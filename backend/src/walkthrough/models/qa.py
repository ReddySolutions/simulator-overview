from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from walkthrough.models.workflow import SourceRef


class ValidatorFinding(BaseModel):
    severity: Literal["critical", "medium", "low", "info"]
    code: str
    message: str
    screen_id: str | None = None
    evidence: list[SourceRef] = Field(default_factory=list)


class ValidatorResult(BaseModel):
    validator: str
    ok: bool
    findings: list[ValidatorFinding] = Field(default_factory=list)


class QAReport(BaseModel):
    project_id: str
    results: list[ValidatorResult]
    has_critical: bool
    generated_at: datetime
