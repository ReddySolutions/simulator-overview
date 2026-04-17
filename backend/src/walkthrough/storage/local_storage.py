"""Local filesystem replacement for GCS — used when LOCAL_DEV=true."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import UploadFile

from walkthrough.config import Settings
from walkthrough.storage.constants import ALLOWED_CONTENT_TYPES


class LocalStorageClient:
    """Drop-in replacement for GCSClient that stores files on the local filesystem."""

    def __init__(self, base_dir: str | None = None) -> None:
        settings = Settings()
        self._base = Path(base_dir or settings.LOCAL_DATA_DIR) / "uploads"
        self._base.mkdir(parents=True, exist_ok=True)
        self._settings = settings

    @property
    def bucket_name(self) -> str:
        return str(self._base)

    async def upload_file(self, file: UploadFile, destination_path: str) -> str:
        content_type = file.content_type or ""
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise ValueError(
                f"Unsupported content type '{content_type}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}"
            )

        data = await file.read()

        if content_type == "video/mp4":
            max_bytes = self._settings.MAX_VIDEO_SIZE_MB * 1024 * 1024
            if len(data) > max_bytes:
                raise ValueError(
                    f"MP4 file exceeds {self._settings.MAX_VIDEO_SIZE_MB}MB limit"
                )

        dest = self._base / destination_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return f"local://{destination_path}"

    async def download_blob(self, blob_path: str) -> bytes:
        path = self._base / blob_path
        if not path.exists():
            raise FileNotFoundError(f"Local blob not found: {blob_path}")
        return path.read_bytes()

    async def list_blobs(self, prefix: str) -> list[str]:
        prefix_path = self._base / prefix
        if not prefix_path.exists():
            return []
        results: list[str] = []
        for p in prefix_path.rglob("*"):
            if p.is_file():
                results.append(str(p.relative_to(self._base)))
        return results

    async def delete_blob(self, blob_path: str) -> None:
        path = self._base / blob_path
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)

    def local_path(self, blob_path: str) -> str:
        """Return the absolute local filesystem path for a blob."""
        return str(self._base / blob_path)
