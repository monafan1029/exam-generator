"""
文档解析模块
支持 PDF 和 Word (.docx) 文件，输出统一的纯文本格式
"""
import os
import pdfplumber
import docx


def parse_document(filepath: str) -> str:
    """
    解析文档，返回纯文本
    自动根据文件扩展名选择解析器
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"文件不存在: {filepath}")

    ext = filepath.rsplit(".", 1)[-1].lower()

    if ext == "pdf":
        return _parse_pdf(filepath)
    elif ext == "docx":
        return _parse_docx(filepath)
    else:
        raise ValueError(f"不支持的文件类型: {ext}，目前支持 pdf / docx")


def _parse_pdf(filepath: str) -> str:
    text_parts = []
    with pdfplumber.open(filepath) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                text_parts.append(text)
    return "\n".join(text_parts)


def _parse_docx(filepath: str) -> str:
    doc = docx.Document(filepath)
    text_parts = []
    for para in doc.paragraphs:
        if para.text.strip():
            text_parts.append(para.text)
    return "\n".join(text_parts)