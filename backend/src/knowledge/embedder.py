"""
向量化模块
把knowledge_chunks的文本转成向量存库
"""
import ollama
from ..config import OLLAMA_EMBED_MODEL
from ..database import get_db


def embed_text(text: str) -> list:
    """单段文字转向量"""
    response = ollama.embeddings(
        model=OLLAMA_EMBED_MODEL,
        prompt=text[:1000]
    )
    return response["embedding"]


def embed_document_chunks(document_id: int,
                          progress_callback=None) -> dict:
    """
    把该文档所有未向量化的chunk逐个向量化并存库
    """
    with get_db() as (conn, cur):
        cur.execute("""
            SELECT id, chunk_text FROM knowledge_chunks
            WHERE document_id = %s
              AND embedding IS NULL
              AND chunk_text IS NOT NULL
            ORDER BY chunk_order
        """, (document_id,))
        chunks = cur.fetchall()

    total = len(chunks)
    success = 0
    failed = 0

    for i, (chunk_id, chunk_text) in enumerate(chunks):
        try:
            embedding = embed_text(chunk_text)
            with get_db() as (conn, cur):
                cur.execute("""
                    UPDATE knowledge_chunks
                    SET embedding = %s::vector
                    WHERE id = %s
                """, (str(embedding), chunk_id))
            success += 1
        except Exception:
            failed += 1

        if progress_callback:
            progress_callback(i + 1, total)

    # 更新文档状态为ready
    with get_db() as (conn, cur):
        cur.execute("UPDATE documents SET status='ready' WHERE id=%s",
                    (document_id,))

    return {"total": total, "success": success, "failed": failed}