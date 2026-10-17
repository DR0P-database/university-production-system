from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote_plus
from uuid import UUID

from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection

COLLECTION_NAME = "lecture_material_contents"


def _mongo_uri() -> str:
    if uri := os.getenv("MONGODB_URI"):
        return uri
    user = quote_plus(os.getenv("MONGODB_USER", "academic_service"))
    password = quote_plus(
        os.getenv("MONGODB_PASSWORD", "academic-mongo-local-password")
    )
    host = os.getenv("MONGODB_HOST", "localhost")
    port = os.getenv("MONGODB_PORT", "27017")
    auth_source = quote_plus(os.getenv("MONGODB_AUTH_SOURCE", "academic_content"))
    return f"mongodb://{user}:{password}@{host}:{port}/?authSource={auth_source}"


class MaterialContentStore:
    def __init__(self) -> None:
        self.database_name = os.getenv("MONGODB_ACADEMIC_DB", "academic_content")
        self.client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(
            _mongo_uri(),
            serverSelectionTimeoutMS=int(
                os.getenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "3000")
            ),
        )
        self.collection: AsyncCollection[dict[str, Any]] = self.client[
            self.database_name
        ][COLLECTION_NAME]

    def reference(self, material_id: UUID) -> str:
        return f"mongodb://{self.database_name}/{COLLECTION_NAME}/{material_id}"

    async def ensure_indexes(self) -> None:
        await self.client.admin.command("ping")

    async def put(
        self,
        material_id: UUID,
        content_text: str | None,
        metadata: dict[str, Any],
    ) -> str | None:
        document: dict[str, Any] = {"_id": str(material_id)}
        if content_text is not None:
            document["content_text"] = content_text
        if metadata:
            document["metadata"] = metadata

        if len(document) == 1:
            await self.delete(material_id)
            return None

        await self.collection.replace_one(
            {"_id": str(material_id)}, document, upsert=True
        )
        return self.reference(material_id)

    async def get(self, material_id: UUID) -> dict[str, Any]:
        document = await self.collection.find_one({"_id": str(material_id)})
        return document or {}

    async def get_many(self, material_ids: list[UUID]) -> dict[str, dict[str, Any]]:
        if not material_ids:
            return {}
        result: dict[str, dict[str, Any]] = {}
        cursor = self.collection.find(
            {"_id": {"$in": [str(item_id) for item_id in material_ids]}}
        )
        async for document in cursor:
            result[str(document["_id"])] = document
        return result

    async def delete(self, material_id: UUID) -> None:
        await self.collection.delete_one({"_id": str(material_id)})

    async def delete_many(self, material_ids: list[UUID]) -> None:
        if material_ids:
            await self.collection.delete_many(
                {"_id": {"$in": [str(item_id) for item_id in material_ids]}}
            )

    async def close(self) -> None:
        await self.client.close()


content_store = MaterialContentStore()
