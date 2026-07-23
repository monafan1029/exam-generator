"""
FastAPI 主入口
提供教材上传、知识库构建、出题、组卷、导出的完整API
"""
import os
import shutil
import time
import threading

from fastapi.responses import FileResponse
from src.export.pdf_exporter import export_pdfs
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from src.exam.exam_builder import create_exam

from src.config import BACKEND_PORT
from src.database import get_db
from src.parser.document_parser import parse_document
from src.knowledge.extractor import extract_and_save
from src.knowledge.chunker import chunk_and_label
from src.knowledge.embedder import embed_document_chunks
from src.generator.question_generator import generate_for_knowledge_point

app = FastAPI(
    title="智能出题系统 API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 用一个简单的内存字典记录后台任务进度
# （单机部署够用；多实例部署时需要换成Redis）
task_progress = {}


# ============================================================
# 基础接口
# ============================================================
@app.get("/health")
def health():
    try:
        with get_db() as (conn, cur):
            cur.execute("SELECT 1")
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "error", "database": str(e)}


# ============================================================
# 1. 上传教材 + 构建知识库（后台任务）
# ============================================================
def build_knowledge_base(filepath: str, filename: str, task_id: str):
    """后台任务：解析→提取知识点→切片→向量化"""
    try:
        task_progress[task_id] = {"stage": "parsing", "detail": "解析文档中"}
        text = parse_document(filepath)

        task_progress[task_id] = {"stage": "extracting",
                                  "detail": "提取知识点体系中"}
        result = extract_and_save(text, filename, filepath)
        document_id = result["document_id"]

        task_progress[task_id] = {"stage": "chunking",
                                  "detail": "切片与打标签中",
                                  "document_id": document_id}

        def chunk_progress(order, labeled, unlabeled):
            task_progress[task_id]["detail"] = \
                f"切片中：已处理{order}块（标签{labeled}/未匹配{unlabeled}）"

        chunk_result = chunk_and_label(text, document_id, chunk_progress)

        task_progress[task_id] = {"stage": "embedding",
                                  "detail": "向量化中",
                                  "document_id": document_id}

        def embed_progress(done, total):
            task_progress[task_id]["detail"] = f"向量化：{done}/{total}"

        embed_result = embed_document_chunks(document_id, embed_progress)

        task_progress[task_id] = {
            "stage": "done",
            "document_id": document_id,
            "subject": result["subject"],
            "knowledge_points": result["knowledge_points"],
            "chunks": chunk_result["total_chunks"],
            "embedded": embed_result["success"]
        }
    except Exception as e:
        task_progress[task_id] = {"stage": "failed", "error": str(e)}


@app.post("/api/documents/upload")
async def upload_document(background_tasks: BackgroundTasks,
                          file: UploadFile = File(...)):
    """上传教材，后台自动构建知识库"""
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ("pdf", "docx"):
        raise HTTPException(400, "只支持 PDF 和 Word(.docx) 文件")

    filepath = os.path.join(UPLOAD_DIR, file.filename)
    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)

    task_id = f"build_{file.filename}"
    task_progress[task_id] = {"stage": "queued"}
    background_tasks.add_task(build_knowledge_base,
                              filepath, file.filename, task_id)

    return {"task_id": task_id, "message": "已开始构建知识库"}


@app.get("/api/tasks/{task_id}")
def get_task_progress(task_id: str):
    """查询后台任务进度（前端轮询这个接口显示进度条）"""
    if task_id not in task_progress:
        raise HTTPException(404, "任务不存在")
    return task_progress[task_id]


# ============================================================
# 2. 知识库查询
# ============================================================
@app.get("/api/documents")
def list_documents():
    """列出所有已上传的教材"""
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT id, filename, subject, status, upload_time
            FROM documents ORDER BY upload_time DESC
        """)
        rows = cur.fetchall()
    return [
        {"id": r[0], "filename": r[1], "subject": r[2],
         "status": r[3], "upload_time": str(r[4])}
        for r in rows
    ]


@app.get("/api/documents/{document_id}/knowledge-points")
def list_knowledge_points(document_id: int):
    """列出某教材的知识点树"""
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT id, code, name, name_en, parent_id, level
            FROM knowledge_points
            WHERE document_id = %s ORDER BY id
        """, (document_id,))
        rows = cur.fetchall()
    return [
        {"id": r[0], "code": r[1], "name": r[2],
         "name_en": r[3], "parent_id": r[4], "level": r[5]}
        for r in rows
    ]


# ============================================================
# 3. 出题（后台任务）
# ============================================================
class GenerateRequest(BaseModel):
    document_id: int
    count_single: int = 1   # 每个知识点出几道单选
    count_multi: int = 1    # 每个知识点出几道多选
    count_short: int = 1    # 每个知识点出几道简答

def run_generation(document_id: int, counts: dict, task_id: str):
    """后台任务：批量出题"""
    try:
        skip_kw = ["本章小结", "思考与练习", "参考文献", "附录"]
        with get_db() as (conn, cur):
            cur.execute("""
                SELECT kp.id, kp.name, MIN(kc.id)
                FROM knowledge_points kp
                JOIN knowledge_chunks kc ON kc.knowledge_point_id = kp.id
                WHERE kp.document_id = %s
                GROUP BY kp.id, kp.name ORDER BY kp.id
            """, (document_id,))
            kps = [
                {"id": r[0], "name": r[1], "chunk_id": r[2]}
                for r in cur.fetchall()
                if not any(kw in r[1] for kw in skip_kw)
            ]

        totals = {"saved": 0, "duplicate": 0,
                  "rejected": 0, "failed": 0}

        for i, kp in enumerate(kps):
            task_progress[task_id] = {
                "stage": "generating",
                "detail": f"[{i+1}/{len(kps)}] {kp['name']}",
                "totals": dict(totals)
            }
            stats = generate_for_knowledge_point(
                document_id, kp["id"], kp["name"],
                kp["chunk_id"], counts)
            for k in totals:
                totals[k] += stats.get(k, 0)

        task_progress[task_id] = {"stage": "done", "totals": totals}
    except Exception as e:
        task_progress[task_id] = {"stage": "failed", "error": str(e)}


@app.post("/api/questions/generate")
def generate_questions(req: GenerateRequest,
                       background_tasks: BackgroundTasks):
    """启动批量出题任务"""
    counts = {
        "single_select": req.count_single,
        "multi_select": req.count_multi,
        "short_answer": req.count_short,
    }
    task_id = f"gen_{req.document_id}"
    task_progress[task_id] = {"stage": "queued"}
    background_tasks.add_task(run_generation,
                              req.document_id, counts, task_id)
    return {"task_id": task_id, "message": "出题任务已启动"}

@app.get("/api/documents/{document_id}/questions/stats")
def question_stats(document_id: int):
    """题库统计"""
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT question_type, status, COUNT(*)
            FROM questions WHERE document_id = %s
            GROUP BY question_type, status
        """, (document_id,))
        rows = cur.fetchall()
    return [
        {"type": r[0], "status": r[1], "count": r[2]}
        for r in rows
    ]

@app.delete("/api/documents/{document_id}")
def delete_document(document_id: int):
    """删除教材及其所有关联数据（知识点、切片、题目、试卷、审核记录）"""
    with get_db() as (conn, cur):
        # 1. 先删审核记录（它同时引用questions和exam_papers）
        cur.execute("""
            DELETE FROM review_logs WHERE paper_id IN
            (SELECT id FROM exam_papers WHERE document_id = %s)
        """, (document_id,))
        cur.execute("""
            DELETE FROM review_logs WHERE question_id IN
            (SELECT id FROM questions WHERE document_id = %s)
        """, (document_id,))
        # 2. 删试卷-题目关联
        cur.execute("""
            DELETE FROM exam_paper_questions WHERE paper_id IN
            (SELECT id FROM exam_papers WHERE document_id = %s)
        """, (document_id,))
        # 3. 删题目和试卷
        cur.execute("DELETE FROM questions WHERE document_id = %s",
                    (document_id,))
        cur.execute("DELETE FROM exam_papers WHERE document_id = %s",
                    (document_id,))
        # 4. 删文档（知识点和切片会CASCADE自动删）
        cur.execute("DELETE FROM documents WHERE id = %s", (document_id,))
    return {"message": "已删除"}

# ============================================================
# 4. 题目审核
# ============================================================
class StatusUpdate(BaseModel):
    status: str  # approved / retired


class ContentUpdate(BaseModel):
    content: dict


@app.get("/api/documents/{document_id}/questions")
def list_questions(document_id: int, status: str = None,
                   question_type: str = None):
    """题目列表，支持按状态和题型筛选"""
    sql = """
        SELECT q.id, q.question_type, q.difficulty, q.content,
               q.status, q.dimension, kp.name
        FROM questions q
        JOIN knowledge_points kp ON q.knowledge_point_id = kp.id
        WHERE q.document_id = %s
    """
    params = [document_id]
    if status:
        sql += " AND q.status = %s"
        params.append(status)
    if question_type:
        sql += " AND q.question_type = %s"
        params.append(question_type)
    sql += " ORDER BY q.id"

    with get_db() as (conn, cur):
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [
        {"id": r[0], "type": r[1], "difficulty": r[2],
         "content": r[3], "status": r[4],
         "dimension": r[5], "kp_name": r[6]}
        for r in rows
    ]


@app.put("/api/questions/{question_id}/status")
def update_question_status(question_id: int, req: StatusUpdate):
    """审核操作：通过(approved)或废弃(retired)"""
    if req.status not in ("approved", "retired", "draft"):
        raise HTTPException(400, "无效的状态值")
    with get_db() as (conn, cur):
        cur.execute("""
            UPDATE questions SET status = %s WHERE id = %s
        """, (req.status, question_id))
    return {"message": "已更新"}


@app.put("/api/questions/{question_id}/content")
def update_question_content(question_id: int, req: ContentUpdate):
    """人工编辑题目内容，编辑后自动标记为approved"""
    import json as _json
    with get_db() as (conn, cur):
        cur.execute("""
            UPDATE questions
            SET content = %s, status = 'approved'
            WHERE id = %s
        """, (_json.dumps(req.content, ensure_ascii=False), question_id))
    return {"message": "已保存并通过审核"}

# ============================================================
# 5. 组卷（按需出题）
# ============================================================
class ExamTypeConfig(BaseModel):
    count: int
    score: float


class CreateExamRequest(BaseModel):
    document_id: int
    title: str
    single_select: ExamTypeConfig = None
    multi_select: ExamTypeConfig = None
    short_answer: ExamTypeConfig = None
    kp_ids: list[int] = None   # 选定的知识点范围，None表示全部
    difficulty_ratio: dict = None    # {"1":易权重,"2":中,"3":难}，None=全中等
    chapter_weights: dict = None     # {章节kp_id: 权重}，None=均匀覆盖


def run_create_exam(document_id: int, title: str,
                    config: dict, kp_ids: list, task_id: str,
                    difficulty_ratio: dict = None,
                    chapter_weights: dict = None):
    """后台任务：按需出题组卷"""
    try:
        create_exam(document_id, title, config, kp_ids,
                    task_id, task_progress,
                    difficulty_ratio=difficulty_ratio,
                    chapter_weights=chapter_weights)
    except Exception as e:
        task_progress[task_id] = {"stage": "failed", "error": str(e)}


@app.post("/api/exams/create")
def create_exam_api(req: CreateExamRequest):
    """启动组卷任务（按需出题）"""
    config = {}
    if req.single_select and req.single_select.count > 0:
        config["single_select"] = {
            "count": req.single_select.count,
            "score": req.single_select.score
        }
    if req.multi_select and req.multi_select.count > 0:
        config["multi_select"] = {
            "count": req.multi_select.count,
            "score": req.multi_select.score
        }
    if req.short_answer and req.short_answer.count > 0:
        config["short_answer"] = {
            "count": req.short_answer.count,
            "score": req.short_answer.score
        }

    if not config:
        raise HTTPException(400, "至少要设置一种题型的数量")

    task_id = f"exam_{req.document_id}_{int(time.time())}"
    task_progress[task_id] = {"stage": "queued"}

    thread = threading.Thread(
        target=run_create_exam,
        args=(req.document_id, req.title, config, req.kp_ids, task_id,
              req.difficulty_ratio, req.chapter_weights),
        daemon=True
    )
    thread.start()

    return {"task_id": task_id, "message": "组卷任务已启动"}


@app.get("/api/exams")
def list_exams(document_id: int = None):
    """试卷列表"""
    sql = """
        SELECT ep.id, ep.title, ep.status, ep.created_at,
               d.subject, COUNT(epq.id) as question_count,
               COALESCE(SUM(epq.score), 0) as total_score
        FROM exam_papers ep
        JOIN documents d ON ep.document_id = d.id
        LEFT JOIN exam_paper_questions epq ON epq.paper_id = ep.id
    """
    params = []
    if document_id:
        sql += " WHERE ep.document_id = %s"
        params.append(document_id)
    sql += """
        GROUP BY ep.id, ep.title, ep.status, ep.created_at, d.subject
        ORDER BY ep.created_at DESC
    """

    with get_db() as (conn, cur):
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [
        {"id": r[0], "title": r[1], "status": r[2],
         "created_at": str(r[3]), "subject": r[4],
         "question_count": r[5], "total_score": float(r[6])}
        for r in rows
    ]


@app.get("/api/exams/{paper_id}")
def get_exam(paper_id: int):
    """试卷详情（含所有题目，用于审核）"""
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT ep.title, ep.status, ep.document_id, d.subject
            FROM exam_papers ep
            JOIN documents d ON ep.document_id = d.id
            WHERE ep.id = %s
        """, (paper_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "试卷不存在")
        title, status, document_id, subject = row

        cur.execute("""
            SELECT q.id, epq.question_order, epq.score,
                   q.question_type, q.content, q.status,
                   q.dimension, kp.name, kp.id
            FROM exam_paper_questions epq
            JOIN questions q ON epq.question_id = q.id
            JOIN knowledge_points kp ON q.knowledge_point_id = kp.id
            WHERE epq.paper_id = %s
            ORDER BY epq.question_order
        """, (paper_id,))
        questions = [
            {"id": r[0], "order": r[1], "score": float(r[2]),
             "type": r[3], "content": r[4], "status": r[5],
             "dimension": r[6], "kp_name": r[7], "kp_id": r[8]}
            for r in cur.fetchall()
        ]

    return {
        "id": paper_id,
        "title": title,
        "status": status,
        "document_id": document_id,
        "subject": subject,
        "questions": questions,
        "total_score": sum(q["score"] for q in questions)
    }


@app.post("/api/exams/{paper_id}/resume")
def resume_exam(paper_id: int):
    """
    继续出题：出题中断（刷新/后端重启）的试卷按落库的配置补齐缺口。
    补齐后自动转入审核状态。
    """
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT document_id, status, gen_config
            FROM exam_papers WHERE id = %s
        """, (paper_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "试卷不存在")
    document_id, status, gen_config = row

    if status == "approved":
        raise HTTPException(400, "试卷已成卷，无需继续出题")
    if not gen_config or not gen_config.get("config"):
        raise HTTPException(
            400, "该试卷没有保存出题配置（旧版本创建），无法继续，请删除后重新组卷")

    with get_db() as (conn, cur):
        cur.execute("""
            UPDATE exam_papers SET status = 'generating' WHERE id = %s
        """, (paper_id,))

    task_id = f"exam_resume_{paper_id}_{int(time.time())}"
    task_progress[task_id] = {"stage": "queued", "paper_id": paper_id}

    def run_fill():
        try:
            from src.exam.exam_builder import fill_exam
            fill_exam(paper_id, document_id,
                      gen_config["config"], gen_config.get("kp_ids"),
                      task_id, task_progress,
                      difficulty_ratio=gen_config.get("difficulty_ratio"),
                      chapter_weights=gen_config.get("chapter_weights"))
        except Exception as e:
            task_progress[task_id] = {
                "stage": "failed", "error": str(e), "paper_id": paper_id}

    threading.Thread(target=run_fill, daemon=True).start()
    return {"task_id": task_id, "paper_id": paper_id,
            "message": "已继续出题"}


@app.delete("/api/exams/{paper_id}")
def delete_exam(paper_id: int):
    """删除试卷（题库中的题目本身不受影响，仅移除该试卷及其题目关联）"""
    with get_db() as (conn, cur):
        cur.execute("SELECT id FROM exam_papers WHERE id = %s", (paper_id,))
        if not cur.fetchone():
            raise HTTPException(404, "试卷不存在")
        cur.execute("DELETE FROM review_logs WHERE paper_id = %s", (paper_id,))
        cur.execute("DELETE FROM exam_paper_questions WHERE paper_id = %s",
                    (paper_id,))
        cur.execute("DELETE FROM exam_papers WHERE id = %s", (paper_id,))
    return {"message": "已删除"}


@app.post("/api/exams/{paper_id}/replace/{question_id}")
def replace_question(paper_id: int, question_id: int,
                     new_kp_id: int = None):
    """
    换题：废弃当前题，重新生成一道补上。
    new_kp_id指定新题的知识点（换章节出题）；不传则沿用原知识点。
    """
    from src.generator.question_generator import generate_one_question
    from src.generator import prompts
    import random

    with get_db() as (conn, cur):
        # 找到这道题在卷子里的信息
        cur.execute("""
            SELECT epq.question_order, epq.score, q.question_type,
                   q.knowledge_point_id, q.source_chunk_id,
                   ep.document_id, kp.name
            FROM exam_paper_questions epq
            JOIN questions q ON epq.question_id = q.id
            JOIN exam_papers ep ON epq.paper_id = ep.id
            JOIN knowledge_points kp ON q.knowledge_point_id = kp.id
            WHERE epq.paper_id = %s AND epq.question_id = %s
        """, (paper_id, question_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "题目不在该试卷中")
        order, score, q_type, kp_id, chunk_id, document_id, kp_name = row

        # 指定了新知识点：校验其存在且有可出题的切片
        if new_kp_id and new_kp_id != kp_id:
            cur.execute("""
                SELECT kp.name, MIN(kc.id)
                FROM knowledge_points kp
                JOIN knowledge_chunks kc ON kc.knowledge_point_id = kp.id
                WHERE kp.id = %s AND kp.document_id = %s
                GROUP BY kp.name
            """, (new_kp_id, document_id))
            kp_row = cur.fetchone()
            if not kp_row:
                raise HTTPException(400, "该知识点没有可出题的内容")
            kp_id, chunk_id = new_kp_id, kp_row[1]
            kp_name = kp_row[0]

        # 废弃旧题
        cur.execute("UPDATE questions SET status='retired' WHERE id=%s",
                    (question_id,))
        cur.execute("""
            DELETE FROM exam_paper_questions
            WHERE paper_id = %s AND question_id = %s
        """, (paper_id, question_id))

    # 生成新题（最多试5次）；反例排除维度不适合简答题
    dimensions = [d for d in prompts.DIMENSIONS
                  if not (q_type == "short_answer" and d == "counter")]
    for _ in range(5):
        dim = random.choice(dimensions)
        result = generate_one_question(
            document_id, kp_id, kp_name, chunk_id, q_type, dim)
        if result["status"] == "saved":
            with get_db() as (conn, cur):
                cur.execute("""
                    INSERT INTO exam_paper_questions
                        (paper_id, question_id, question_order, score)
                    VALUES (%s, %s, %s, %s)
                """, (paper_id, result["question_id"], order, score))
            return {"message": "已换题", "new_question_id": result["question_id"]}

    raise HTTPException(500, "换题失败，请重试")


@app.post("/api/exams/{paper_id}/approve")
def approve_exam(paper_id: int):
    """成卷：全部题目标记approved，试卷转approved"""
    with get_db() as (conn, cur):
        cur.execute("""
            UPDATE questions SET status = 'approved'
            WHERE id IN (
                SELECT question_id FROM exam_paper_questions
                WHERE paper_id = %s
            )
        """, (paper_id,))
        cur.execute("""
            UPDATE exam_papers
            SET status = 'approved', approved_at = NOW()
            WHERE id = %s
        """, (paper_id,))
    return {"message": "试卷已通过审核"}

class ManualExamRequest(BaseModel):
    document_id: int
    title: str
    questions: list[dict]  # [{"id": 5, "score": 4}, {"id": 8, "score": 6}, ...]


@app.post("/api/exams/create-manual")
def create_manual_exam(req: ManualExamRequest):
    """从题库手动选题组卷，直接成卷（不走审核）"""
    if not req.questions:
        raise HTTPException(400, "请至少选择一道题")

    with get_db() as (conn, cur):
        # 创建试卷，直接approved
        cur.execute("""
            INSERT INTO exam_papers
                (title, document_id, status, version, approved_at)
            VALUES (%s, %s, 'approved', 1, NOW())
            RETURNING id
        """, (req.title, req.document_id))
        paper_id = cur.fetchone()[0]

        # 按题型排序：单选→多选→简答
        cur.execute("""
            SELECT id, question_type FROM questions
            WHERE id = ANY(%s)
        """, ([q["id"] for q in req.questions],))
        type_map = {r[0]: r[1] for r in cur.fetchall()}

        order_priority = {"single_select": 1, "multi_select": 2,
                          "short_answer": 3}
        sorted_qs = sorted(
            req.questions,
            key=lambda q: order_priority.get(type_map.get(q["id"], ""), 9)
        )

        for i, q in enumerate(sorted_qs):
            cur.execute("""
                INSERT INTO exam_paper_questions
                    (paper_id, question_id, question_order, score)
                VALUES (%s, %s, %s, %s)
            """, (paper_id, q["id"], i + 1, q["score"]))

            # 更新使用统计
            cur.execute("""
                UPDATE questions
                SET use_count = use_count + 1, last_used_at = NOW()
                WHERE id = %s
            """, (q["id"],))

    return {"paper_id": paper_id, "message": "试卷已生成"}

DIFF_LABELS = {1: "易", 2: "中", 3: "难", 4: "中"}  # 旧数据4按中处理


def _load_export_rows(paper_id: int) -> list:
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT epq.question_order, q.question_type, q.difficulty,
                   kp.name, q.content, epq.score
            FROM exam_paper_questions epq
            JOIN questions q ON epq.question_id = q.id
            JOIN knowledge_points kp ON q.knowledge_point_id = kp.id
            WHERE epq.paper_id = %s ORDER BY epq.question_order
        """, (paper_id,))
        rows = cur.fetchall()
    if not rows:
        raise HTTPException(404, "试卷不存在或没有题目")
    out = []
    type_names = {"single_select": "单选题", "multi_select": "多选题",
                  "short_answer": "简答题"}
    for order, qtype, diff, kp_name, c, score in rows:
        ans = c.get("answer", "")
        out.append({
            "order": order,
            "type": type_names.get(qtype, qtype),
            "difficulty": DIFF_LABELS.get(diff, "中"),
            "knowledge_point": kp_name.strip(),
            "question": c.get("question", ""),
            "option_a": (c.get("options") or {}).get("A", ""),
            "option_b": (c.get("options") or {}).get("B", ""),
            "option_c": (c.get("options") or {}).get("C", ""),
            "option_d": (c.get("options") or {}).get("D", ""),
            "answer": "、".join(ans) if isinstance(ans, list) else str(ans),
            "explanation": c.get("explanation", ""),
            "model_answer": c.get("model_answer", ""),
            "key_points": "；".join(c.get("key_points") or []),
            "score": float(score),
        })
    return out


@app.get("/api/exams/{paper_id}/export/{fmt}")
def export_exam(paper_id: int, fmt: str):
    """导出在线考试系统通用格式。fmt: xlsx（每题一行）/ json（结构化）"""
    if fmt not in ("xlsx", "json"):
        raise HTTPException(400, "fmt必须是xlsx或json")
    rows = _load_export_rows(paper_id)

    if fmt == "json":
        from fastapi.responses import JSONResponse
        return JSONResponse(
            content={"paper_id": paper_id, "questions": rows},
            headers={"Content-Disposition":
                     f'attachment; filename="paper_{paper_id}.json"'})

    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "试卷"
    headers = ["序号", "题型", "难度", "知识点", "题干", "选项A", "选项B",
               "选项C", "选项D", "答案", "解析", "参考答案", "评分要点", "分值"]
    ws.append(headers)
    for r in rows:
        ws.append([r["order"], r["type"], r["difficulty"],
                   r["knowledge_point"], r["question"], r["option_a"],
                   r["option_b"], r["option_c"], r["option_d"], r["answer"],
                   r["explanation"], r["model_answer"], r["key_points"],
                   r["score"]])
    path = os.path.join(os.path.dirname(__file__), "outputs",
                        f"paper_{paper_id}_export.xlsx")
    wb.save(path)
    return FileResponse(
        path, filename=f"试卷_{paper_id}_导出.xlsx",
        media_type="application/vnd.openxmlformats-officedocument"
                   ".spreadsheetml.sheet")


@app.get("/api/exams/{paper_id}/pdf/{version}")
def download_pdf(paper_id: int, version: str):
    """下载试卷PDF。version: exam（题目版）/ answer（答案版）"""
    if version not in ("exam", "answer"):
        raise HTTPException(400, "version必须是exam或answer")

    result = export_pdfs(paper_id)
    path = result["exam_pdf"] if version == "exam" else result["answer_pdf"]
    filename = f"试卷_{paper_id}_{'题目版' if version == 'exam' else '答案版'}.pdf"
    return FileResponse(path, filename=filename,
                        media_type="application/pdf")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0",
                port=BACKEND_PORT, reload=True)