"""
PDF导出模块
生成题目版（学生用）和答案版（教师用）两份PDF
$...$ 包裹的LaTeX公式经matplotlib mathtext渲染成SVG内嵌图片
"""
import os
import re
import io
import json
import base64
import html as html_lib

import matplotlib
matplotlib.use("Agg")
from matplotlib import mathtext
from matplotlib.font_manager import FontProperties

from weasyprint import HTML, CSS
from ..database import get_db

# mathtext不支持的命令替换成等价写法
_MATHTEXT_SUBS = [
    (re.compile(r'\\text\s*\{'), r'\\mathrm{'),
    (re.compile(r'\\thinspace'), r'\\,'),
    (re.compile(r'\\ldots'), r'\\dots'),
]


def _render_formula(tex: str) -> str:
    """单个LaTeX公式 -> 内嵌SVG的<img>标签；渲染失败回退为转义原文"""
    cleaned = tex.strip()
    for pat, rep in _MATHTEXT_SUBS:
        cleaned = pat.sub(rep, cleaned)
    try:
        buf = io.BytesIO()
        mathtext.math_to_image(
            f"${cleaned}$", buf, format="svg",
            prop=FontProperties(size=11)
        )
        b64 = base64.b64encode(buf.getvalue()).decode()
        return (f'<img class="math" alt="{html_lib.escape(tex)}" '
                f'src="data:image/svg+xml;base64,{b64}"/>')
    except Exception:
        return html_lib.escape(f"${tex}$")


def htmlize(text) -> str:
    """
    题目文本 -> 安全HTML：普通文字转义，$...$公式渲染成数学式。
    所有插入HTML模板的动态文本都必须经过这里。
    """
    text = str(text or "")
    parts = re.split(r'(\$[^$]+\$)', text)
    out = []
    for part in parts:
        if len(part) > 2 and part.startswith("$") and part.endswith("$"):
            out.append(_render_formula(part[1:-1]))
        else:
            out.append(html_lib.escape(part))
    return "".join(out)

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "outputs"
)
os.makedirs(OUTPUT_DIR, exist_ok=True)

TYPE_NAMES = {
    "single_select": "单选题",
    "multi_select": "多选题",
    "short_answer": "简答题",
}
TYPE_INSTRUCTIONS = {
    "single_select": "每题只有一个正确答案，请将答案字母填入括号内。",
    "multi_select": "每题有两个或两个以上正确答案，请将所有答案字母填入括号内。",
    "short_answer": "请根据所学内容作答。",
}

BASE_CSS = """
@page { size: A4; margin: 20mm 25mm; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: "SimSun", "STSong", "Songti SC", serif;
  font-size: 11pt; color: #000; line-height: 1.7; width: 100%;
}
.header {
  text-align: center; border-bottom: 2px solid #000;
  padding-bottom: 10px; margin-bottom: 18px;
}
.exam-title { font-size: 17pt; font-weight: bold; margin-bottom: 5px; }
.exam-meta { font-size: 10pt; color: #444; margin-bottom: 6px; }
.exam-info {
  display: flex; justify-content: space-between;
  font-size: 10.5pt; margin-top: 8px;
}
.watermark { color: #cc0000; font-size: 12pt; font-weight: bold; margin-top: 5px; }
.section { margin-bottom: 20px; }
.section-title {
  font-size: 12pt; font-weight: bold; margin-bottom: 3px;
  border-left: 4px solid #000; padding-left: 7px;
}
.section-instruction {
  font-size: 9.5pt; color: #555; margin-bottom: 10px;
  margin-left: 11px; font-style: italic;
}
.question { margin-bottom: 14px; }
.question-stem { line-height: 1.75; margin-bottom: 5px; }
.score-tag { color: #555; font-size: 9.5pt; }
.blank { letter-spacing: 3px; }
.options { padding-left: 18px; }
.option { line-height: 1.75; }
.answer-line {
  border-bottom: 1px solid #aaa; margin: 7px 0; height: 18px;
}
.answer-box {
  background: #f7f7f7; border-left: 3px solid #cc0000;
  padding: 7px 11px; margin-top: 7px;
}
.answer-label { font-weight: bold; color: #cc0000; }
.answer-value { font-weight: bold; font-size: 12pt; }
.explanation {
  margin-top: 5px; padding: 5px 11px;
  color: #333; font-size: 10.5pt; line-height: 1.65;
}
.key-points ul { padding-left: 18px; margin: 4px 0; }
img.math { height: 1.15em; vertical-align: -0.25em; }
.footer {
  text-align: center; font-size: 9.5pt; color: #888;
  margin-top: 16px; border-top: 1px solid #ccc; padding-top: 7px;
}
"""


def load_paper(paper_id: int) -> dict:
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT ep.title, ep.created_at, d.subject
            FROM exam_papers ep
            JOIN documents d ON ep.document_id = d.id
            WHERE ep.id = %s
        """, (paper_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"试卷不存在: {paper_id}")
        title, created_at, subject = row

        cur.execute("""
            SELECT epq.question_order, epq.score, q.question_type,
                   q.content, kp.name
            FROM exam_paper_questions epq
            JOIN questions q ON epq.question_id = q.id
            JOIN knowledge_points kp ON q.knowledge_point_id = kp.id
            WHERE epq.paper_id = %s
            ORDER BY epq.question_order
        """, (paper_id,))
        questions = []
        for r in cur.fetchall():
            content = r[3]
            if isinstance(content, str):
                content = json.loads(content)
            questions.append({
                "order": r[0], "score": float(r[1]),
                "type": r[2], "content": content, "kp_name": r[4],
            })

    return {
        "paper_id": paper_id, "title": title,
        "subject": subject or "考试",
        "created": created_at.strftime("%Y年%m月%d日") if created_at else "",
        "questions": questions,
        "total_score": sum(q["score"] for q in questions),
    }


def build_exam_html(paper: dict) -> str:
    """题目版HTML"""
    groups = {}
    for q in paper["questions"]:
        groups.setdefault(q["type"], []).append(q)

    sections = ""
    num = 1
    for t in ["single_select", "multi_select", "short_answer"]:
        if t not in groups:
            continue
        qs = groups[t]
        type_score = sum(q["score"] for q in qs)

        items = ""
        for q in qs:
            c = q["content"]
            if t in ("single_select", "multi_select"):
                opts = "".join(
                    f'<div class="option">{k}. {htmlize(v)}</div>'
                    for k, v in c.get("options", {}).items()
                )
                items += f"""
<div class="question">
  <div class="question-stem">{q["order"]}. {htmlize(c.get("question",""))}
    <span class="score-tag">（{q["score"]:g}分）</span>
    <span class="blank">（　　）</span>
  </div>
  <div class="options">{opts}</div>
</div>"""
            else:
                lines = "".join(
                    '<div class="answer-line"></div>'
                    for _ in range(max(4, int(q["score"] / 2)))
                )
                items += f"""
<div class="question">
  <div class="question-stem">{q["order"]}. {htmlize(c.get("question",""))}
    <span class="score-tag">（{q["score"]:g}分）</span>
  </div>
  <div>{lines}</div>
</div>"""

        sections += f"""
<div class="section">
  <div class="section-title">{num}、{TYPE_NAMES[t]}（共{len(qs)}题，共{type_score:g}分）</div>
  <div class="section-instruction">{TYPE_INSTRUCTIONS[t]}</div>
  {items}
</div>"""
        num += 1

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head><body>
<div class="header">
  <div class="exam-title">{paper["subject"]} 考试试卷</div>
  <div class="exam-meta">{paper["title"]}</div>
  <div class="exam-info">
    <span>日期：{paper["created"]}</span>
    <span>满分：{paper["total_score"]:g}分</span>
    <span>考试时间：90分钟</span>
  </div>
  <div class="exam-info" style="margin-top:7px;">
    <span>姓名：_______________</span>
    <span>学号：_______________</span>
    <span>得分：_______________</span>
  </div>
</div>
{sections}
<div class="footer">— 试卷结束 —</div>
</body></html>"""


def build_answer_html(paper: dict) -> str:
    """答案版HTML"""
    items = ""
    for q in paper["questions"]:
        c = q["content"]
        if q["type"] in ("single_select", "multi_select"):
            opts = "".join(
                f'<div class="option">{k}. {htmlize(v)}</div>'
                for k, v in c.get("options", {}).items()
            )
            ans = c.get("answer", "")
            if isinstance(ans, list):
                ans = "、".join(ans)
            items += f"""
<div class="question">
  <div class="question-stem">{q["order"]}. [{TYPE_NAMES[q["type"]]}·{q["score"]:g}分] [{htmlize(q["kp_name"])}] {htmlize(c.get("question",""))}</div>
  <div class="options">{opts}</div>
  <div class="answer-box">
    <span class="answer-label">正确答案：</span>
    <span class="answer-value">{html_lib.escape(str(ans))}</span>
  </div>
  <div class="explanation"><span class="answer-label">解析：</span>{htmlize(c.get("explanation",""))}</div>
</div>"""
        else:
            pts = "".join(f"<li>{htmlize(p)}</li>"
                          for p in c.get("key_points", []))
            items += f"""
<div class="question">
  <div class="question-stem">{q["order"]}. [{TYPE_NAMES[q["type"]]}·{q["score"]:g}分] [{htmlize(q["kp_name"])}] {htmlize(c.get("question",""))}</div>
  <div class="answer-box">
    <span class="answer-label">参考答案：</span>
    <p style="margin-top:5px;">{htmlize(c.get("model_answer",""))}</p>
    <div class="key-points"><strong>评分要点：</strong><ul>{pts}</ul></div>
  </div>
</div>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head><body>
<div class="header">
  <div class="exam-title">{paper["subject"]} 考试试卷</div>
  <div class="exam-meta">{paper["title"]}　{paper["created"]}</div>
  <div class="watermark">【教师版·含答案·请勿外传】</div>
</div>
{items}
</body></html>"""


def export_pdfs(paper_id: int) -> dict:
    """生成两份PDF，返回文件路径"""
    paper = load_paper(paper_id)
    css = CSS(string=BASE_CSS)

    exam_path = os.path.join(OUTPUT_DIR, f"paper_{paper_id}_exam.pdf")
    answer_path = os.path.join(OUTPUT_DIR, f"paper_{paper_id}_answer.pdf")

    HTML(string=build_exam_html(paper)).write_pdf(exam_path, stylesheets=[css])
    HTML(string=build_answer_html(paper)).write_pdf(answer_path, stylesheets=[css])

    with get_db() as (conn, cur):
        cur.execute("UPDATE exam_papers SET pdf_path=%s WHERE id=%s",
                    (exam_path, paper_id))

    return {"exam_pdf": exam_path, "answer_pdf": answer_path}