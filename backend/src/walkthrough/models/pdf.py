from __future__ import annotations

from pydantic import BaseModel

from walkthrough.models.video import UIElement


class PDFSection(BaseModel):
    heading: str
    text: str
    page_number: int
    confidence: float


class PDFTable(BaseModel):
    headers: list[str]
    rows: list[list[str]]
    page_number: int


class PDFImage(BaseModel):
    image_id: str
    page_number: int
    description: str | None = None
    ui_elements: list[UIElement] | None = None


class PDFExtraction(BaseModel):
    pdf_id: str
    filename: str
    sections: list[PDFSection]
    tables: list[PDFTable]
    images: list[PDFImage]
