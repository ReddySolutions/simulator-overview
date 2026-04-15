from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from walkthrough.models.video import UIElement


class SourceRef(BaseModel):
    source_type: Literal["video", "audio", "pdf"]
    reference: str  # e.g. 'video1.mp4:01:23' or 'SOP.pdf:Section 3.2'
    excerpt: str | None = None


class Narrative(BaseModel):
    what: str
    why: str
    when_condition: str | None = None


class WorkflowScreen(BaseModel):
    screen_id: str
    title: str
    ui_elements: list[UIElement]
    narrative: Narrative | None = None
    evidence_tier: Literal["observed", "mentioned"]
    source_refs: list[SourceRef]


class BranchPoint(BaseModel):
    screen_id: str
    condition: str
    paths: dict[str, str]  # action -> next_screen_id


class DecisionTree(BaseModel):
    root_screen_id: str
    screens: dict[str, WorkflowScreen]
    branches: list[BranchPoint]
