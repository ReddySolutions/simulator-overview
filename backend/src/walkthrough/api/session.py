"""Session persistence and regeneration API endpoints.

Provides session state inspection, pipeline resumption, clarification
reopening, and walkthrough regeneration. All state is loaded from Firestore
(M8) — no in-memory dependency, survives server restart.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from walkthrough.ai.orchestrator import PhaseOrchestrator, ProgressEvent
from walkthrough.config import Settings
from walkthrough.storage.firestore import FirestoreClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["session"])


# --- Response models ---


class SessionState(BaseModel):
    project_id: str
    phase: str
    progress: int
    pending_questions: int
    can_resume: bool


class ResumeResponse(BaseModel):
    project_id: str
    message: str
    resumed_from_phase: str


class ReopenResponse(BaseModel):
    project_id: str
    message: str
    question_count: int


class RegenerateResponse(BaseModel):
    project_id: str
    message: str


# --- Helpers ---


def _get_firestore() -> FirestoreClient:
    settings = Settings()
    return FirestoreClient(collection=settings.FIRESTORE_COLLECTION)


def _phase_to_progress(status: str) -> int:
    """Map project status to approximate progress percentage."""
    return {
        "uploading": 0,
        "analyzing": 25,
        "clarifying": 75,
        "generating": 90,
        "complete": 100,
    }.get(status, 0)


async def _run_resume_task(project_id: str) -> None:
    """Background task that resumes the pipeline and pushes events to shared queue."""
    from walkthrough.api.projects import _active_pipelines

    queue = _active_pipelines.get(project_id)
    if queue is None:
        return

    try:
        orchestrator = PhaseOrchestrator()
        async for event in orchestrator.run_pipeline(project_id):
            await queue.put(event)
    except Exception:
        logger.exception("Resume pipeline failed for project %s", project_id)
        await queue.put(
            ProgressEvent(phase="error", percentage=0, message="Resume failed")
        )
    finally:
        await queue.put(None)  # Sentinel


async def _run_regeneration_task(project_id: str) -> None:
    """Background task that re-runs generation and pushes events to shared queue."""
    from walkthrough.api.projects import _active_pipelines

    queue = _active_pipelines.get(project_id)
    if queue is None:
        return

    try:
        orchestrator = PhaseOrchestrator()
        async for event in orchestrator.run_generation_phase(project_id):
            await queue.put(event)
    except Exception:
        logger.exception("Regeneration failed for project %s", project_id)
        await queue.put(
            ProgressEvent(
                phase="error", percentage=0, message="Regeneration failed"
            )
        )
    finally:
        await queue.put(None)  # Sentinel


# --- Endpoints ---


@router.get("/{project_id}/session", response_model=SessionState)
async def get_session(project_id: str) -> SessionState:
    """Return current session state: phase, progress, pending questions, can_resume.

    All state loaded from Firestore (M8) — survives server restart.
    """
    fs = _get_firestore()
    project = await fs.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    pending = sum(1 for q in project.questions if q.answer is None)

    # Can resume if not complete and not currently uploading with no files
    can_resume = project.status not in ("complete", "uploading")

    return SessionState(
        project_id=project.project_id,
        phase=project.status,
        progress=_phase_to_progress(project.status),
        pending_questions=pending,
        can_resume=can_resume,
    )


@router.post("/{project_id}/resume", response_model=ResumeResponse)
async def resume_pipeline(project_id: str) -> ResumeResponse:
    """Resume pipeline from last persisted phase.

    Skips completed phases, picks up mid-clarification if needed.
    The orchestrator infers the resume point from project state stored
    in Firestore (M8).
    """
    from walkthrough.api.projects import _active_pipelines

    fs = _get_firestore()
    project = await fs.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.status == "complete":
        raise HTTPException(
            status_code=400,
            detail="Project is already complete. Use reopen-clarification or regenerate.",
        )

    if project.status == "uploading":
        raise HTTPException(
            status_code=400,
            detail="Project has no files to analyze. Upload files first.",
        )

    if project_id in _active_pipelines:
        raise HTTPException(
            status_code=409,
            detail="Pipeline is already running for this project",
        )

    resumed_from = project.status

    queue: asyncio.Queue[ProgressEvent | None] = asyncio.Queue()
    _active_pipelines[project_id] = queue
    asyncio.create_task(_run_resume_task(project_id))

    return ResumeResponse(
        project_id=project_id,
        message="Pipeline resumed",
        resumed_from_phase=resumed_from,
    )


@router.post(
    "/{project_id}/reopen-clarification",
    response_model=ReopenResponse,
)
async def reopen_clarification(project_id: str) -> ReopenResponse:
    """Reopen Phase 6 for a completed project.

    Loads existing questions/answers for editing without re-uploading or
    re-analyzing source files. Transitions project status back to
    'clarifying' so the clarification API endpoints work normally.
    """
    fs = _get_firestore()
    project = await fs.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.status != "complete":
        raise HTTPException(
            status_code=400,
            detail="Only completed projects can reopen clarification",
        )

    project.status = "clarifying"
    from datetime import datetime, timezone
    project.updated_at = datetime.now(timezone.utc)
    await fs.save_project(project)

    return ReopenResponse(
        project_id=project_id,
        message="Clarification reopened. Edit answers and regenerate when ready.",
        question_count=len(project.questions),
    )


@router.post("/{project_id}/regenerate", response_model=RegenerateResponse)
async def regenerate_walkthrough(project_id: str) -> RegenerateResponse:
    """Re-run Phase 7-8 with current answers.

    Overwrites previous output (V1 overwrite model, no version history).
    Only allowed when all critical gaps are resolved or acknowledged.
    """
    from walkthrough.api.projects import _active_pipelines

    fs = _get_firestore()
    project = await fs.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.status not in ("clarifying", "complete"):
        raise HTTPException(
            status_code=400,
            detail="Project must be in clarifying or complete state to regenerate",
        )

    # Verify all critical gaps are resolved or acknowledged
    can_generate = all(
        g.resolved or g.resolution is not None
        for g in project.gaps
        if g.severity == "critical"
    )
    if not can_generate:
        raise HTTPException(
            status_code=400,
            detail="Cannot regenerate: unresolved critical gaps remain",
        )

    if project_id in _active_pipelines:
        raise HTTPException(
            status_code=409,
            detail="Generation is already running for this project",
        )

    queue: asyncio.Queue[ProgressEvent | None] = asyncio.Queue()
    _active_pipelines[project_id] = queue
    asyncio.create_task(_run_regeneration_task(project_id))

    return RegenerateResponse(
        project_id=project_id,
        message="Regeneration started",
    )
