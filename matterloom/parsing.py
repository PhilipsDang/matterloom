"""Extract source text without inventing PDF pages for Word documents."""
from __future__ import annotations

import io
import json
import os
import subprocess
import threading
import zipfile
from pathlib import Path

import pypdfium2 as pdfium
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
PDF_LOCK = threading.Lock()  # PDFium is not thread safe.
MAX_PAGES = 100


def render_page(path: Path, page_number: int, scale: float = 1.4) -> bytes:
    with PDF_LOCK:
        with pdfium.PdfDocument(str(path)) as pdf:
            if page_number < 1 or page_number > len(pdf):
                raise ValueError("页码超出范围。")
            page = pdf[page_number - 1]
            try:
                width, height = page.get_size()
                factor = min(scale, 2400 / max(width, height))
                bitmap = page.render(scale=factor)
                try:
                    img = bitmap.to_pil()
                    output = io.BytesIO()
                    img.save(output, format="PNG")
                    return output.getvalue()
                finally:
                    bitmap.close()
            finally:
                page.close()


def ocr_available() -> bool:
    return Path(os.environ.get("MATTERLOOM_OCR_BIN", ROOT / "work/bin/vision-ocr")).is_file()


def recognize(path: Path, page_number: int) -> dict:
    """OCR a single rendered page, entirely on the local machine."""
    import tempfile

    binary = Path(os.environ.get("MATTERLOOM_OCR_BIN", ROOT / "work/bin/vision-ocr"))
    if not binary.is_file():
        raise RuntimeError("本机尚未配置扫描识别；可查看原页并稍后重新解析。")
    with tempfile.TemporaryDirectory(prefix="matterloom-ocr-") as folder:
        image = Path(folder) / "page.png"
        image.write_bytes(render_page(path, page_number, 2.0))
        process = subprocess.run([str(binary), str(image)], capture_output=True, text=True, timeout=90)
        if process.returncode:
            raise RuntimeError("本机文字识别未成功，请核对原页或换用更清晰的文件。")
        result = json.loads(process.stdout)
        if not isinstance(result.get("text"), str):
            raise RuntimeError("文字识别未返回可用结果。")
        return result


def parse_pdf(path: Path, use_ocr: bool) -> dict:
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise ValueError("文件已加密，请上传解除密码保护后的副本。")
    if not reader.pages or len(reader.pages) > MAX_PAGES:
        raise ValueError(f"请上传 1–{MAX_PAGES} 页的 PDF。")
    units, warnings = [], []
    for index, page in enumerate(reader.pages, 1):
        text, method, note, lines = "", "text", "", []
        try:
            text = page.extract_text() or ""
        except Exception:
            note = "文字层读取失败。"
        # Short text layers can be a page number on an otherwise scanned page.
        try:
            has_images = bool(page.images)
        except Exception:
            has_images = True
        needs_ocr = len("".join(text.split())) < 35 and (has_images or not text.strip())
        if needs_ocr:
            if use_ocr:
                try:
                    result = recognize(path, index)
                    if result["text"].strip():
                        text, lines, method = result["text"], result.get("lines", []), "ocr"
                        note = "文字由 OCR 识别，金额、姓名和日期请与原页核对。"
                    else:
                        note = "未识别到可用文字；该页可能为空白或图像不清晰。"
                except Exception as exc:
                    note = str(exc) if isinstance(exc, RuntimeError) else "扫描识别超时或失败，可重试。"
            else:
                note = "该页文字层不足，可能是扫描页；开启扫描识别后可重新解析。"
        status = "ready" if text.strip() and (not needs_ocr or method == "ocr") else "needs_review"
        if has_images and not needs_ocr:
            status = "needs_review"
            note = "该页含文字及图片；本版提取文字层，图片中的额外文字请核对原页。"
        if status == "needs_review":
            warnings.append(f"第 {index} 页：{note}")
        units.append({"sequence": index, "page_number": index, "locator": f"文件第 {index} 页",
                      "text": text.strip(), "method": method, "status": status, "note": note,
                      "ocr_lines": lines})
    return {"units": units, "page_count": len(units), "warnings": warnings,
            "status": "partial" if warnings else "ready", "parser": "pypdf + Apple Vision" if any(u["method"] == "ocr" for u in units) else "pypdf"}


def parse_docx(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        if sum(i.file_size for i in archive.infolist()) > 60 * 1024 * 1024:
            raise ValueError("Word 文件解压后过大，请拆分后重试。")
        if "word/document.xml" not in archive.namelist():
            raise ValueError("文件不是有效的 DOCX 文档。")
        xml = archive.read("word/document.xml")
        has_revisions = b"<w:ins " in xml or b"<w:del " in xml
    document = Document(path)
    units, warnings = [], []
    paragraphs, tables = 0, 0
    for block in document.element.body.iterchildren():
        if block.tag.endswith("}p"):
            paragraphs += 1
            para = Paragraph(block, document)
            if para.text.strip():
                units.append({"locator": f"正文第 {paragraphs} 段", "text": para.text.strip()})
        elif block.tag.endswith("}tbl"):
            tables += 1
            table = Table(block, document)
            for row_index, row in enumerate(table.rows, 1):
                seen = set()
                for col_index, cell in enumerate(row.cells, 1):
                    if cell._tc in seen:
                        continue
                    seen.add(cell._tc)
                    text = cell.text.strip()
                    if text:
                        units.append({"locator": f"表格 {tables} · 第 {row_index} 行第 {col_index} 列", "text": text})
    for index, unit in enumerate(units, 1):
        unit.update(sequence=index, page_number=None, method="docx", status="ready", note="", ocr_lines=[])
    if document.inline_shapes:
        warnings.append("文档含图片；图片中的文字未提取，请下载原件核对。")
    if any(p.text.strip() for section in document.sections for area in [section.header, section.footer] for p in area.paragraphs):
        warnings.append("文档含页眉或页脚文字；本版提取正文，请下载原件核对其他区域。")
    if len(document.element.body.xpath('.//w:tbl')) > tables:
        warnings.append("文档含嵌套表格；内部表格未完整展开，请下载原件核对。")
    if has_revisions:
        warnings.append("文档包含修订痕迹；修订内容未完整展开，请在 Word 中核对。")
    if b"txbxContent" in xml or b"footnoteReference" in xml or b"endnoteReference" in xml:
        warnings.append("文档包含文本框或脚注等内容，本版本仅提取正文段落与普通表格。")
    if not units:
        warnings.append("未找到可读取的正文或表格文字。")
    return {"units": units, "page_count": None, "warnings": warnings,
            "status": "partial" if warnings else "ready", "parser": "python-docx"}


def parse(path: Path, kind: str, use_ocr: bool = True) -> dict:
    return parse_pdf(path, use_ocr) if kind == "pdf" else parse_docx(path)
