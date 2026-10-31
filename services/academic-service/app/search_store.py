from __future__ import annotations

import asyncio
import os
from typing import Any, Literal
from uuid import UUID

from elasticsearch import Elasticsearch, NotFoundError
from elasticsearch.helpers import bulk

RUSSIAN_ANALYZER = "lecture_russian"
INDEX_VERSION_SUFFIX = "_ru_v1"
LECTURE_DOCUMENT_INDEX_PROPERTIES: dict[str, dict[str, str]] = {
    "document_type": {"type": "keyword"},
    "lecture_id": {"type": "keyword"},
    "material_id": {"type": "keyword"},
    "content_type": {"type": "keyword"},
    "content": {"type": "text", "analyzer": RUSSIAN_ANALYZER},
}

LECTURE_INDEX_SETTINGS = {
    "analysis": {
        "analyzer": {
            RUSSIAN_ANALYZER: {
                "type": "custom",
                "tokenizer": "standard",
                "filter": ["lowercase", "lecture_russian_stemmer"],
            }
        },
        "filter": {
            "lecture_russian_stemmer": {"type": "stemmer", "language": "russian"}
        },
    }
}


class SearchUnavailable(RuntimeError):
    """Raised when the Elasticsearch document projection cannot be queried."""


class LectureDocumentSearchStore:
    def __init__(self) -> None:
        base_index = os.getenv("ELASTICSEARCH_LECTURES_INDEX", "lectures")
        self.index_name = f"{base_index}{INDEX_VERSION_SUFFIX}"
        self.client = Elasticsearch(
            os.getenv("ELASTICSEARCH_URL", "http://localhost:9200"),
            request_timeout=float(os.getenv("ELASTICSEARCH_TIMEOUT_SECONDS", "3")),
        )

    async def ensure_index(self) -> None:
        exists = await asyncio.to_thread(
            self.client.indices.exists, index=self.index_name
        )
        if exists:
            mapping = await asyncio.to_thread(
                self.client.indices.get_mapping, index=self.index_name
            )
            current_properties = (
                mapping.get(self.index_name, {})
                .get("mappings", {})
                .get("properties", {})
            )
            if current_properties == LECTURE_DOCUMENT_INDEX_PROPERTIES:
                return
            raise SearchUnavailable(
                f"Unexpected mapping for index {self.index_name}; rebuild is required"
            )
        await asyncio.to_thread(
            self.client.indices.create,
            index=self.index_name,
            settings=LECTURE_INDEX_SETTINGS,
            mappings={
                "dynamic": "strict",
                "properties": LECTURE_DOCUMENT_INDEX_PROPERTIES,
            },
        )

    async def replace_lecture_documents(
        self,
        lecture_id: UUID,
        documents: list[tuple[str, dict[str, Any]]],
    ) -> None:
        await self.ensure_index()
        await asyncio.to_thread(
            self.client.delete_by_query,
            index=self.index_name,
            query={"term": {"lecture_id": str(lecture_id)}},
            conflicts="proceed",
            refresh=False,
        )
        actions = [
            {
                "_op_type": "index",
                "_index": self.index_name,
                "_id": document_id,
                "_source": document,
            }
            for document_id, document in documents
        ]
        if actions:
            await asyncio.to_thread(
                bulk,
                self.client,
                actions,
                refresh=False,
            )

    async def delete(self, lecture_id: UUID) -> None:
        try:
            await asyncio.to_thread(
                self.client.delete_by_query,
                index=self.index_name,
                query={"term": {"lecture_id": str(lecture_id)}},
                conflicts="proceed",
                refresh=False,
            )
        except NotFoundError:
            pass

    async def refresh(self) -> None:
        await asyncio.to_thread(self.client.indices.refresh, index=self.index_name)

    async def search(
        self,
        query: str,
        *,
        document_type: str | None,
        lecture_id: UUID | None,
        content_type: str | None,
        offset: int,
        limit: int,
    ) -> dict[str, Any]:
        filters: list[dict[str, Any]] = []
        if document_type is not None:
            filters.append({"term": {"document_type": document_type}})
        if lecture_id is not None:
            filters.append({"term": {"lecture_id": str(lecture_id)}})
        if content_type is not None:
            filters.append({"term": {"content_type": content_type}})
        try:
            await self.ensure_index()
            response = await asyncio.to_thread(
                self.client.search,
                index=self.index_name,
                query={
                    "bool": {
                        "must": [{"match": {"content": {"query": query}}}],
                        "filter": filters,
                    }
                },
                from_=offset,
                size=limit,
                sort=[{"_score": "desc"}],
                track_total_hits=True,
            )
        except Exception as exc:
            raise SearchUnavailable("Elasticsearch document search failed") from exc

        total_value = response["hits"]["total"]
        total = total_value["value"] if isinstance(total_value, dict) else total_value
        return {
            "items": [
                {
                    "document_id": hit["_id"],
                    "score": hit.get("_score"),
                    **hit["_source"],
                }
                for hit in response["hits"]["hits"]
            ],
            "limit": limit,
            "offset": offset,
            "total": total,
        }

    async def search_lecture_ids(
        self,
        query: str,
        mode: Literal["phrase", "words"],
        after: str | None,
        limit: int,
    ) -> dict[str, Any]:
        """Page over unique lecture IDs without Elasticsearch's result-window limit."""
        composite: dict[str, Any] = {
            "size": limit,
            "sources": [{"lecture_id": {"terms": {"field": "lecture_id"}}}],
        }
        if after is not None:
            composite["after"] = {"lecture_id": after}
        match = (
            {"match_phrase": {"content": {"query": query}}}
            if mode == "phrase"
            else {"match": {"content": {"query": query, "operator": "and"}}}
        )
        try:
            await self.ensure_index()
            response = await asyncio.to_thread(
                self.client.search,
                index=self.index_name,
                size=0,
                query=match,
                aggs={"lectures": {"composite": composite}},
            )
        except Exception as exc:
            raise SearchUnavailable("Elasticsearch lecture search failed") from exc
        aggregation = response["aggregations"]["lectures"]
        return {
            "items": [bucket["key"]["lecture_id"] for bucket in aggregation["buckets"]],
            "next_cursor": aggregation.get("after_key", {}).get("lecture_id"),
        }

    async def close(self) -> None:
        await asyncio.to_thread(self.client.close)


search_store = LectureDocumentSearchStore()
