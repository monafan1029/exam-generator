"""
切片模块（Context-Aware版）
- 流式切片，不占内存
- 每个chunk自动注入所属章节信息（解决"该项目"类上下文缺失问题）
- AI打知识点标签，失败的块标签为空（保底不中断）
"""
import re
import ollama
from ..config import OLLAMA_MODEL
from ..database import get_db

CHUNK_SIZE = 500
SKIP_KEYWORDS = ["本章小结", "思考与练习", "参考文献", "附录", "前言", "目录"]


def load_knowledge_points(document_id: int) -> list:
    """加载该文档的知识点列表（过滤小结/练习）"""
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT id, code, name FROM knowledge_points
            WHERE document_id = %s ORDER BY id
        """, (document_id,))
        rows = cur.fetchall()

    return [
        {"id": r[0], "code": r[1], "name": r[2]}
        for r in rows
        if not any(kw in r[2] for kw in SKIP_KEYWORDS)
    ]


def detect_current_chapter(line: str) -> str | None:
    """检测这一行是否是章标题，是则返回标题文字"""
    clean = line.strip()
    if re.match(r'^第\s*\d+\s*[章讲]', clean) or \
       re.match(r'^第\s*[一二三四五六七八九十]+\s*[章讲]', clean) or \
       re.match(r'^(Chapter|Lecture)\s+\d+', clean, re.IGNORECASE):
        return clean
    return None


def detect_current_section(line: str) -> str | None:
    """检测这一行是否是小节标题"""
    clean = line.strip()
    if re.match(r'^\d+\.\d+\s+\S', clean) and \
       not re.match(r'^\d+\.\d+\.\d+', clean):
        return clean
    return None


def label_chunk(text: str, kp_list: list, kp_options: str) -> int | None:
    """AI给块打知识点标签，失败返回None（不中断流程）"""
    prompt = f"""判断以下文字属于哪个知识点，只输出编码，不要其他文字。

知识点：
{kp_options}

文字：
{text[:200]}

只输出编码："""

    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            think=False,
            options={"temperature": 0.1, "num_predict": 15}
        )
        code = re.sub(r'[^A-Z0-9\-]', '',
                      response["message"]["content"].strip().upper())
        for kp in kp_list:
            if kp["code"] == code:
                return kp["id"]
    except Exception:
        pass
    return None

_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_to_int(s: str) -> int | None:
    """中文数字转整数（支持一~九十九）"""
    if s in _CN_NUM:
        return _CN_NUM[s]
    if s.startswith("十"):
        return 10 + _CN_NUM.get(s[1:], 0)
    if s.endswith("十"):
        return _CN_NUM[s[0]] * 10
    if "十" in s:
        a, b = s.split("十", 1)
        return _CN_NUM.get(a, 0) * 10 + _CN_NUM.get(b, 0)
    return None


def _section_num(s: str) -> str | None:
    """提取小节编号前缀，如 '1.1    大语言模型的特点' -> '1.1'"""
    m = re.match(r'^(\d+\.\d+)(?!\.\d)', s.strip())
    return m.group(1) if m else None


def _chapter_num(s: str) -> str | None:
    """提取章编号，如 '第 1 章 概述' / '第一章' / 'Chapter 3' -> '1'/'1'/'3'"""
    clean = s.strip()
    m = re.match(r'^第\s*(\d+)\s*[章讲]', clean)
    if m:
        return m.group(1)
    m = re.match(r'^(?:Chapter|Lecture)\s+(\d+)', clean, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.match(r'^第\s*([一二三四五六七八九十]+)\s*[章讲]', clean)
    if m:
        n = _cn_to_int(m.group(1))
        return str(n) if n else None
    return None


def _squash(s: str) -> str:
    """去掉所有空白字符，用于名称对照（PDF提取的空格数经常不一致）"""
    return re.sub(r'\s+', '', s)


def match_kp_by_section(current_section: str,
                        current_chapter: str,
                        kp_list: list) -> int | None:
    """
    用当前章节位置直接匹配知识点，不调用AI。
    优先编号前缀匹配（对空格差异免疫），再退到去空白后的名称包含匹配。
    """
    # 1. 小节编号匹配："1.1 xxx" 只看 "1.1"
    if current_section:
        sec_num = _section_num(current_section)
        if sec_num:
            for kp in kp_list:
                if _section_num(kp["name"]) == sec_num:
                    return kp["id"]
        # 编号提不出来（如AI生成的主题名），退到去空白名称匹配
        sec_sq = _squash(current_section)
        for kp in kp_list:
            kp_sq = _squash(kp["name"])
            if kp_sq and (kp_sq in sec_sq or sec_sq.endswith(kp_sq)):
                return kp["id"]

    # 2. 章编号匹配："第 1 章" / "第一章" / "Chapter 1" 都归一到 "1"
    if current_chapter:
        ch_num = _chapter_num(current_chapter)
        if ch_num:
            for kp in kp_list:
                if _chapter_num(kp["name"]) == ch_num:
                    return kp["id"]
        ch_sq = _squash(current_chapter)
        for kp in kp_list:
            kp_sq = _squash(kp["name"])
            if kp_sq and kp_sq in ch_sq:
                return kp["id"]
    return None


def chunk_and_label(text: str, document_id: int,
                    progress_callback=None) -> dict:
    """
    完整流程：流式切片 + 注入章节上下文 + AI打标签 + 写库
    """
    kp_list = load_knowledge_points(document_id)
    if not kp_list:
        raise ValueError("该文档没有知识点，请先运行知识点提取")

    kp_options = "\n".join(f"  {kp['code']}: {kp['name']}"
                           for kp in kp_list)

    # 无章节结构的文档（如单篇lecture，只有一个根节点）：
    # AI打标签失败时归到根节点，保证内容不会因无标签而无法参与出题
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT id FROM knowledge_points
            WHERE document_id = %s AND level = 1
        """, (document_id,))
        roots = cur.fetchall()
    fallback_kp_id = roots[0][0] if len(roots) == 1 else None

    # 清理该文档的旧chunks
    with get_db() as (conn, cur):
        cur.execute("DELETE FROM knowledge_chunks WHERE document_id = %s",
                    (document_id,))

    buffer = ""
    chunk_order = 0
    labeled = 0
    unlabeled = 0

    # 实时跟踪当前章节位置（Context-Aware的核心）
    current_chapter = ""
    current_section = ""

    lines = text.split("\n")

    for line in lines:
        clean = line.strip()
        if not clean:
            continue

        # 更新当前章节/小节位置
        ch = detect_current_chapter(clean)
        if ch:
            current_chapter = ch
            current_section = ""
        sec = detect_current_section(clean)
        if sec:
            current_section = sec

        buffer += clean + "\n"

        if len(buffer) >= CHUNK_SIZE:
            chunk_text = buffer.strip()
            if len(chunk_text) > 30:
                chunk_order += 1

                # ===== Context-Aware：注入章节上下文 =====
                context_prefix = ""
                if current_chapter:
                    context_prefix += f"[本段出自：{current_chapter}"
                    if current_section:
                        context_prefix += f" > {current_section}"
                    context_prefix += "]\n"

                full_chunk = context_prefix + chunk_text
                # =========================================

                # 先规则匹配（零成本），匹配不上再用AI兜底
                kp_id = match_kp_by_section(current_section, current_chapter, kp_list)
                if kp_id is None:
                    kp_id = label_chunk(chunk_text, kp_list, kp_options)
                if kp_id is None:
                    kp_id = fallback_kp_id
                if kp_id:
                    labeled += 1
                else:
                    unlabeled += 1

                with get_db() as (conn, cur):
                    cur.execute("""
                        INSERT INTO knowledge_chunks
                            (document_id, knowledge_point_id, chunk_text,
                             chunk_order, token_estimate)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (document_id, kp_id, full_chunk,
                          chunk_order, len(full_chunk) // 2))

                if progress_callback:
                    progress_callback(chunk_order, labeled, unlabeled)

            # 保留重叠部分
            buffer = buffer[-100:]

    # 处理最后剩余
    if buffer.strip() and len(buffer.strip()) > 30:
        chunk_order += 1
        kp_id = match_kp_by_section(current_section, current_chapter, kp_list)
        if kp_id is None:
            kp_id = label_chunk(buffer.strip(), kp_list, kp_options)
        if kp_id is None:
            kp_id = fallback_kp_id
        if kp_id:
            labeled += 1
        else:
            unlabeled += 1
        with get_db() as (conn, cur):
            cur.execute("""
                INSERT INTO knowledge_chunks
                    (document_id, knowledge_point_id, chunk_text,
                     chunk_order, token_estimate)
                VALUES (%s, %s, %s, %s, %s)
            """, (document_id, kp_id, buffer.strip(),
                  chunk_order, len(buffer) // 2))

    # 更新文档状态
    with get_db() as (conn, cur):
        cur.execute("UPDATE documents SET status='chunking' WHERE id=%s",
                    (document_id,))

    return {
        "total_chunks": chunk_order,
        "labeled": labeled,
        "unlabeled": unlabeled
    }