from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from walkthrough.deps import get_firestore_client, get_storage_client
from walkthrough.models.project import Project
from walkthrough.storage.constants import ALLOWED_CONTENT_TYPES

router = APIRouter(prefix="/api/projects", tags=["upload"])

ALLOWED_EXTENSIONS = {".mp4": "video/mp4", ".pdf": "application/pdf"}


class CreateProjectRequest(BaseModel):
    name: str


class CreateProjectResponse(BaseModel):
    project_id: str
    name: str
    status: str


class FileInfo(BaseModel):
    filename: str
    content_type: str
    gcs_uri: str


class UploadResponse(BaseModel):
    filename: str
    content_type: str
    gcs_uri: str
    files: list[FileInfo]
    ready_for_analysis: bool


def _get_clients():  # type: ignore[no-untyped-def]
    return get_storage_client(), get_firestore_client()


@router.post("", response_model=CreateProjectResponse)
async def create_project(body: CreateProjectRequest) -> CreateProjectResponse:
    """Create a new project, returns project_id."""
    project_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    project = Project(
        project_id=project_id,
        name=body.name,
        status="uploading",
        videos=[],
        pdfs=[],
        decision_trees=[],
        gaps=[],
        questions=[],
        created_at=now,
        updated_at=now,
    )
    _, fs = _get_clients()
    await fs.save_project(project)
    return CreateProjectResponse(
        project_id=project_id,
        name=body.name,
        status="uploading",
    )


@router.post("/{project_id}/upload", response_model=UploadResponse)
async def upload_file(project_id: str, file: UploadFile) -> UploadResponse:
    """Upload an MP4 or PDF file to a project."""
    gcs, fs = _get_clients()

    project = await fs.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    content_type = file.content_type or ""
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{content_type}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}"
            ),
        )

    filename = file.filename or "untitled"
    destination = f"projects/{project_id}/uploads/{filename}"

    try:
        gcs_uri = await gcs.upload_file(file, destination)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await fs.update_project_field(
        project_id, "updated_at", datetime.now(timezone.utc).isoformat()
    )

    existing_blobs = await gcs.list_blobs(f"projects/{project_id}/uploads/")
    files = _blobs_to_file_info(existing_blobs, gcs.bucket_name)
    ready = _check_ready(files)

    return UploadResponse(
        filename=filename,
        content_type=content_type,
        gcs_uri=gcs_uri,
        files=files,
        ready_for_analysis=ready,
    )


def _blobs_to_file_info(blob_names: list[str], bucket_name: str) -> list[FileInfo]:
    """Convert GCS blob names to FileInfo list with inferred content types."""
    results: list[FileInfo] = []
    for name in blob_names:
        lower = name.lower()
        ct = "application/octet-stream"
        for ext, mime in ALLOWED_EXTENSIONS.items():
            if lower.endswith(ext):
                ct = mime
                break
        filename = name.rsplit("/", 1)[-1] if "/" in name else name
        results.append(
            FileInfo(
                filename=filename,
                content_type=ct,
                gcs_uri=f"gs://{bucket_name}/{name}",
            )
        )
    return results


def _check_ready(files: list[FileInfo]) -> bool:
    """At least one MP4 and one PDF required before analysis can start."""
    has_mp4 = any(f.content_type == "video/mp4" for f in files)
    has_pdf = any(f.content_type == "application/pdf" for f in files)
    return has_mp4 and has_pdf
