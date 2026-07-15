"""
出题引擎（核心模块）
- 多维度出题：同一知识点从6个维度出题，实现"无限出题"
- CoT两步生成：先分析再出题，每步输出短，不截断
- LLM-as-a-Judge：多选题和简答题生成后自动质检
- 向量查重：与题库已有题目比对，避免重复
"""
import json
import re
import time
import random
import ollama
from ..config import OLLAMA_MODEL, OLLAMA_EMBED_MODEL
from ..database import get_db
from . import prompts


SIMILARITY_THRESHOLD = 0.92
# 需要Judge校验的题型（单选题结构简单，跳过以节省时间）
JUDGE_TYPES = {"single_select", "multi_select", "short_answer"}


def _call_model(prompt: str, max_tokens: int = 800,
                retries: int = 2) -> dict | None:
    """调用模型并解析JSON，失败重试"""
    for attempt in range(retries):
        try:
            response = ollama.chat(
                model=OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                format="json",
                options={"temperature": 0.7, "num_predict": max_tokens}
            )
            content = response["message"]["content"]
            content = content.replace("```json", "").replace("```", "").strip()
            return json.loads(content)
        except json.JSONDecodeError:
            if attempt < retries - 1:
                time.sleep(1)
                continue
        except Exception:
            time.sleep(3)
            continue
    return None


def retrieve_context(document_id: int, kp_id: int) -> str:
    """检索该知识点对应的原文片段（已含章节上下文前缀）"""
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT chunk_text FROM knowledge_chunks
            WHERE document_id = %s AND knowledge_point_id = %s
            ORDER BY chunk_order LIMIT 3
        """, (document_id, kp_id))
        rows = cur.fetchall()
    if not rows:
        return ""
    return "\n\n".join(r[0] for r in rows)[:2000]


def is_duplicate(embedding_str: str, document_id: int) -> bool:
    """向量查重（接收已算好的向量，避免重复计算）"""
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT COUNT(*) FROM questions
            WHERE document_id = %s AND embedding IS NOT NULL
        """, (document_id,))
        if cur.fetchone()[0] == 0:
            return False

        cur.execute("""
            SELECT 1 - (embedding <=> %s::vector) AS similarity
            FROM questions
            WHERE document_id = %s AND embedding IS NOT NULL
            ORDER BY similarity DESC LIMIT 1
        """, (embedding_str, document_id))
        row = cur.fetchone()
        return row and row[0] >= SIMILARITY_THRESHOLD

    with get_db() as (conn, cur):
        cur.execute("""
            SELECT 1 - (embedding <=> %s::vector) AS similarity
            FROM questions
            WHERE document_id = %s AND embedding IS NOT NULL
            ORDER BY similarity DESC LIMIT 1
        """, (str(embedding), document_id))
        row = cur.fetchone()
        return row and row[0] >= SIMILARITY_THRESHOLD


def judge_question(content: dict, context: str) -> tuple[str, str]:
    """
    LLM-as-a-Judge质检
    返回 (status, reason)
    status: "passed" / "rejected" / "judge_failed"
    """
    question_json = json.dumps(content, ensure_ascii=False)
    prompt = prompts.build_judge_prompt(question_json, context)
    result = _call_model(prompt, max_tokens=300)

    if not result:
        return "judge_failed", "Judge引擎响应失败，需人工复核"

    if result.get("status") == "rejected":
        return "rejected", result.get("reason", "未说明原因")
    return "passed", ""


def generate_one_question(document_id: int, kp_id: int, kp_name: str,
                          chunk_id: int, question_type: str,
                          dimension: str) -> dict:
    """
    生成一道题的完整流程：
    CoT分析 → 生成 → 查重 → Judge质检 → 入库
    返回 {"status": "saved"/"duplicate"/"rejected"/"failed", ...}
    """
    context = retrieve_context(document_id, kp_id)
    if not context:
        return {"status": "failed", "reason": "无原文"}

    dimension_desc = prompts.DIMENSIONS[dimension]

    # ===== CoT第一步：分析 =====
    thought_prompt = prompts.build_thought_prompt(
        kp_name, dimension, dimension_desc, context, question_type)
    thought_result = _call_model(thought_prompt, max_tokens=500)
    thought = json.dumps(thought_result, ensure_ascii=False) \
        if thought_result else "（无分析）"

    # ===== CoT第二步：生成 =====
    if question_type == "single_select":
        gen_prompt = prompts.build_single_select_prompt(
            kp_name, context, thought)
        difficulty = 2
    elif question_type == "multi_select":
        gen_prompt = prompts.build_multi_select_prompt(
            kp_name, context, thought)
        difficulty = 3
    else:
        gen_prompt = prompts.build_short_answer_prompt(
            kp_name, context, thought)
        difficulty = 4

    content = _call_model(gen_prompt, max_tokens=900)
    if not content or "question" not in content:
        return {"status": "failed", "reason": "生成失败"}

    question_text = content["question"]

    # ===== 提前算向量（全流程只算一次） =====
    try:
        embedding = ollama.embeddings(
            model=OLLAMA_EMBED_MODEL,
            prompt=question_text[:500]
        )["embedding"]
        embedding_str = str(embedding)
    except Exception:
        embedding_str = None

    # ===== 查重（传入算好的向量） =====
    if embedding_str and is_duplicate(embedding_str, document_id):
        return {"status": "duplicate"}

    # ===== Judge质检（仅多选和简答） =====
    db_status = "draft"
    if question_type in JUDGE_TYPES:
        judge_status, reason = judge_question(content, context)
        if judge_status == "rejected":
            return {"status": "rejected", "reason": reason}
        elif judge_status == "judge_failed":
            db_status = "needs_review"  # 入库但隔离，等人工复核

    # ===== 入库（直接用之前算好的向量） =====
    with get_db() as (conn, cur):
        cur.execute("""
            INSERT INTO questions
                (document_id, knowledge_point_id, source_chunk_id,
                 question_type, difficulty, content, embedding,
                 status, generated_by_model, dimension)
            VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s)
            RETURNING id
        """, (document_id, kp_id, chunk_id, question_type, difficulty,
              json.dumps(content, ensure_ascii=False),
              embedding_str, db_status, OLLAMA_MODEL, dimension))
        question_id = cur.fetchone()[0]

    return {"status": "saved", "question_id": question_id,
            "db_status": db_status}

def generate_for_knowledge_point(document_id: int, kp_id: int,
                                 kp_name: str, chunk_id: int,
                                 counts: dict) -> dict:
    """
    为一个知识点批量出题
    counts: {"single_select": 2, "multi_select": 1, "short_answer": 0}
    数量为0的题型跳过
    """
    stats = {"saved": 0, "duplicate": 0, "rejected": 0, "failed": 0}
    dimensions = list(prompts.DIMENSIONS.keys())

    for q_type, target in counts.items():
        if target <= 0:
            continue
        random.shuffle(dimensions)
        used = 0
        for dim in dimensions:
            if used >= target:
                break
            result = generate_one_question(
                document_id, kp_id, kp_name, chunk_id, q_type, dim)
            stats[result["status"]] += 1
            if result["status"] == "saved":
                used += 1
            time.sleep(1)

    return stats