from __future__ import annotations

import asyncio
import os
from typing import Any
from uuid import UUID

from elasticsearch import Elasticsearch, NotFoundError

LECTURE_INDEX_PROPERTIES: dict[str, dict[str, str]] = {
    "title": {"type": "text"},
    "annotation": {"type": "text"},
    "content_text": {"type": "text"},
    "lecture_type": {"type": "keyword"},
    "course": {"type": "text"},
}


class LectureSearchStore:
    def __init__(self) -> None:
        self.index_name = os.getenv("ELASTICSEARCH_LECTURES_INDEX", "lectures")
        self.client = Elasticsearch(
            os.getenv("ELASTICSEARCH_URL", "http://localhost:9200"),
            request_timeout=float(os.getenv("ELASTICSEARCH_TIMEOUT_SECONDS", "3")),
        )

    async def ensure_index(self) -> None:
        exists = await asyncio.to_thread(
            self.client.indices.exists, index=self.index_name
        )
        if exists:
            return
        await asyncio.to_thread(
            self.client.indices.create,
            index=self.index_name,
            mappings={
                "dynamic": "strict",
                "properties": LECTURE_INDEX_PROPERTIES,
            },
        )

    async def put(self, lecture_id: UUID, document: dict[str, Any]) -> None:
        await self.ensure_index()
        await asyncio.to_thread(
            self.client.index,
            index=self.index_name,
            id=str(lecture_id),
            document=document,
        )

    async def delete(self, lecture_id: UUID) -> None:
        try:
            await asyncio.to_thread(
                self.client.delete, index=self.index_name, id=str(lecture_id)
            )
        except NotFoundError:
            pass

    async def close(self) -> None:
        await asyncio.to_thread(self.client.close)


search_store = LectureSearchStore()
