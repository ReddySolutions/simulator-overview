"""Local JSON-file replacement for Firestore — used when LOCAL_DEV=true."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from walkthrough.config import Settings
from walkthrough.models.project import Project


class LocalFirestoreClient:
    """Drop-in replacement for FirestoreClient that stores projects as JSON files."""

    def __init__(self, collection: str | None = None) -> None:
        settings = Settings()
        name = collection or settings.FIRESTORE_COLLECTION
        self._dir = Path(settings.LOCAL_DATA_DIR) / "projects" / name
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, project_id: str) -> Path:
        return self._dir / f"{project_id}.json"

    async def save_project(self, project: Project) -> None:
        data = project.model_dump(mode="json")
        self._path(project.project_id).write_text(
            json.dumps(data, indent=2, default=str)
        )

    async def load_project(self, project_id: str) -> Project | None:
        path = self._path(project_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return Project.model_validate(data)

    async def list_projects(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for path in self._dir.glob("*.json"):
            data = json.loads(path.read_text())
            results.append({
                "project_id": data.get("project_id", ""),
                "name": data.get("name", ""),
                "status": data.get("status", ""),
                "updated_at": data.get("updated_at", ""),
            })
        return results

    async def delete_project(self, project_id: str) -> None:
        path = self._path(project_id)
        if path.exists():
            path.unlink()

    async def update_project_field(
        self, project_id: str, field: str, value: Any
    ) -> None:
        path = self._path(project_id)
        if not path.exists():
            return
        data = json.loads(path.read_text())
        if isinstance(value, datetime):
            value = value.isoformat()
        data[field] = value
        path.write_text(json.dumps(data, indent=2, default=str))
