"""
出题Prompt模板集中管理
所有针对模型的指令都在这里，方便调整和维护
"""

# ============================================================
# 出题维度定义（实现"无限出题"的核心）
# 同一知识点从不同维度出题，保证题目不重复
# ============================================================
DIMENSIONS = {
    "definition":  "定义理解类：考查对核心概念定义的准确理解",
    "comparison":  "对比辨析类：考查与相近概念的区别和联系",
    "application": "应用场景类：考查在实际场景中的运用判断",
    "counter":     "反例排除类：从反面考查，找出不属于/不正确的选项",
    "principle":   "原理机制类：考查内部原理、工作机制、技术细节",
    "pros_cons":   "优缺点类：考查方法的优势、局限性、适用边界",
}

# 通用约束（所有题型共用）
COMMON_RULES = """
出题规则（必须严格遵守）：
1. 题干必须自包含：严禁"该项目"、"上述方法"等指代词，必须写出具体名称
2. 严禁在题干中出现"根据教材"、"根据原文"等字样
3. 严禁组合型选项（如"1和3"、"以上都是"），每个选项必须是独立完整的陈述
4. 干扰项构造要求（关键质量项）：
   - 每个干扰项必须与题干的提问直接对位，是对同一问题的不同回答
   - 极性一致（最重要）：题干问"问题/缺陷/局限"，四个选项必须全部是负面表述
     （三个干扰项是"听起来像但实际不成立的问题"）；题干问"优势/作用/特点"，
     四个选项必须全部是同类正面表述。严禁把优点混进"找问题"的选项里，
     否则学生只看语气就能排除，题目作废
   - 秒杀自检：出完题后自问——一个没学过教材的人能否仅凭选项语气、长度、
     常识就锁定答案？能则必须重写干扰项
   - 干扰项应通过以下方式构造：细节篡改（数字/名称/版本改错）、
     张冠李戴（把其他相关概念的特性安到本概念上）、因果错位（事实正确但与题干问的机制无关）
   - 严禁使用"仅能"、"完全不"、"未采用任何"等极端否定表述作为干扰项
   - 严禁干扰项的信息量和具体程度明显低于正确答案（长度和细节感应大致相当）
5. 所有内容必须基于教材原文，不得编造
6. 选项文本必须是纯粹的客观陈述，严禁以下内容混入选项：
   - 正误标注：如"（正确）"、"（错误）"
   - 自我评价：如"非常适合"、"最符合题意"、"题干中未提到"
   - 判断理由：选项只陈述事实，为什么对/错只能写在explanation里
   - 前缀标签："选项A："这类文字（选项内容直接开始，不要带编号）
7. 题干应是简洁的疑问句，不复述教材原文段落，不含"本题考查"等元话语
8. 数学公式一律使用LaTeX格式，行内公式用$...$包裹，
   例如 $P(w_t | w_1, \\ldots, w_{t-1})$，禁止用纯文本堆砌公式
9. 解析中严禁引用选项字母（如"选项B错误"），必须直接陈述选项内容本身的对错及原因
10. 四个选项的长度和细节程度应大致相当，正确答案不得明显比干扰项更长更详细
"""


def build_thought_prompt(kp_name: str, dimension: str,
                         dimension_desc: str, context: str,
                         question_type: str) -> str:
    """CoT第一步：让模型先分析怎么出题"""
    type_names = {
        "single_select": "单选题",
        "multi_select": "多选题",
        "short_answer": "简答题"
    }
    return f"""你是出题专家。请分析如何为以下知识点出一道{type_names[question_type]}。

知识点：{kp_name}
出题维度：{dimension_desc}

教材原文：
{context}

请分析：
1. 这段原文中，适合从"{dimension_desc}"角度考查的核心内容是什么
2. 题干应该怎么问（注意：题干必须自包含，写出具体名称，不用指代词）
3. 如果是选择题：构思4个选项，并检查它们之间是否相互独立、没有包含关系

只输出JSON：
{{"core_content": "要考查的核心内容", "question_idea": "题干思路", "options_check": "选项独立性分析（选择题）或答案要点（简答题）"}}"""


def build_single_select_prompt(kp_name: str, context: str,
                                thought: str = None,
                                dimension_desc: str = None) -> str:
    """
    生成单选题。
    thought为None时走单步模式（跳过CoT提速），此时用dimension_desc直接注入出题维度
    """
    if thought:
        guidance = f"你之前的出题分析：\n{thought}"
    else:
        guidance = f"出题维度：{dimension_desc}" if dimension_desc else ""

    return f"""你是出题专家。请为以下知识点生成一道单选题。

知识点：{kp_name}
{guidance}

教材原文：
{context}

{COMMON_RULES}

只输出JSON：
{{"question": "题干", "options": {{"A": "", "B": "", "C": "", "D": ""}}, "answer": "A", "explanation": "解析"}}"""


def build_multi_select_prompt(kp_name: str, context: str,
                               thought: str) -> str:
    return f"""你是出题专家。基于以下分析，生成最终的多选题。

知识点：{kp_name}

教材原文：
{context}

你之前的出题分析：
{thought}

{COMMON_RULES}
额外要求：正确答案为2-3个选项。

只输出JSON：
{{"question": "题干", "options": {{"A": "", "B": "", "C": "", "D": ""}}, "answer": ["A", "C"], "explanation": "解析"}}"""


def build_short_answer_prompt(kp_name: str, context: str,
                               thought: str) -> str:
    return f"""你是出题专家。基于以下分析，生成最终的简答题。

知识点：{kp_name}

教材原文：
{context}

你之前的出题分析：
{thought}

{COMMON_RULES}
额外要求：问题要有思考价值，参考答案覆盖3-5个关键要点。

只输出JSON：
{{"question": "题干", "model_answer": "完整参考答案", "key_points": ["要点1", "要点2", "要点3"]}}"""


def build_judge_prompt(question_json: str, context: str) -> str:
    """LLM-as-a-Judge：校验题目质量"""
    return f"""你是严苛的试题审核专家。请审核以下题目是否合格。

教材原文（题目依据）：
{context}

待审核题目：
{question_json}

审核标准（任何一条不满足即为rejected）：
1. 题干必须是一个真正的问题（疑问句或明确的指令），不能是陈述句
2. 题干不得与任何一个选项内容相同或高度相似（题干抄答案是严重缺陷）
3. 单选题必须有且只有一个可辩护的正确答案，其他选项必须明确错误；如果有两个以上选项都说得通，即为缺陷题
4. 解析的逻辑必须自洽：解析必须支持标注的正确答案，不能出现"选项X也正确但不选"这类自相矛盾的表述
5. 选项之间相互独立，无包含或从属关系
6. 内容忠实于教材原文，不编造
7. 选项文本中不得出现正误标注、自我评价（"最适合"、"未提到"类）、判断理由或"选项X："前缀
8. 含数学公式的内容必须使用LaTeX格式（$...$包裹）
9. 干扰项质量：干扰项不得使用极端否定表述（"仅""任何""完全"），不得明显比正确答案空泛，必须与题干提问对位

只输出JSON：
{{"status": "passed" 或 "rejected", "reason": "如果rejected，说明具体原因"}}"""


def build_polarity_prompt(question: str, options: dict) -> str:
    """
    独立的极性标注任务（供程序化秒杀检验用）。
    只做分类不做评判，小模型聚焦单一任务才稳定。
    """
    opts_text = "\n".join(f"{k}. {v}" for k, v in options.items())
    return f"""对一道选择题做极性标注，只做分类，不评价题目好坏。

判定规则——只看句子主干对主语的断言方向：
- 肯定其能力/作用（"能够…"、"可以…"、"提供…"、"通过…实现…"）= positive
- 否定其能力/指出问题（"无法…"、"难以…"、"缺乏…"、"存在…问题"）= negative
- 无褒贬的事实陈述 = neutral
- 陷阱示例："能够精准捕捉深层语义的偏差"——句中虽有"偏差"一词，
  但主干是"能够捕捉"（肯定能力）→ positive；
  "无法有效处理复杂创作型任务"——主干是"无法处理" → negative

题干（标注它问的方向，问缺点/问题/不正确项=negative，问优点/作用/正确项=positive）：
{question}

选项（逐个标注）：
{opts_text}

只输出JSON：
{{"stem_asks": "negative/positive/neutral",
  "options_polarity": {{"A": "...", "B": "...", "C": "...", "D": "..."}}}}"""