from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from walkthrough.models.pdf import PDFExtraction
from walkthrough.models.video import VideoAnalysis
from walkthrough.models.workflow import DecisionTree, SourceRef


class Gap(BaseModel):
    gap_id: str
    severity: Literal["critical", "medium", "low"]
    description: str
    evidence: list[SourceRef]
    resolution: str | None = None
    resolved: bool = False


class ClarificationQuestion(BaseModel):
    question_id: str
    text: str
    severity: Literal["critical", "medium", "low"]
    evidence: list[SourceRef]
    answer: str | None = None


class Project(BaseModel):
    project_id: str
    name: str
    status: Literal["uploading", "analyzing", "clarifying", "generating", "complete"]
    videos: list[VideoAnalysis]
    pdfs: list[PDFExtraction]
    decision_trees: list[DecisionTree]
    gaps: list[Gap]
    questions: list[ClarificationQuestion]
    created_at: datetime
    updated_at: datetime
