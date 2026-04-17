"""Project CRUD and analysis API endpoints.

Provides list/get/delete for projects and triggers the PhaseOrchestrator
pipeline as a background task with SSE progress streaming.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from starlette.requests import Request

from walkthrough.ai.orchestrator import PhaseOrchestrator, ProgressEvent
from walkthrough.deps import get_firestore_client, get_storage_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])

# Active pipeline event queues keyed by project_id.
# POST /analyze pushes events; GET /progress reads them via SSE.
_active_pipelines: dict[str, asyncio.Queue[ProgressEvent | None]] = {}


# --- Response models ---


class ProjectSummary(BaseModel):
    project_id: str
    name: str
    status: str
    updated_at: str


class ProjectDetail(BaseModel):
    project_id: str
    name: str
    status: str
    videos: list[Any]
    pdfs: list[Any]
    decision_trees: list[Any]
    gaps: list[Any]
    questions: list[Any]
    walkthrough_output: dict[str, Any] | None
    created_at: str
    updated_at: str


class AnalyzeResponse(BaseModel):
    project_id: str
    message: str


# --- Helpers ---


def _get_clients():  # type: ignore[no-untyped-def]
    return get_storage_client(), get_firestore_client()


async def _has_required_files(storage: Any, project_id: str) -> bool:
    """Check that at least one MP4 and one PDF have been uploaded."""
    blobs = await storage.list_blobs(f"projects/{project_id}/uploads/")
    has_mp4 = any(b.lower().endswith(".mp4") for b in blobs)
    has_pdf = any(b.lower().endswith(".pdf") for b in blobs)
    return has_mp4 and has_pdf


async def _run_pipeline_task(project_id: str) -> None:
    """Background task that runs the orchestrator and pushes events to the queue."""
    queue = _active_pipelines.get(project_id)
    if queue is None:
        return

    try:
        orchestrator = PhaseOrchestrator()
        async for event in orchestrator.run_pipeline(project_id):
            await queue.put(event)
    except Exception:
        logger.exception("Pipeline failed for project %s", project_id)
        await queue.put(
            ProgressEvent(phase="error", percentage=0, message="Pipeline failed")
        )
    finally:
        await queue.put(None)  # Sentinel — signals end of stream


# --- Endpoints ---


@router.get("", response_model=list[ProjectSummary])
async def list_projects() -> list[ProjectSummary]:
    """List all projects (id, name, status, updated_at)."""
    _, fs = _get_clients()
    rows = await fs.list_projects()
    return [
        ProjectSummary(
            project_id=r.get("project_id", ""),
            name=r.get("name", ""),
            status=r.get("status", ""),
            updated_at=str(r.get("updated_at", "")),
        )
        for r in rows
    ]


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: str) -> ProjectDetail:
    """Full project details including walkthrough output."""
    _, fs = _get_clients()
    project = await fs.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    data = project.model_dump(mode="json")
    return ProjectDetail(
        project_id=data["project_id"],
        name=data["name"],
        status=data["status"],
        videos=data["videos"],
        pdfs=data["pdfs"],
        decision_trees=data["decision_trees"],
        gaps=data["gaps"],
        questions=data["questions"],
        walkthrough_output=data.get("walkthrough_output"),
        created_at=str(data["created_at"]),
        updated_at=str(data["updated_at"]),
    )


@router.delete("/{project_id}")
async def delete_project(project_id: str) -> dict[str, str]:
    """Delete project document and all GCS files."""
    gcs, fs = _get_clients()

    project = await fs.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Delete all GCS blobs under the project prefix
    blobs = await gcs.list_blobs(f"projects/{project_id}/")
    for blob_path in blobs:
        await gcs.delete_blob(blob_path)

    await fs.delete_project(project_id)
    return {"detail": "Project deleted"}


@router.post("/{project_id}/analyze", response_model=AnalyzeResponse)
async def analyze_project(project_id: str) -> AnalyzeResponse:
    """Trigger the PhaseOrchestrator pipeline as a background task."""
    gcs, fs = _get_clients()

    project = await fs.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if not await _has_required_files(gcs, project_id):
        raise HTTPException(
            status_code=400,
            detail="Project requires at least one MP4 and one PDF before analysis",
        )

    if project_id in _active_pipelines:
        return AnalyzeResponse(
            project_id=project_id,
            message="Analysis already running",
        )

    queue: asyncio.Queue[ProgressEvent | None] = asyncio.Queue()
    _active_pipelines[project_id] = queue

    asyncio.create_task(_run_pipeline_task(project_id))

    return AnalyzeResponse(
        project_id=project_id,
        message="Analysis started",
    )


@router.get("/{project_id}/progress")
async def stream_progress(project_id: str, request: Request) -> EventSourceResponse:
    """SSE endpoint streaming phase progress events from the orchestrator."""

    async def event_generator():  # type: ignore[no-untyped-def]
        queue = _active_pipelines.get(project_id)
        if queue is None:
            # No active pipeline — check if project exists and report status
            _, fs = _get_clients()
            project = await fs.load_project(project_id)
            if project is None:
                yield {
                    "event": "error",
                    "data": json.dumps({"message": "Project not found"}),
                }
                return
            yield {
                "event": "status",
                "data": json.dumps({
                    "phase": project.status,
                    "percentage": 100 if project.status == "complete" else 0,
                    "message": f"Project status: {project.status}",
                }),
            }
            return

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield {"event": "ping", "data": ""}
                    continue

                if event is None:
                    # Pipeline finished
                    break

                yield {
                    "event": "progress",
                    "data": json.dumps({
                        "phase": event.phase,
                        "percentage": event.percentage,
                        "message": event.message,
                    }),
                }
        finally:
            # Clean up the queue when the client disconnects or pipeline ends
            _active_pipelines.pop(project_id, None)

    return EventSourceResponse(event_generator())
