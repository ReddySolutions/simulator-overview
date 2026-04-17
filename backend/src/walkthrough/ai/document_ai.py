from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from functools import partial

from google.cloud import documentai

from walkthrough.config import Settings
from walkthrough.models.pdf import PDFExtraction, PDFImage, PDFSection, PDFTable

logger = logging.getLogger(__name__)

_IMAGE_TEMP_DIR = os.path.join(tempfile.gettempdir(), "walkthrough_images")


async def extract_pdf(pdf_path: str, pdf_id: str) -> PDFExtraction:
    """Extract structured data from a PDF using Google Document AI.

    Args:
        pdf_path: GCS URI (gs://...) or local path to the PDF file.
        pdf_id: Unique identifier for this PDF.

    Returns:
        PDFExtraction with sections, tables, and images.

    Raises:
        ValueError: If Document AI response cannot be parsed.
    """
    settings = Settings()
    pdf_content = await _read_pdf_content(pdf_path, settings)
    document = await _process_document(pdf_content, settings)
    filename = os.path.basename(pdf_path)
    return _parse_document(document, pdf_id, filename)


async def _read_pdf_content(pdf_path: str, settings: Settings) -> bytes:
    """Read PDF content from GCS URI or local path."""
    if pdf_path.startswith("gs://"):
        from walkthrough.storage.gcs import GCSClient

        client = GCSClient(settings.GCS_BUCKET)
        # Extract blob path from gs://bucket/path
        parts = pdf_path.split("/", 3)
        blob_path = parts[3] if len(parts) > 3 else ""
        return await client.download_blob(blob_path)

    return await asyncio.to_thread(_read_local_file, pdf_path)


def _read_local_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


async def _process_document(
    pdf_content: bytes, settings: Settings
) -> documentai.Document:
    """Send PDF to Document AI for processing."""
    processor_name = (
        f"projects/{settings.GCP_PROJECT_ID}"
        f"/locations/{settings.DOCUMENTAI_LOCATION}"
        f"/processors/{settings.DOCUMENTAI_PROCESSOR_ID}"
    )

    client = documentai.DocumentProcessorServiceClient()
    raw_document = documentai.RawDocument(
        content=pdf_content,
        mime_type="application/pdf",
    )
    request = documentai.ProcessRequest(
        name=processor_name,
        raw_document=raw_document,
    )

    result = await asyncio.to_thread(
        partial(client.process_document, request=request)
    )
    return result.document


def _extract_text_from_layout(
    full_text: str, text_anchor: documentai.Document.TextAnchor | None
) -> str:
    """Extract text from a Document AI text anchor."""
    if not text_anchor or not text_anchor.text_segments:
        return ""
    result = ""
    for segment in text_anchor.text_segments:
        start = int(segment.start_index)
        end = int(segment.end_index)
        result += full_text[start:end]
    return result.strip()


def _is_likely_heading(text: str) -> bool:
    """Heuristic to detect if a paragraph is likely a section heading."""
    if not text:
        return False
    stripped = text.strip()
    if len(stripped) > 100:
        return False
    if stripped.endswith("."):
        return False
    if len(stripped.split()) > 10:
        return False
    return True


def _parse_table(
    full_text: str,
    table: documentai.Document.Page.Table,
    page_number: int,
) -> PDFTable | None:
    """Parse a Document AI table into PDFTable model."""
    headers: list[str] = []
    rows: list[list[str]] = []

    for header_row in table.header_rows:
        for cell in header_row.cells:
            cell_text = _extract_text_from_layout(
                full_text, cell.layout.text_anchor
            )
            headers.append(cell_text)

    for body_row in table.body_rows:
        row: list[str] = []
        for cell in body_row.cells:
            cell_text = _extract_text_from_layout(
                full_text, cell.layout.text_anchor
            )
            row.append(cell_text)
        rows.append(row)

    if not headers and not rows:
        return None

    return PDFTable(headers=headers, rows=rows, page_number=page_number)


def _store_page_image(image_id: str, content: bytes) -> None:
    """Store extracted page image to temp directory for screenshot analysis."""
    os.makedirs(_IMAGE_TEMP_DIR, exist_ok=True)
    path = os.path.join(_IMAGE_TEMP_DIR, f"{image_id}.png")
    with open(path, "wb") as f:
        f.write(content)
    logger.info("Stored extracted image: %s", path)


def get_extracted_image(image_id: str) -> bytes | None:
    """Retrieve extracted image bytes by image_id.

    Returns:
        Image bytes if found, None otherwise.
    """
    path = os.path.join(_IMAGE_TEMP_DIR, f"{image_id}.png")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    return None


def _parse_document(
    document: documentai.Document, pdf_id: str, filename: str
) -> PDFExtraction:
    """Parse Document AI response into PDFExtraction model."""
    full_text = document.text or ""
    sections: list[PDFSection] = []
    tables: list[PDFTable] = []
    images: list[PDFImage] = []

    for page_idx, page in enumerate(document.pages):
        page_number = page.page_number or (page_idx + 1)

        # Extract sections from paragraphs
        current_heading = ""
        current_text_parts: list[str] = []
        current_confidence: float = 1.0

        for paragraph in page.paragraphs:
            para_text = _extract_text_from_layout(
                full_text, paragraph.layout.text_anchor
            )
            confidence = paragraph.layout.confidence

            if _is_likely_heading(para_text):
                # Save previous section if accumulated
                if current_heading or current_text_parts:
                    sections.append(
                        PDFSection(
                            heading=current_heading or "Untitled Section",
                            text="\n".join(current_text_parts),
                            page_number=page_number,
                            confidence=current_confidence,
                        )
                    )
                current_heading = para_text
                current_text_parts = []
                current_confidence = confidence if confidence else 1.0
            else:
                current_text_parts.append(para_text)
                # Track minimum confidence across paragraphs in this section
                if confidence and confidence > 0:
                    current_confidence = min(current_confidence, confidence)

        # Save last section on the page
        if current_heading or current_text_parts:
            sections.append(
                PDFSection(
                    heading=current_heading or "Untitled Section",
                    text="\n".join(current_text_parts),
                    page_number=page_number,
                    confidence=current_confidence,
                )
            )

        # Extract tables
        for table in page.tables:
            parsed_table = _parse_table(full_text, table, page_number)
            if parsed_table:
                tables.append(parsed_table)

        # Extract page images for screenshot analysis
        if page.image and page.image.content:
            image_id = f"{pdf_id}_page_{page_number}"
            _store_page_image(image_id, page.image.content)
            images.append(
                PDFImage(
                    image_id=image_id,
                    page_number=page_number,
                    description=None,
                    ui_elements=None,
                )
            )

    return PDFExtraction(
        pdf_id=pdf_id,
        filename=filename,
        sections=sections,
        tables=tables,
        images=images,
    )
