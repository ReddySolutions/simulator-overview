from __future__ import annotations

from datetime import datetime
from typing import Any

from google.cloud import firestore

from walkthrough.models.project import Project


def _serialize_value(value: Any) -> Any:
    """Convert Python types to Firestore-compatible JSON values."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class FirestoreClient:
    def __init__(self, collection: str) -> None:
        self._client = firestore.AsyncClient()
        self._collection = self._client.collection(collection)

    async def save_project(self, project: Project) -> None:
        data = project.model_dump(mode="json")
        await self._collection.document(project.project_id).set(data)

    async def load_project(self, project_id: str) -> Project | None:
        doc = await self._collection.document(project_id).get()
        if not doc.exists:
            return None
        return Project.model_validate(doc.to_dict())

    async def list_projects(self) -> list[dict[str, Any]]:
        query = self._collection.select(
            ["project_id", "name", "status", "updated_at"]
        )
        results: list[dict[str, Any]] = []
        async for doc in query.stream():
            data = doc.to_dict()
            if data is not None:
                results.append(data)
        return results

    async def delete_project(self, project_id: str) -> None:
        await self._collection.document(project_id).delete()

    async def update_project_field(
        self, project_id: str, field: str, value: Any
    ) -> None:
        await self._collection.document(project_id).update(
            {field: _serialize_value(value)}
        )
