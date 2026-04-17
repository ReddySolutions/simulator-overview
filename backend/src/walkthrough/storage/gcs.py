from __future__ import annotations

import asyncio
from functools import partial

from fastapi import UploadFile
from google.cloud import storage

from walkthrough.config import Settings

ALLOWED_CONTENT_TYPES = {"video/mp4", "application/pdf"}


class GCSClient:
    def __init__(self, bucket_name: str) -> None:
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket_name)
        self._settings = Settings()

    @property
    def bucket_name(self) -> str:
        return str(self._bucket.name)

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

        blob = self._bucket.blob(destination_path)
        await asyncio.to_thread(
            partial(blob.upload_from_string, data, content_type=content_type)
        )
        return f"gs://{self._bucket.name}/{destination_path}"

    async def download_blob(self, blob_path: str) -> bytes:
        blob = self._bucket.blob(blob_path)
        return await asyncio.to_thread(blob.download_as_bytes)

    async def list_blobs(self, prefix: str) -> list[str]:
        blobs = await asyncio.to_thread(
            partial(self._client.list_blobs, self._bucket, prefix=prefix)
        )
        return [blob.name for blob in blobs]

    async def delete_blob(self, blob_path: str) -> None:
        blob = self._bucket.blob(blob_path)
        await asyncio.to_thread(blob.delete)
