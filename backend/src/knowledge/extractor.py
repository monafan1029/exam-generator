"""
知识点提取模块
- 用规则从文本中提取章节标题（可靠、不依赖AI）
- 用AI给章节生成英文名和编码（每章单独处理，避免JSON截断）
- 写入 documents 和 knowledge_points 表
"""
import re
import json
import ollama
from ..config import OLLAMA_MODEL
from ..database import get_db


def extract_titles_by_rule(text: str) -> list[dict]:
    """
    用正则规则解析章节结构，返回:
    [{"chapter": "第1章 xxx", "sections": ["1.1 xxx", ...]}, ...]
    """
    lines = text.split("\n")
    chapters = []
    current_chapter = None

    for line in lines:
        clean = line.strip()
        if not clean or len(clean) > 80:
            continue

        # 章标题：第X章 或 第一章
        if re.match(r'^第\s*\d+\s*章', clean) or \
           re.match(r'^第\s*[一二三四五六七八九十]+\s*章', clean):
            current_chapter = {"chapter": clean, "sections": []}
            chapters.append(current_chapter)

        # 二级小节：X.X 格式（排除X.X.X）
        elif current_chapter and \
                re.match(r'^\d+\.\d+\s+\S', clean) and \
                not re.match(r'^\d+\.\d+\.\d+', clean):
            current_chapter["sections"].append(clean)

    return chapters


def ai_process_chapter(chapter_data: dict, index: int) -> dict:
    """
    让AI给单个章节生成英文名（每次只处理一章，输出短，不截断）
    AI失败时自动用规则兜底
    """
    chapter_title = chapter_data["chapter"]
    sections = chapter_data["sections"]
    sections_text = "\n".join(f"  {s}" for s in sections) or "  （无小节）"

    prompt = f"""将以下教材章节标题翻译成英文。只输出JSON。

章节：{chapter_title}
小节：
{sections_text}

输出格式：
{{
  "name_en": "Chapter English Name",
  "children_en": ["Section 1 English Name", "Section 2 English Name"]
}}"""

    name_en = f"Chapter {index}"
    children_en = [f"Section {index}.{i+1}" for i in range(len(sections))]

    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            format="json",
            options={"temperature": 0.1, "num_predict": 500}
        )
        content = response["message"]["content"]
        content = content.replace("```json", "").replace("```", "").strip()
        result = json.loads(content)
        name_en = result.get("name_en", name_en)
        ai_children = result.get("children_en", [])
        if len(ai_children) == len(sections):
            children_en = ai_children
    except Exception:
        pass  # AI失败就用规则兜底的默认值

    return {
        "code": f"CH{index:02d}",
        "name_zh": chapter_title,
        "name_en": name_en,
        "level": 1,
        "children": [
            {
                "code": f"CH{index:02d}-{i+1:02d}",
                "name_zh": sec,
                "name_en": children_en[i] if i < len(children_en) else "",
                "level": 2
            }
            for i, sec in enumerate(sections)
        ]
    }


def get_subject_name(text_preview: str) -> dict:
    """AI推断学科名称"""
    prompt = f"""根据以下教材内容判断学科名称，只输出JSON。

内容：{text_preview[:500]}

格式：{{"subject": "English Name", "subject_zh": "中文名称"}}"""

    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            format="json",
            options={"temperature": 0.1, "num_predict": 100}
        )
        content = response["message"]["content"]
        content = content.replace("```json", "").replace("```", "").strip()
        return json.loads(content)
    except Exception:
        return {"subject": "Unknown", "subject_zh": "未知学科"}


def extract_and_save(text: str, filename: str, file_path: str) -> dict:
    """
    完整流程：提取知识点体系并写入数据库
    返回 {"document_id": x, "chapters": n, "knowledge_points": m}
    """
    file_type = filename.rsplit(".", 1)[-1].lower()

    # 规则提取章节
    chapters = extract_titles_by_rule(text)
    if not chapters:
        raise ValueError("未能识别到任何章节标题，请检查教材格式")

    # AI识别学科
    subject_info = get_subject_name(text)

    # 逐章处理
    knowledge_points = []
    for i, ch in enumerate(chapters):
        kp = ai_process_chapter(ch, i + 1)
        knowledge_points.append(kp)

    # 写入数据库
    with get_db() as (conn, cur):
        # 清理同名文档的旧数据
        cur.execute("""
            DELETE FROM knowledge_points WHERE document_id IN
            (SELECT id FROM documents WHERE filename = %s)
        """, (filename,))
        cur.execute("DELETE FROM documents WHERE filename = %s", (filename,))

        # 写入documents
        cur.execute("""
            INSERT INTO documents (filename, file_type, file_path, subject, status)
            VALUES (%s, %s, %s, %s, 'parsing')
            RETURNING id
        """, (filename, file_type, file_path,
              subject_info.get("subject_zh", "未知学科")))
        document_id = cur.fetchone()[0]

        # 写入知识点树
        kp_count = 0
        for kp in knowledge_points:
            cur.execute("""
                INSERT INTO knowledge_points
                    (document_id, code, name, name_en, parent_id, level, weight)
                VALUES (%s, %s, %s, %s, NULL, %s, 1.0)
                RETURNING id
            """, (document_id, kp["code"], kp["name_zh"],
                  kp["name_en"], kp["level"]))
            parent_id = cur.fetchone()[0]
            kp_count += 1

            for child in kp["children"]:
                cur.execute("""
                    INSERT INTO knowledge_points
                        (document_id, code, name, name_en, parent_id, level, weight)
                    VALUES (%s, %s, %s, %s, %s, %s, 1.0)
                """, (document_id, child["code"], child["name_zh"],
                      child["name_en"], parent_id, child["level"]))
                kp_count += 1

    return {
        "document_id": document_id,
        "subject": subject_info.get("subject_zh", ""),
        "chapters": len(chapters),
        "knowledge_points": kp_count
    }