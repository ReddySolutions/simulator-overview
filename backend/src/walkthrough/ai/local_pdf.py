"""Local PDF extraction using PyMuPDF — replacement for Document AI when LOCAL_DEV=true."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import pymupdf

from walkthrough.models.pdf import PDFExtraction, PDFImage, PDFSection, PDFTable

logger = logging.getLogger(__name__)

_IMAGE_TEMP_DIR = os.path.join(tempfile.gettempdir(), "walkthrough_images")


async def extract_pdf(pdf_path: str, pdf_id: str) -> PDFExtraction:
    """Extract structured data from a PDF using PyMuPDF.

    Drop-in replacement for document_ai.extract_pdf(). Reads the PDF locally,
    extracts text organized by headings, tables, and page images.

    Args:
        pdf_path: Local filesystem path or local:// URI to the PDF file.
        pdf_id: Unique identifier for this PDF.

    Returns:
        PDFExtraction with sections, tables, and images.
    """
    resolved = _resolve_path(pdf_path)
    doc = pymupdf.open(resolved)
    filename = os.path.basename(resolved)

    sections: list[PDFSection] = []
    tables: list[PDFTable] = []
    images: list[PDFImage] = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_number = page_idx + 1

        # Extract text blocks and organize into sections
        text_dict: dict = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)  # type: ignore[assignment]
        blocks: list[dict] = text_dict.get("blocks", [])
        current_heading = ""
        current_text_parts: list[str] = []

        for block in blocks:
            if block.get("type") != 0:  # Skip non-text blocks
                continue

            block_text = ""
            is_bold = False
            max_font_size = 0.0

            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    block_text += span.get("text", "")
                    if "bold" in span.get("font", "").lower():
                        is_bold = True
                    max_font_size = max(max_font_size, span.get("size", 0))

            block_text = block_text.strip()
            if not block_text:
                continue

            # Heuristic: headings are bold or larger text, short lines
            if _is_likely_heading(block_text, is_bold, max_font_size):
                if current_heading or current_text_parts:
                    sections.append(PDFSection(
                        heading=current_heading or "Untitled Section",
                        text="\n".join(current_text_parts),
                        page_number=page_number,
                        confidence=0.9,
                    ))
                current_heading = block_text
                current_text_parts = []
            else:
                current_text_parts.append(block_text)

        # Save last section on the page
        if current_heading or current_text_parts:
            sections.append(PDFSection(
                heading=current_heading or "Untitled Section",
                text="\n".join(current_text_parts),
                page_number=page_number,
                confidence=0.9,
            ))

        # Extract tables
        finder_result = page.find_tables()
        for table in finder_result.tables if finder_result else []:
            extracted = table.extract()
            if extracted and len(extracted) >= 2:
                headers = [str(c) if c else "" for c in extracted[0]]
                rows = [
                    [str(c) if c else "" for c in row]
                    for row in extracted[1:]
                ]
                tables.append(PDFTable(
                    headers=headers,
                    rows=rows,
                    page_number=page_number,
                ))

        # Extract page as image for screenshot analysis
        pix = page.get_pixmap(dpi=150)
        image_id = f"{pdf_id}_page_{page_number}"
        _store_page_image(image_id, pix.tobytes("png"))
        images.append(PDFImage(
            image_id=image_id,
            page_number=page_number,
            description=None,
            ui_elements=None,
        ))

    doc.close()

    return PDFExtraction(
        pdf_id=pdf_id,
        filename=filename,
        sections=sections,
        tables=tables,
        images=images,
    )


def get_extracted_image(image_id: str) -> bytes | None:
    """Retrieve extracted image bytes by image_id."""
    path = os.path.join(_IMAGE_TEMP_DIR, f"{image_id}.png")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    return None


def _resolve_path(pdf_path: str) -> str:
    """Resolve local:// URIs and GCS-style paths to local filesystem paths."""
    if pdf_path.startswith("local://"):
        from walkthrough.config import Settings
        settings = Settings()
        relative = pdf_path.removeprefix("local://")
        return str(Path(settings.LOCAL_DATA_DIR) / "uploads" / relative)
    if pdf_path.startswith("gs://"):
        # In local dev, GCS URIs shouldn't appear, but handle gracefully
        parts = pdf_path.split("/", 3)
        local_name = parts[3] if len(parts) > 3 else parts[-1]
        from walkthrough.config import Settings
        settings = Settings()
        return str(Path(settings.LOCAL_DATA_DIR) / "uploads" / local_name)
    return pdf_path


def _is_likely_heading(text: str, is_bold: bool, font_size: float) -> bool:
    """Heuristic to detect section headings."""
    if not text or len(text) > 100:
        return False
    if text.endswith("."):
        return False
    if len(text.split()) > 10:
        return False
    if is_bold:
        return True
    if font_size > 12:
        return True
    return False


def _store_page_image(image_id: str, content: bytes) -> None:
    """Store extracted page image to temp directory for screenshot analysis."""
    os.makedirs(_IMAGE_TEMP_DIR, exist_ok=True)
    path = os.path.join(_IMAGE_TEMP_DIR, f"{image_id}.png")
    with open(path, "wb") as f:
        f.write(content)
