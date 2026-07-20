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
# 需要Judge校验的题型（当前全部题型都过Judge质检）
JUDGE_TYPES = {"single_select", "multi_select", "short_answer"}


def _protect_latex_escapes(raw: str) -> str:
    """
    模型在JSON字符串里写LaTeX单反斜杠命令（\\text、\\lambda、\\thinspace...），
    json.loads会把 \\t 解析成制表符、\\f 解析成换页符，公式被静默打碎。
    在解析前把"反斜杠+2个以上字母"的组合翻倍成 \\\\，让LaTeX命令活过JSON解析。
    \\uXXXX 这类合法unicode转义保持不动。
    """
    return re.sub(r'\\(?!u[0-9a-fA-F]{4})(?=[a-zA-Z]{2,})', r'\\\\', raw)


def _remap_letters(text: str, letter_map: dict) -> str:
    """
    洗牌后同步替换解析文本中引用的选项字母（模型经常无视"不引用字母"的指令）。
    只替换独立出现的A-D（前后不是英文字母），避免误伤API、BERT等词。
    """
    if not text:
        return text
    return re.sub(
        r'(?<![A-Za-z])([ABCD])(?![A-Za-z])',
        lambda m: letter_map.get(m.group(1), m.group(1)),
        text
    )


# 简答题里出现这些字样说明被出成了选择题（无选项可选，题目必坏）
_CHOICE_PHRASES = re.compile(r'下列|以下哪|哪一项|哪个选项|选项[A-D1-4一二三四]')


def _validate_and_shuffle(content: dict, question_type: str) -> dict | None:
    """
    选择题结构校验 + 选项洗牌。
    校验：4个选项齐全、答案格式合法（单选1个字母、多选2-3个字母）。
    洗牌：模型倾向把正确答案放A（实测55%），打乱选项消除位置偏差，
          并同步重映射解析中引用的选项字母。
    返回规整后的content，不合格返回None。
    """
    if question_type == "short_answer":
        if not content.get("model_answer") or not content.get("key_points"):
            return None
        # 简答题被出成"下列哪项"式选择题（没有选项可选）= 坏题
        if _CHOICE_PHRASES.search(content.get("question", "")) or \
           _CHOICE_PHRASES.search(content.get("model_answer", "")):
            return None
        return content

    options = content.get("options")
    if not isinstance(options, dict) or len(options) != 4 or \
       set(options.keys()) != {"A", "B", "C", "D"}:
        return None

    answer = content.get("answer")
    if question_type == "single_select":
        if not isinstance(answer, str):
            return None
        answer = answer.strip().upper()
        if answer not in options:
            return None
        answer_letters = [answer]
    else:  # multi_select
        if not isinstance(answer, list):
            return None
        answer_letters = [str(a).strip().upper() for a in answer]
        if not (2 <= len(answer_letters) <= 3) or \
           not all(a in options for a in answer_letters) or \
           len(set(answer_letters)) != len(answer_letters):
            return None

    # 洗牌：按打乱后的顺序重新分配字母
    items = list(options.items())  # [(旧字母, 文本)]
    random.shuffle(items)
    letter_map = {}  # 旧字母 -> 新字母
    new_options = {}
    for new_letter, (old_letter, text) in zip("ABCD", items):
        letter_map[old_letter] = new_letter
        new_options[new_letter] = text

    content["options"] = new_options
    if question_type == "single_select":
        content["answer"] = letter_map[answer_letters[0]]
    else:
        content["answer"] = sorted(letter_map[a] for a in answer_letters)
    if content.get("explanation"):
        content["explanation"] = _remap_letters(
            content["explanation"], letter_map)
    return content


def _call_model(prompt: str, max_tokens: int = 800,
                retries: int = 2, temperature: float = 0.7) -> dict | None:
    """调用模型并解析JSON，失败重试。出题用高温发散，质检/分类用低温求稳"""
    for attempt in range(retries):
        try:
            response = ollama.chat(
                model=OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                format="json",
                think=False,  # qwen3思考模式一次调用40s+，必须关；旧模型会忽略此参数
                options={"temperature": temperature, "num_predict": max_tokens}
            )
            content = response["message"]["content"]
            content = content.replace("```json", "").replace("```", "").strip()
            return json.loads(_protect_latex_escapes(content))
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


def _polarity_instakill(content: dict) -> str | None:
    """
    秒杀题程序化判定：题干问"问题/缺点"（或"优点"）时，若与题干方向
    同极性的选项恰好就是正确答案集合，则学生仅凭语气即可锁定答案。
    独立小调用做极性标注（分类模型擅长），本函数执行规则（逻辑代码可靠）。
    返回拒绝原因，通过（或标注失败）返回None。
    """
    options = content.get("options")
    if not options:
        return None
    prompt = prompts.build_polarity_prompt(
        content.get("question", ""), options)
    result = _call_model(prompt, max_tokens=120, temperature=0.0)
    if not result:
        return None  # 标注失败不拦截

    stem = result.get("stem_asks")
    pol = result.get("options_polarity")
    if stem not in ("negative", "positive") or not isinstance(pol, dict) or \
       set(pol.keys()) != set(options.keys()):
        return None

    matching = [k for k, v in pol.items() if v == stem]
    answer = content.get("answer")
    answer_set = set(answer) if isinstance(answer, list) else {answer}
    # 秒杀成立需要鲜明的语气反差：正确答案与题干同极性，
    # 且所有干扰项都是相反极性（neutral的平实陈述不构成秒杀线索）
    opposite = "positive" if stem == "negative" else "negative"
    non_answer = set(pol.keys()) - answer_set
    if set(matching) == answer_set and non_answer and \
       all(pol.get(k) == opposite for k in non_answer):
        direction = "负面" if stem == "negative" else "正面"
        return (f"秒杀题：题干问{direction}内容，但只有正确答案是{direction}"
                f"表述，其余选项极性相反，凭语气即可选出")
    return None


def judge_question(content: dict, context: str) -> tuple[str, str]:
    """
    两段式质检：LLM-as-a-Judge审内容质量 + 独立极性标注做程序化秒杀检验
    返回 (status, reason)
    status: "passed" / "rejected" / "judge_failed"
    """
    question_json = json.dumps(content, ensure_ascii=False)
    prompt = prompts.build_judge_prompt(question_json, context)
    result = _call_model(prompt, max_tokens=400, temperature=0.1)

    if not result:
        return "judge_failed", "Judge引擎响应失败，需人工复核"

    if result.get("status") == "rejected":
        return "rejected", result.get("reason", "未说明原因")

    instakill = _polarity_instakill(content)
    if instakill:
        return "rejected", instakill
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

    # ===== CoT分析（单选题结构简单，跳过CoT直接生成，省一次模型调用） =====
    if question_type == "single_select":
        thought = None
    else:
        thought_prompt = prompts.build_thought_prompt(
            kp_name, dimension, dimension_desc, context, question_type)
        thought_result = _call_model(thought_prompt, max_tokens=500)
        thought = json.dumps(thought_result, ensure_ascii=False) \
            if thought_result else "（无分析）"

    # ===== 生成 =====
    if question_type == "single_select":
        gen_prompt = prompts.build_single_select_prompt(
            kp_name, context, thought=None, dimension_desc=dimension_desc)
        difficulty = 2
    elif question_type == "multi_select":
        gen_prompt = prompts.build_multi_select_prompt(
            kp_name, context, thought)
        difficulty = 3
    else:
        gen_prompt = prompts.build_short_answer_prompt(
            kp_name, context, thought)
        difficulty = 4

    content = _call_model(gen_prompt, max_tokens=1200)
    if not content or "question" not in content:
        return {"status": "failed", "reason": "生成失败"}

    # 结构校验 + 选项洗牌（消除"正确答案总在A"的位置偏差）
    content = _validate_and_shuffle(content, question_type)
    if not content:
        return {"status": "failed", "reason": "题目结构不合格"}

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

    for q_type, target in counts.items():
        if target <= 0:
            continue
        dimensions = [d for d in prompts.DIMENSIONS
                      if not (q_type == "short_answer" and d == "counter")]
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

    return stats