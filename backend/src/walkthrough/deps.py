"""Dependency factories — return GCP or local clients based on LOCAL_DEV setting."""

from __future__ import annotations

from typing import TYPE_CHECKING

from walkthrough.config import Settings

if TYPE_CHECKING:
    from walkthrough.storage.firestore import FirestoreClient
    from walkthrough.storage.gcs import GCSClient
    from walkthrough.storage.local_firestore import LocalFirestoreClient
    from walkthrough.storage.local_storage import LocalStorageClient


def get_storage_client() -> GCSClient | LocalStorageClient:
    """Return a GCSClient or LocalStorageClient depending on LOCAL_DEV."""
    settings = Settings()
    if settings.LOCAL_DEV:
        from walkthrough.storage.local_storage import LocalStorageClient
        return LocalStorageClient()
    from walkthrough.storage.gcs import GCSClient
    return GCSClient(bucket_name=settings.GCS_BUCKET)


def get_firestore_client(
    collection: str | None = None,
) -> FirestoreClient | LocalFirestoreClient:
    """Return a FirestoreClient or LocalFirestoreClient depending on LOCAL_DEV."""
    settings = Settings()
    name = collection or settings.FIRESTORE_COLLECTION
    if settings.LOCAL_DEV:
        from walkthrough.storage.local_firestore import LocalFirestoreClient
        return LocalFirestoreClient(collection=name)
    from walkthrough.storage.firestore import FirestoreClient
    return FirestoreClient(collection=name)
