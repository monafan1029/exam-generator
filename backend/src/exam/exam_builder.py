"""
组卷模块（按需出题）
核心流程：按试卷需求出题 → 查重 → 挂卷 → 转入审核
"""
import time
import random
from ..database import get_db
from ..generator.question_generator import generate_one_question
from ..generator import prompts


def get_knowledge_points_in_scope(document_id: int,
                                   kp_ids: list = None) -> list:
    """
    获取出题范围内的知识点
    kp_ids为None时用全部知识点，否则只用指定的
    过滤掉小结/练习类，并按历史出题次数升序（冷门知识点优先）
    """
    skip_kw = ["本章小结", "思考与练习", "参考文献", "附录"]
    with get_db() as (conn, cur):
        if kp_ids:
            cur.execute("""
                SELECT kp.id, kp.name, MIN(kc.id) as chunk_id,
                       COUNT(q.id) as q_count
                FROM knowledge_points kp
                JOIN knowledge_chunks kc ON kc.knowledge_point_id = kp.id
                LEFT JOIN questions q ON q.knowledge_point_id = kp.id
                WHERE kp.document_id = %s AND kp.id = ANY(%s)
                GROUP BY kp.id, kp.name
                ORDER BY q_count ASC
            """, (document_id, kp_ids))
        else:
            cur.execute("""
                SELECT kp.id, kp.name, MIN(kc.id) as chunk_id,
                       COUNT(q.id) as q_count
                FROM knowledge_points kp
                JOIN knowledge_chunks kc ON kc.knowledge_point_id = kp.id
                LEFT JOIN questions q ON q.knowledge_point_id = kp.id
                WHERE kp.document_id = %s
                GROUP BY kp.id, kp.name
                ORDER BY q_count ASC
            """, (document_id,))
        rows = cur.fetchall()

    return [
        {"id": r[0], "name": r[1], "chunk_id": r[2]}
        for r in rows
        if not any(kw in r[1] for kw in skip_kw)
    ]


def create_exam(document_id: int, title: str,
                config: dict, kp_ids: list = None,
                task_id: str = None,
                progress_store: dict = None) -> int:
    """
    按需出题组卷
    config示例: {
        "single_select": {"count": 10, "score": 4},
        "multi_select":  {"count": 5,  "score": 6},
        "short_answer":  {"count": 2,  "score": 10}
    }
    返回 paper_id
    """


    # 1. 创建空试卷
    with get_db() as (conn, cur):
        cur.execute("""
            INSERT INTO exam_papers
                (title, document_id, status, version)
            VALUES (%s, %s, 'generating', 1)
            RETURNING id
        """, (title, document_id))
        paper_id = cur.fetchone()[0]
    
    if task_id and progress_store is not None:
        progress_store[task_id] = {
            "stage": "generating",
            "paper_id": paper_id,
            "detail": "开始出题..."
        }

    def report(detail, extra=None):
        if task_id and progress_store is not None:
            progress_store[task_id] = {
                "stage": "generating",
                "paper_id": paper_id,
                "detail": detail,
                **(extra or {})
            }
    # 2. 获取知识点范围
    kps = get_knowledge_points_in_scope(document_id, kp_ids)
    if not kps:
        raise ValueError("选定范围内没有可用知识点")

    dimensions = list(prompts.DIMENSIONS.keys())
    question_order = 0
    totals = {"saved": 0, "duplicate": 0, "rejected": 0, "failed": 0}

    # 3. 逐题型按需出题
    for q_type, cfg in config.items():
        need = cfg["count"]
        score = cfg["score"]
        got = 0
        kp_index = 0
        attempts = 0
        max_attempts = need * 5  # 防止死循环：查重/失败太多时兜底退出

        while got < need and attempts < max_attempts:
            attempts += 1
            # 轮转知识点（冷门优先，循环取）
            kp = kps[kp_index % len(kps)]
            kp_index += 1
            dim = random.choice(dimensions)

            report(f"出题中：{q_type} {got+1}/{need}（{kp['name']}）",
                   {"totals": dict(totals)})

            result = generate_one_question(
                document_id, kp["id"], kp["name"],
                kp["chunk_id"], q_type, dim)
            totals[result["status"]] += 1

            if result["status"] == "saved":
                question_order += 1
                got += 1
                # 挂到试卷上
                with get_db() as (conn, cur):
                    cur.execute("""
                        INSERT INTO exam_paper_questions
                            (paper_id, question_id, question_order, score)
                        VALUES (%s, %s, %s, %s)
                    """, (paper_id, result["question_id"],
                          question_order, score))

            time.sleep(0.5)

    # 4. 试卷转入审核状态
    with get_db() as (conn, cur):
        cur.execute("""
            UPDATE exam_papers SET status = 'reviewing' WHERE id = %s
        """, (paper_id,))

    if task_id and progress_store is not None:
        progress_store[task_id] = {
            "stage": "done",
            "paper_id": paper_id,
            "totals": totals,
            "generated": question_order
        }

    return paper_id