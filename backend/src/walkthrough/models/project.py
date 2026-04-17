from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

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


class Choice(BaseModel):
    """A preset answer option for a ClarificationQuestion.

    Shown as a clickable button in the clarification UI; clicking submits
    the label as the question's answer. An optional description gives the
    user a short explanation of what picking this choice means.
    """

    label: str
    description: str | None = None


class ClarificationQuestion(BaseModel):
    question_id: str
    text: str
    severity: Literal["critical", "medium", "low"]
    evidence: list[SourceRef]
    choices: list[Choice] = []
    answer: str | None = None


class Project(BaseModel):
    project_id: str
    name: str
    status: Literal[
        "uploading",
        "analyzing",
        "clarifying",
        "generating",
        "complete",
        "qa_blocked",
    ]
    videos: list[VideoAnalysis]
    pdfs: list[PDFExtraction]
    decision_trees: list[DecisionTree]
    gaps: list[Gap]
    questions: list[ClarificationQuestion]
    walkthrough_output: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
