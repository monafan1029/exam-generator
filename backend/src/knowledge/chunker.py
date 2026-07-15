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
    if re.match(r'^第\s*\d+\s*章', clean) or \
       re.match(r'^第\s*[一二三四五六七八九十]+\s*章', clean):
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

def match_kp_by_section(current_section: str,
                        current_chapter: str,
                        kp_list: list) -> int | None:
    """用当前章节位置直接匹配知识点,不调用AI"""
    # 优先匹配小节名
    if current_section:
        for kp in kp_list:
            # 小节标题形如"6.1 大语言模型的毒性与偏见"
            # 知识点名形如"大语言模型的毒性与偏见"
            if kp["name"] in current_section or \
               current_section.endswith(kp["name"]):
                return kp["id"]
    # 小节没匹配上,退而匹配章名
    if current_chapter:
        for kp in kp_list:
            if kp["name"] in current_chapter:
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
            kp_id = label_chunk(chunk_text, kp_list, kp_options)
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