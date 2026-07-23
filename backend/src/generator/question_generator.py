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
import difflib
import ollama
# 带超时的客户端：Ollama服务挂死时（实测发生过：连接建立但0%CPU永不响应），
# 无超时的调用会让出题线程无限期阻塞且无任何报错。300s足够容纳最慢的正常
# 调用；超时后抛异常走已有的重试逻辑，实现自愈。
_ollama_client = ollama.Client(timeout=300)
from ..config import OLLAMA_MODEL, OLLAMA_EMBED_MODEL
from ..database import get_db
from . import prompts


# 实测校准：确认的真实重复题（同答案同内容改写）相似度0.9048，
# 而同知识点但内容确实不同的题对相似度在0.62-0.78区间，两者有明显间隔。
# 原0.92太高，刚好放过了0.9048这条——收紧到0.88，在0.78和0.9048中间留足
# 余量，避免同时把"同知识点但真的不同"的题也误判成重复。
SIMILARITY_THRESHOLD = 0.88
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


# 简答题里出现这些字样说明被出成了选择题（无选项可选，题目必坏）。
# "哪些"单独出现是合法简答句式（"...的应用场景有哪些"属于开放式列举），
# 只有跟"正确"搭配（"哪些...是正确的"）才是要求从候选项里挑正误的选择题式提问，
# 必须限定在附近距离内，避免误伤正常的开放式简答题干。
_CHOICE_PHRASES = re.compile(
    r'下列|以下哪|哪一项|哪个选项|选项[A-D1-4一二三四]|'
    r'哪些.{0,15}正确|请选出|所有适用项'
)

# 解析中直接断言"X是答案"的模式（任何题干下都指答案本身）
_ASSERT_ANSWER = [
    re.compile(r'(?:选项\s*)?([A-D])\s*(?:是|为)\s*正确答案'),
    re.compile(r'正确答案\s*(?:是|为|应为|应该是)\s*([A-D])(?![A-Za-z])'),
    re.compile(r'(?:因此|所以)\s*(?:答案\s*)?(?:应?选|是|为)\s*([A-D])(?![A-Za-z])'),
]
# "选项X正确"式断言：仅在正向题干下等同于"X是答案"
# （"哪一项不正确"类反例题中，"选项B正确"指B陈述属实，不指B是答案）
_ASSERT_OPTION_OK = re.compile(
    r'选项\s*([A-D])(?:\s*[和、与]\s*(?:选项\s*)?([A-D]))?'
    r'(?:\s*[和、与]\s*(?:选项\s*)?([A-D]))?\s*(?:是|均|都)?正确')
_NEG_STEM = re.compile(r'不正确|不属于|不符合|不恰当|不成立|错误的|不是')

# 干扰项用"仅/完全/所有类型/单一的"这类绝对化措辞——不用看懂内容，
# 凭语感套路（"带绝对词的选项一般是错的"）就能秒排，是无效干扰项。
# prompt里明令禁止过，但实测模型完全没当回事（复测中5/7问题题都是这个），
# 纯正则零延迟兜底，比继续在prompt里加反例可靠。
_ABSOLUTE_WORDING = re.compile(
    r'仅(?:仅)?(?:通过|依赖|关注|限于|能|靠)|'
    r'只(?:能|通过|依赖|靠)|'
    r'完全(?:不|无|依赖|消除|遗忘|一致|忽略|替代)|'
    r'所有(?:类型|任务|场景)|(?:任何|所有).{0,4}都|'
    r'单一的|唯一的|无需(?:人工|任何)'
)

# 选项文本混入正误标注（"- 正确"/"（错误）"...）或"选项N:"式前缀标签——
# prompt已明令禁止但judge是概率性的会漏判，这里用规则兜底强制拦截
_OPTION_POLLUTED = re.compile(
    r'[-－—]\s*(?:正确|错误)(?:[，,].{0,20})?$|'  # 结尾" - 正确"/" - 错误，理由"
    r'[（(]\s*(?:正确|错误)\s*[）)]|'             # （正确）/（错误）
    r'^\s*选项\s*[A-D0-9一二三四]\s*[:：]'          # 开头"选项3："这类前缀
)


def _explanation_contradicts(content: dict) -> bool:
    """
    答案-解析一致性校验：模型偶发"答案标A、解析论证D"的自相矛盾。
    从解析中提取被断言为答案的选项字母，与答案字段比对。
    只在能明确提取到断言时才判定，提取不到不拦截。
    """
    expl = content.get("explanation", "")
    if not expl:
        return False
    asserted = set()
    for pat in _ASSERT_ANSWER:
        for m in pat.finditer(expl):
            asserted.update(g for g in m.groups() if g)
    if not _NEG_STEM.search(content.get("question", "")):
        for m in _ASSERT_OPTION_OK.finditer(expl):
            asserted.update(g for g in m.groups() if g)
    if not asserted:
        return False
    answer = content.get("answer")
    answer_set = set(answer) if isinstance(answer, list) else {answer}
    # 解析断言了答案之外的字母 → 矛盾
    return not asserted.issubset(answer_set)


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

    # 任一选项为空/纯空白 → 模型漏写，结构性坏题，直接废弃重出
    if any(not str(v).strip() for v in options.values()):
        return None

    # 选项文本自带正误标注或"选项N:"前缀 → 结构性坏题，直接废弃重出
    if any(_OPTION_POLLUTED.search(str(v)) for v in options.values()):
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

    # 孪生选项检测：两个选项文本高度雷同（实测坏例：仅"向量相似度"换成
    # "余弦相似度"、其余逐字相同，且双双是正确答案）= 机械凑数。
    # 两档规则（阈值用真实题目校准过：合法的同结构对位选项最高0.759）：
    #   1) 相似度>=0.80 且两个都在答案里 → 纯凑数，拦
    #   2) 相似度>=0.92 → 近乎逐字复制，无论是否答案都拦
    answer_set = set(answer_letters)
    letters = list(options.keys())
    for i in range(len(letters)):
        for j in range(i + 1, len(letters)):
            a, b = letters[i], letters[j]
            sim = difflib.SequenceMatcher(
                None, str(options[a]), str(options[b])).ratio()
            if sim >= 0.92 or (sim >= 0.80 and
                               {a, b} <= answer_set):
                return None

    # 答案字段与解析断言矛盾（模型偶发标错answer）→ 废题重出
    if _explanation_contradicts(content):
        return None

    # 干扰项用"仅/完全/所有类型/单一的"这类绝对化措辞 → 不用看内容，
    # 凭语感就能排除，是一眼假的伪干扰项，废题重出（只查干扰项，不查
    # 正确答案本身——正确答案哪怕表述听起来"绝对"也可能是教材原话）
    distractors = {k: v for k, v in options.items() if k not in answer_letters}
    if any(_ABSOLUTE_WORDING.search(str(v)) for v in distractors.values()):
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
            response = _ollama_client.chat(
                model=OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                format="json",
                think=False,  # qwen3思考模式一次调用40s+，必须关；旧模型会忽略此参数
                keep_alive="2h",  # 防止空闲5分钟后模型被卸载，下次调用免去冷加载
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
    """
    检索该知识点对应的原文片段（已含章节上下文前缀）。
    知识点切片多于3个时，随机取一个连续窗口（而非永远固定最前3个）——
    否则同一知识点反复出题时，每次看到的原文都完全相同，模型只能靠换
    "维度"和随机性制造差异，容易撞出高度相似的题、拉高查重重试率。
    随机窗口仍取"连续"的3个，保留局部语义连贯，不打乱顺序。
    """
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT chunk_text FROM knowledge_chunks
            WHERE document_id = %s AND knowledge_point_id = %s
            ORDER BY chunk_order
        """, (document_id, kp_id))
        all_chunks = [r[0] for r in cur.fetchall()]
    if not all_chunks:
        return ""
    if len(all_chunks) <= 3:
        window = all_chunks
    else:
        start = random.randint(0, len(all_chunks) - 3)
        window = all_chunks[start:start + 3]
    return "\n\n".join(window)[:2000]


def is_duplicate(embedding_str: str, document_id: int) -> bool:
    """
    向量查重（接收已算好的向量，避免重复计算）。
    只跟"仍在使用"的题比对——已废弃(retired)/已拒绝(rejected)的题
    不再代表题库现状，不该继续挡住同一知识点的新题生成。
    """
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT 1 - (embedding <=> %s::vector) AS similarity
            FROM questions
            WHERE document_id = %s AND embedding IS NOT NULL
              AND status NOT IN ('retired', 'rejected')
            ORDER BY similarity DESC LIMIT 1
        """, (embedding_str, document_id))
        row = cur.fetchone()
        return row and row[0] >= SIMILARITY_THRESHOLD


# 题干里问"局限性/优势"这类词时，若这个具体的词逐字出现在正确答案选项
# 里、干扰项完全不含——纯靠字面回声就能秒选，不需要看懂选项内容
_ASK_KEYWORD = re.compile(r'局限性?|缺陷|不足之处|弊端|优势|优点|好处|益处')


def _keyword_echo_instakill(content: dict) -> str | None:
    """
    程序化秒杀检验（关键词版，不需要模型调用）：题干问"...的局限性是什么"
    这类问题时，若"局限"这个词逐字只出现在正确答案选项文本里、干扰项一个
    都不含，考生凭字面回声就能秒选。只认题干里出现过的那个具体词是否
    原样重现，不用宽泛的情感词库匹配（避免"提升/提高/改善"这类同义词
    的自然分布差异被误判成秒杀）。纯正则，零延迟。
    """
    options = content.get("options")
    if not options:
        return None
    question = content.get("question", "")
    answer = content.get("answer")
    answer_set = set(answer) if isinstance(answer, list) else {answer}

    m = _ASK_KEYWORD.search(question)
    if not m:
        return None
    keyword = m.group(0).rstrip("性")  # "局限性" -> "局限"

    hits = {k for k, v in options.items() if keyword in str(v)}
    non_answer = set(options.keys()) - answer_set
    if hits and hits == answer_set and not (hits & non_answer):
        return (f"秒杀题：题干中的'{keyword}'一词逐字只出现在正确答案"
                f"选项里，其余选项完全不含，凭字面回声即可秒选")
    return None


def _verdict_mismatch(content: dict, judge_result: dict) -> str | None:
    """
    答案-解析一致性核验：不再单独调模型，直接复用主judge调用里顺带
    输出的option_verdicts（同一次调用，不额外增加耗时）。
    只做客观事实核对：解析自己认定的true集合是否等于answer字段
    （如"解析说B属于该场景，但answer把B当成不属于的正确答案"，纯粹的
    数据/逻辑错误）。
    """
    options = content.get("options")
    if not options:
        return None
    verdict = judge_result.get("option_verdicts")
    if not isinstance(verdict, dict) or set(verdict.keys()) != set(options.keys()):
        return None  # 标注缺失/不完整不拦截

    answer = content.get("answer")
    answer_set = set(answer) if isinstance(answer, list) else {answer}
    true_set = {k for k, v in verdict.items() if v == "true"}

    if true_set and true_set != answer_set:
        return (f"答案与解析矛盾：解析认定{sorted(true_set)}为真，"
                f"但标注答案是{sorted(answer_set)}")
    return None


def judge_question(content: dict, context: str) -> tuple[str, str]:
    """
    质检：LLM-as-a-Judge审内容质量（含选项转述核对、自洽性、option_verdicts）
    + 关键词回声秒杀检验（免费，纯正则）
    + 答案-解析一致性核验（复用judge同一次调用的输出，不加调用）

    注：原本还有一次独立的"极性标注"模型调用做秒杀检验，但复盘发现它
    从未真正抓住过一个真实坏题——它的原始目标案例(#558)自己都没测中
    （把中性陈述误判成正面），真正拦住那道题的是后来加的关键词回声检验。
    继续保留这次调用只是白花时间，已去掉。
    返回 (status, reason)
    status: "passed" / "rejected" / "judge_failed"
    """
    question_json = json.dumps(content, ensure_ascii=False)
    prompt = prompts.build_judge_prompt(question_json, context)
    result = _call_model(prompt, max_tokens=450, temperature=0.1)

    if not result:
        return "judge_failed", "Judge引擎响应失败，需人工复核"

    if result.get("status") == "rejected":
        return "rejected", result.get("reason", "未说明原因")

    reason = _verdict_mismatch(content, result)
    if reason:
        return "rejected", reason

    reason = _keyword_echo_instakill(content)
    if reason:
        return "rejected", reason
    return "passed", ""


# 难度档位：1易/2中/3难，生成时注入prompt并标注入库。
# 注意：难度是prompt引导+模型自标注，8B模型遵从度有限，标注仅供参考，
# 审核时可人工修正
DIFFICULTY_GUIDE = {
    1: "难度要求：基础题——直接考查教材中明确陈述的概念定义或事实，干扰项差异明显",
    2: "难度要求：中等题——考查概念间的关系或机制原理，干扰项需要仔细辨析",
    3: "难度要求：较难题——需要综合理解或辨析易混淆概念，干扰项高度贴近正确答案",
}


def generate_one_question(document_id: int, kp_id: int, kp_name: str,
                          chunk_id: int, question_type: str,
                          dimension: str, difficulty: int = 2) -> dict:
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
    elif question_type == "multi_select":
        gen_prompt = prompts.build_multi_select_prompt(
            kp_name, context, thought)
    else:
        gen_prompt = prompts.build_short_answer_prompt(
            kp_name, context, thought)

    difficulty = difficulty if difficulty in DIFFICULTY_GUIDE else 2
    gen_prompt += "\n" + DIFFICULTY_GUIDE[difficulty]

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
        embedding = _ollama_client.embeddings(
            model=OLLAMA_EMBED_MODEL,
            prompt=question_text[:500],
            keep_alive="2h",
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