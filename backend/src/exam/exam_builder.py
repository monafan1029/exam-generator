"""
组卷模块（按需出题）
核心流程：按试卷需求出题 → 查重 → 挂卷 → 转入审核
"""
import json
import random
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from ..database import get_db
from ..generator.question_generator import generate_one_question
from ..generator import prompts

# 出题并发数（本地Ollama，2路在生成/查重/质检/入库各环节间流水重叠）
GEN_WORKERS = 2


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


    # 1. 创建空试卷（出题配置落库，中断后可通过resume继续）
    with get_db() as (conn, cur):
        cur.execute("""
            INSERT INTO exam_papers
                (title, document_id, status, version, gen_config)
            VALUES (%s, %s, 'generating', 1, %s)
            RETURNING id
        """, (title, document_id,
              json.dumps({"config": config, "kp_ids": kp_ids})))
        paper_id = cur.fetchone()[0]

    fill_exam(paper_id, document_id, config, kp_ids,
              task_id, progress_store)
    return paper_id


def fill_exam(paper_id: int, document_id: int,
              config: dict, kp_ids: list = None,
              task_id: str = None,
              progress_store: dict = None):
    """
    把试卷补齐到config要求的题量（新建和续出共用）。
    按已挂卷的题数计算各题型缺口，只出缺的部分；完成后试卷转入审核。
    """
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

    # 已有的题（断点续出场景）
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT q.question_type, COUNT(*),
                   COALESCE(MAX(epq.question_order), 0)
            FROM exam_paper_questions epq
            JOIN questions q ON epq.question_id = q.id
            WHERE epq.paper_id = %s
            GROUP BY q.question_type
        """, (paper_id,))
        rows = cur.fetchall()
    existing = {r[0]: r[1] for r in rows}
    question_order = max((r[2] for r in rows), default=0)

    kps = get_knowledge_points_in_scope(document_id, kp_ids)
    if not kps:
        raise ValueError("选定范围内没有可用知识点")

    all_dims = list(prompts.DIMENSIONS.keys())
    # 反例排除（"下列哪项不正确"）只适合选择题，简答题没有选项可排除
    dims_by_type = {
        "single_select": all_dims,
        "multi_select": all_dims,
        "short_answer": [d for d in all_dims if d != "counter"],
    }
    totals = {"saved": 0, "duplicate": 0, "rejected": 0, "failed": 0}

    # 逐题型补齐缺口（GEN_WORKERS路并发）
    with ThreadPoolExecutor(max_workers=GEN_WORKERS) as pool:
        for q_type, cfg in config.items():
            need = cfg["count"] - existing.get(q_type, 0)
            if need <= 0:
                continue
            score = cfg["score"]
            got = 0
            kp_index = 0
            attempts = 0
            max_attempts = need * 5  # 防止死循环：查重/失败太多时兜底退出
            pending = set()

            while (got < need and attempts < max_attempts) or pending:
                # 补满在飞任务；got+在飞 不超过 need，避免尾部多出题
                while (len(pending) < GEN_WORKERS
                       and attempts < max_attempts
                       and got + len(pending) < need):
                    # 轮转知识点（冷门优先，循环取）
                    kp = kps[kp_index % len(kps)]
                    kp_index += 1
                    dim = random.choice(dims_by_type[q_type])
                    pending.add(pool.submit(
                        generate_one_question, document_id, kp["id"],
                        kp["name"], kp["chunk_id"], q_type, dim))
                    attempts += 1

                if not pending:
                    break

                report(f"出题中：{q_type} {got+1}/{need}",
                       {"totals": dict(totals)})

                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for fut in done:
                    try:
                        result = fut.result()
                    except Exception:
                        result = {"status": "failed"}
                    totals[result["status"]] = \
                        totals.get(result["status"], 0) + 1

                    if result["status"] == "saved" and got < need:
                        question_order += 1
                        got += 1
                        # 挂到试卷上
                        with get_db() as (conn, cur):
                            cur.execute("""
                                INSERT INTO exam_paper_questions
                                    (paper_id, question_id,
                                     question_order, score)
                                VALUES (%s, %s, %s, %s)
                            """, (paper_id, result["question_id"],
                                  question_order, score))

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