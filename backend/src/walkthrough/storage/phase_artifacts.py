"""Per-phase JSON artifacts written next to the monolithic project JSON.

Each phase writes a structured artifact so subsequent phases and QA
validators can read that phase's output directly, independent of the
monolithic project document. Artifact presence also drives resume logic.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from walkthrough.config import Settings

PHASE_ORDER = [
    "ingestion",
    "path_merge",
    "narrative",
    "contradictions",
    "clarification",
    "generation",
]


def _phases_dir(project_id: str) -> Path:
    settings = Settings()
    return (
        Path(settings.LOCAL_DATA_DIR)
        / "projects"
        / settings.FIRESTORE_COLLECTION
        / project_id
        / "phases"
    )


def _artifact_path(project_id: str, phase: str) -> Path:
    return _phases_dir(project_id) / f"{phase}.json"


async def write_phase_artifact(
    project_id: str, phase: str, payload: dict
) -> Path:
    """Write a phase artifact JSON file; returns the written path."""
    path = _artifact_path(project_id, phase)

    def _write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, default=str))

    await asyncio.to_thread(_write)
    return path


async def read_phase_artifact(project_id: str, phase: str) -> dict | None:
    """Return parsed JSON for a phase artifact, or None if absent."""
    path = _artifact_path(project_id, phase)

    def _read() -> dict | None:
        if not path.exists():
            return None
        return json.loads(path.read_text())

    return await asyncio.to_thread(_read)


def phase_artifact_exists(project_id: str, phase: str) -> bool:
    """Return True iff the artifact file exists on disk."""
    return _artifact_path(project_id, phase).exists()


def completed_phases(project_id: str) -> list[str]:
    """Return phases (in PHASE_ORDER sequence) whose artifact files exist."""
    return [p for p in PHASE_ORDER if phase_artifact_exists(project_id, p)]
