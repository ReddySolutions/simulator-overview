"""Clarification API endpoints for viewing and answering questions during Phase 6.

Provides question listing (ordered by severity), answer submission, unanswerable
marking, status summary, and generation trigger. Generation is only allowed when
all critical gaps are resolved or acknowledged (M4, N3).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from walkthrough.ai.orchestrator import PhaseOrchestrator, ProgressEvent
from walkthrough.ai.tools.clarification import apply_answer, mark_unanswerable
from walkthrough.deps import get_firestore_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["clarification"])


# --- Response models ---


class QuestionResponse(BaseModel):
    question_id: str
    text: str
    severity: str
    evidence: list[Any]
    answer: str | None


class AnswerRequest(BaseModel):
    answer: str


class AnswerResponse(BaseModel):
    question_id: str
    answer: str
    follow_up_questions: list[QuestionResponse]


class UnanswerableResponse(BaseModel):
    question_id: str
    marked_unanswerable: bool


class QuestionsStatus(BaseModel):
    total: int
    answered: int
    unanswerable: int
    remaining_critical: int
    can_generate: bool


class GenerateResponse(BaseModel):
    project_id: str
    message: str


# --- Helpers ---


def _get_firestore():  # type: ignore[no-untyped-def]
    return get_firestore_client()


async def _run_generation_task(project_id: str) -> None:
    """Background task that runs generation and pushes events to the shared pipeline queue."""
    from walkthrough.api.projects import _active_pipelines

    queue = _active_pipelines.get(project_id)
    if queue is None:
        return

    try:
        orchestrator = PhaseOrchestrator()
        async for event in orchestrator.run_generation_phase(project_id):
            await queue.put(event)
    except Exception:
        logger.exception("Generation failed for project %s", project_id)
        await queue.put(
            ProgressEvent(phase="error", percentage=0, message="Generation failed")
        )
    finally:
        await queue.put(None)  # Sentinel


# --- Endpoints ---


@router.get("/{project_id}/questions", response_model=list[QuestionResponse])
async def list_questions(project_id: str) -> list[QuestionResponse]:
    """Return clarification questions with evidence, ordered by severity (critical first)."""
    fs = _get_firestore()
    project = await fs.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    severity_order = {"critical": 0, "medium": 1, "low": 2}
    sorted_questions = sorted(
        project.questions,
        key=lambda q: severity_order.get(q.severity, 3),
    )

    return [
        QuestionResponse(
            question_id=q.question_id,
            text=q.text,
            severity=q.severity,
            evidence=[ref.model_dump(mode="json") for ref in q.evidence],
            answer=q.answer,
        )
        for q in sorted_questions
    ]


@router.post(
    "/{project_id}/questions/{question_id}/answer",
    response_model=AnswerResponse,
)
async def answer_question(
    project_id: str,
    question_id: str,
    body: AnswerRequest,
) -> AnswerResponse:
    """Submit an answer to a clarification question.

    Applies the answer to the corresponding gap, persists state, and
    returns any follow-up questions generated from remaining gaps.
    """
    fs = _get_firestore()
    project = await fs.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Find the question
    question = next(
        (q for q in project.questions if q.question_id == question_id),
        None,
    )
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    # Apply answer to the corresponding gap
    project.gaps = await apply_answer(question_id, body.answer, project.gaps)

    # Record the answer on the question itself
    question.answer = body.answer

    await fs.save_project(project)

    # Check for remaining unanswered questions as follow-ups
    follow_ups = [
        QuestionResponse(
            question_id=q.question_id,
            text=q.text,
            severity=q.severity,
            evidence=[ref.model_dump(mode="json") for ref in q.evidence],
            answer=q.answer,
        )
        for q in project.questions
        if q.answer is None and q.question_id != question_id
    ]

    return AnswerResponse(
        question_id=question_id,
        answer=body.answer,
        follow_up_questions=follow_ups,
    )


@router.post(
    "/{project_id}/questions/{question_id}/unanswerable",
    response_model=UnanswerableResponse,
)
async def mark_question_unanswerable(
    project_id: str,
    question_id: str,
) -> UnanswerableResponse:
    """Mark a question as unanswerable.

    Critical gaps stay unresolved for N3 warning metadata on affected screens.
    Medium/low gaps are marked resolved with an unanswerable note.
    """
    fs = _get_firestore()
    project = await fs.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    question = next(
        (q for q in project.questions if q.question_id == question_id),
        None,
    )
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    project.gaps = await mark_unanswerable(question_id, project.gaps)
    question.answer = "Marked unanswerable by user"

    await fs.save_project(project)

    return UnanswerableResponse(
        question_id=question_id,
        marked_unanswerable=True,
    )


@router.get(
    "/{project_id}/questions/status",
    response_model=QuestionsStatus,
)
async def questions_status(project_id: str) -> QuestionsStatus:
    """Return question status summary including can_generate flag.

    can_generate is true only when all critical gaps are resolved or
    acknowledged as unanswerable (M4, N3).
    """
    fs = _get_firestore()
    project = await fs.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    total = len(project.questions)
    answered = sum(1 for q in project.questions if q.answer is not None)
    unanswerable = sum(
        1
        for q in project.questions
        if q.answer == "Marked unanswerable by user"
    )
    remaining_critical = sum(
        1
        for g in project.gaps
        if g.severity == "critical" and not g.resolved and g.resolution is None
    )
    # Can generate when all critical gaps have been addressed (resolved or acknowledged-unanswerable)
    can_generate = all(
        g.resolved or g.resolution is not None
        for g in project.gaps
        if g.severity == "critical"
    )

    return QuestionsStatus(
        total=total,
        answered=answered,
        unanswerable=unanswerable,
        remaining_critical=remaining_critical,
        can_generate=can_generate,
    )


@router.post("/{project_id}/generate", response_model=GenerateResponse)
async def trigger_generation(project_id: str) -> GenerateResponse:
    """Trigger Phase 7-8 generation. Only allowed when can_generate is true."""
    from walkthrough.api.projects import _active_pipelines

    fs = _get_firestore()
    project = await fs.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Verify can_generate
    can_generate = all(
        g.resolved or g.resolution is not None
        for g in project.gaps
        if g.severity == "critical"
    )
    if not can_generate:
        raise HTTPException(
            status_code=400,
            detail="Cannot generate: unresolved critical gaps remain",
        )

    if project_id in _active_pipelines:
        raise HTTPException(
            status_code=409,
            detail="Generation is already running for this project",
        )

    queue: asyncio.Queue[ProgressEvent | None] = asyncio.Queue()
    _active_pipelines[project_id] = queue
    asyncio.create_task(_run_generation_task(project_id))

    return GenerateResponse(
        project_id=project_id,
        message="Generation started",
    )
