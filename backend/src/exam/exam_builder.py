"""
组卷模块（按需出题）
核心流程：按试卷需求出题 → 查重 → 挂卷 → 转入审核
"""
import json
import random
import time
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
                       COUNT(q.id) as q_count, kp.parent_id
                FROM knowledge_points kp
                JOIN knowledge_chunks kc ON kc.knowledge_point_id = kp.id
                LEFT JOIN questions q ON q.knowledge_point_id = kp.id
                WHERE kp.document_id = %s AND kp.id = ANY(%s)
                GROUP BY kp.id, kp.name, kp.parent_id
                ORDER BY q_count ASC
            """, (document_id, kp_ids))
        else:
            cur.execute("""
                SELECT kp.id, kp.name, MIN(kc.id) as chunk_id,
                       COUNT(q.id) as q_count, kp.parent_id
                FROM knowledge_points kp
                JOIN knowledge_chunks kc ON kc.knowledge_point_id = kp.id
                LEFT JOIN questions q ON q.knowledge_point_id = kp.id
                WHERE kp.document_id = %s
                GROUP BY kp.id, kp.name, kp.parent_id
                ORDER BY q_count ASC
            """, (document_id,))
        rows = cur.fetchall()

    kps = [
        {"id": r[0], "name": r[1], "chunk_id": r[2],
         "chapter": r[4] or r[0]}  # 无父节点（章/lecture根）以自身为章
        for r in rows
        if not any(kw in r[1] for kw in skip_kw)
    ]

    # 按章节交错排列：每章轮流取一个（章内保持冷门优先）。
    # 这样题目数量少于知识点数时，也会优先铺满所有章节，而不是
    # 集中在全局排序的前几个知识点上。
    groups = {}
    for kp in kps:
        groups.setdefault(kp["chapter"], []).append(kp)
    buckets = list(groups.values())
    interleaved = []
    depth = 0
    while len(interleaved) < len(kps):
        for b in buckets:
            if depth < len(b):
                interleaved.append(b[depth])
        depth += 1
    return interleaved


def _difficulty_quota(need: int, ratio: dict) -> list:
    """
    按易/中/难比例把need道题分成难度配额列表，如need=10、比例5:3:2
    → [1]*5+[2]*3+[3]*2。ratio为None时全部中等难度。用最大余数法处理
    取整，保证配额总数恰好等于need。
    """
    if not ratio:
        return [2] * need
    weights = {int(k): float(v) for k, v in ratio.items()
               if int(k) in (1, 2, 3) and float(v) > 0}
    total_w = sum(weights.values())
    if not total_w:
        return [2] * need
    exact = {d: need * w / total_w for d, w in weights.items()}
    counts = {d: int(x) for d, x in exact.items()}
    for d in sorted(exact, key=lambda d: exact[d] - counts[d], reverse=True):
        if sum(counts.values()) >= need:
            break
        counts[d] += 1
    quota = []
    for d in sorted(counts):
        quota.extend([d] * counts[d])
    return quota


def create_exam(document_id: int, title: str,
                config: dict, kp_ids: list = None,
                task_id: str = None,
                progress_store: dict = None,
                difficulty_ratio: dict = None,
                chapter_weights: dict = None) -> int:
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
              json.dumps({"config": config, "kp_ids": kp_ids,
                          "difficulty_ratio": difficulty_ratio,
                          "chapter_weights": chapter_weights})))
        paper_id = cur.fetchone()[0]

    fill_exam(paper_id, document_id, config, kp_ids,
              task_id, progress_store,
              difficulty_ratio=difficulty_ratio,
              chapter_weights=chapter_weights)
    return paper_id


def fill_exam(paper_id: int, document_id: int,
              config: dict, kp_ids: list = None,
              task_id: str = None,
              progress_store: dict = None,
              difficulty_ratio: dict = None,
              chapter_weights: dict = None):
    """
    把试卷补齐到config要求的题量（新建和续出共用）。
    按已挂卷的题数计算各题型缺口，只出缺的部分；完成后试卷转入审核。
    """
    start_time = time.time()

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

    # 进度统计：total_target是这份卷子的总题量，per_type记录各题型
    # 已完成/总数。ETA不是写死的估算，是用"这次运行到目前为止的真实
    # 平均每题耗时"乘以剩余题数算出来的——不同电脑配置跑出来的速率
    # 不一样，进度条会自动适配当前机器的真实速度，而不是给一个通用数字。
    total_target = sum(cfg["count"] for cfg in config.values())
    initial_saved = sum(existing.values())
    progress_state = {
        "total_saved": initial_saved,
        "per_type": {t: existing.get(t, 0) for t in config},
    }

    if task_id and progress_store is not None:
        progress_store[task_id] = {
            "stage": "generating",
            "paper_id": paper_id,
            "detail": "开始出题...",
            "total_target": total_target,
            "total_saved": initial_saved,
            "percent": round(initial_saved / total_target * 100, 1)
                       if total_target else 0,
            "per_type": dict(progress_state["per_type"]),
            "eta_seconds": None,
        }

    def report(detail, extra=None):
        if task_id and progress_store is not None:
            elapsed = time.time() - start_time
            saved_this_run = progress_state["total_saved"] - initial_saved
            avg_per_q = elapsed / saved_this_run if saved_this_run > 0 else None
            remaining = max(total_target - progress_state["total_saved"], 0)
            eta_seconds = round(avg_per_q * remaining) if avg_per_q else None
            progress_store[task_id] = {
                "stage": "generating",
                "paper_id": paper_id,
                "detail": detail,
                "total_target": total_target,
                "total_saved": progress_state["total_saved"],
                "percent": round(progress_state["total_saved"] / total_target
                                 * 100, 1) if total_target else 0,
                "per_type": dict(progress_state["per_type"]),
                "elapsed_seconds": round(elapsed),
                "eta_seconds": eta_seconds,
                **(extra or {})
            }

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

    # 按章节分组（章内保持kps原有的冷门优先顺序）
    chapters_order = []
    chapter_kps = {}
    for kp in kps:
        if kp["chapter"] not in chapter_kps:
            chapter_kps[kp["chapter"]] = []
            chapters_order.append(kp["chapter"])
        chapter_kps[kp["chapter"]].append(kp)

    # 该章尝试这么多次仍未产出，放弃对它的优先保底（避免死磕一个查重
    # 命中率高的章节耗尽全部预算，导致其余章节反而一题都分不到）
    GIVEUP_PER_CHAPTER = 4

    # 逐题型补齐缺口（GEN_WORKERS路并发）
    with ThreadPoolExecutor(max_workers=GEN_WORKERS) as pool:
        for q_type, cfg in config.items():
            need = cfg["count"] - existing.get(q_type, 0)
            if need <= 0:
                continue
            score = cfg["score"]
            got = 0
            covered = set()       # 本题型已成功产出的章节
            fails = {c: 0 for c in chapters_order}
            progress_idx = {c: 0 for c in chapters_order}  # 章内轮转指针
            in_flight = {c: 0 for c in chapters_order}
            got_in_ch = {c: 0 for c in chapters_order}
            attempts = 0
            # 覆盖阶段(每章至少一次) + 常规重试预算，防止死循环
            max_attempts = need * 5 + len(chapters_order) * GIVEUP_PER_CHAPTER
            pending = {}  # future -> (chapter, difficulty)
            # 难度配额：按比例分好，提交时领取，失败退还
            diff_pool = _difficulty_quota(need, difficulty_ratio)
            random.shuffle(diff_pool)

            # 章节目标配额（用户设置了章节比例时生效）
            ch_w = {int(k): float(v) for k, v in (chapter_weights or {}).items()
                    if int(k) in chapter_kps and float(v) > 0}
            ch_target = {}
            if ch_w:
                total_w = sum(ch_w.values())
                ch_target = {c: need * w / total_w for c, w in ch_w.items()}

            def pick_chapter():
                if ch_target:
                    # 有章节比例：选缺口最大的章（目标-已得-在飞），
                    # 连续失败超阈值的章不再优先
                    cands = [(c, ch_target[c] - got_in_ch[c] - in_flight[c])
                             for c in ch_target
                             if fails[c] < GIVEUP_PER_CHAPTER]
                    cands = [x for x in cands if x[1] > 0] or \
                            [(c, 0) for c in chapters_order]
                    return max(cands, key=lambda x: x[1])[0]
                uncovered = [c for c in chapters_order
                            if c not in covered and fails[c] < GIVEUP_PER_CHAPTER]
                candidates = uncovered or chapters_order
                return min(candidates, key=lambda c: in_flight[c])

            while (got < need and attempts < max_attempts) or pending:
                # 补满在飞任务；got+在飞 不超过 need，避免尾部多出题
                while (len(pending) < GEN_WORKERS
                       and attempts < max_attempts
                       and got + len(pending) < need):
                    chapter = pick_chapter()
                    kps_in_ch = chapter_kps[chapter]
                    kp = kps_in_ch[progress_idx[chapter] % len(kps_in_ch)]
                    progress_idx[chapter] += 1
                    in_flight[chapter] += 1
                    dim = random.choice(dims_by_type[q_type])
                    difficulty = diff_pool.pop() if diff_pool else 2
                    fut = pool.submit(
                        generate_one_question, document_id, kp["id"],
                        kp["name"], kp["chunk_id"], q_type, dim, difficulty)
                    pending[fut] = (chapter, difficulty)
                    attempts += 1

                if not pending:
                    break

                report(f"出题中：{q_type} {got+1}/{need}"
                       f"（已覆盖{len(covered)}/{len(chapters_order)}章）",
                       {"totals": dict(totals)})

                done, still_pending = wait(pending.keys(),
                                           return_when=FIRST_COMPLETED)
                for fut in done:
                    chapter, fut_diff = pending.pop(fut)
                    in_flight[chapter] -= 1
                    try:
                        result = fut.result()
                    except Exception:
                        result = {"status": "failed"}
                    totals[result["status"]] = \
                        totals.get(result["status"], 0) + 1

                    if result["status"] == "saved" and got < need:
                        covered.add(chapter)
                        got_in_ch[chapter] += 1
                        question_order += 1
                        got += 1
                        progress_state["total_saved"] += 1
                        progress_state["per_type"][q_type] += 1
                        # 挂到试卷上
                        with get_db() as (conn, cur):
                            cur.execute("""
                                INSERT INTO exam_paper_questions
                                    (paper_id, question_id,
                                     question_order, score)
                                VALUES (%s, %s, %s, %s)
                            """, (paper_id, result["question_id"],
                                  question_order, score))
                        report(f"出题中：{q_type} {got}/{need}"
                               f"（已覆盖{len(covered)}/{len(chapters_order)}章）",
                               {"totals": dict(totals)})
                    elif result["status"] != "saved":
                        fails[chapter] += 1
                        diff_pool.append(fut_diff)  # 失败退还难度配额
                # pending已在上面逐个pop完done的，此时恰好只剩still_pending

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
            "generated": question_order,
            "total_target": total_target,
            "total_saved": progress_state["total_saved"],
            "percent": round(progress_state["total_saved"] / total_target
                             * 100, 1) if total_target else 100,
            "per_type": dict(progress_state["per_type"]),
            "elapsed_seconds": round(time.time() - start_time),
            "eta_seconds": 0,
        }

    return paper_id