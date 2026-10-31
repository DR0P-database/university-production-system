from __future__ import annotations

import importlib
import os
from uuid import uuid4

import pytest
from elasticsearch import Elasticsearch


@pytest.mark.asyncio
async def test_existing_index_with_old_mapping_is_not_deleted(load_app, monkeypatch):
    load_app("services/academic-service")
    module = importlib.import_module("app.search_store")
    store = module.LectureDocumentSearchStore()

    class Indices:
        def exists(self, *, index):
            return True

        def get_mapping(self, *, index):
            properties = {
                key: {"type": value["type"]}
                for key, value in module.LECTURE_DOCUMENT_INDEX_PROPERTIES.items()
            }
            return {index: {"mappings": {"properties": properties}}}

        def delete(self, *, index):
            pytest.fail("The incompatible index must not be deleted")

    monkeypatch.setattr(store.client, "indices", Indices())
    try:
        with pytest.raises(module.SearchUnavailable, match="Unexpected mapping"):
            await store.ensure_index()
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_russian_inflections_and_phrase_positions_in_elasticsearch(load_app):
    url = os.getenv("TEST_ELASTICSEARCH_URL")
    if not url:
        pytest.skip("Set TEST_ELASTICSEARCH_URL to run Elasticsearch integration tests")

    load_app("services/academic-service")
    module = importlib.import_module("app.search_store")
    store = module.LectureDocumentSearchStore()
    await store.close()
    store.client = Elasticsearch(url)
    store.index_name = f"test-lecture-russian-{uuid4().hex}"
    lecture_id = uuid4()
    try:
        await store.ensure_index()
        await store.replace_lecture_documents(
            lecture_id,
            [
                (
                    "description:test",
                    {
                        "document_type": "description",
                        "lecture_id": str(lecture_id),
                        "content": "Основы базы данных",
                    },
                )
            ],
        )
        await store.refresh()
        result = await store.search(
            "база данных",
            document_type=None,
            lecture_id=None,
            content_type=None,
            offset=0,
            limit=10,
        )
        assert result["total"] == 1
        words = await store.search_lecture_ids("данные база", "words", None, 10)
        assert words["items"] == [str(lecture_id)]
        missing_word = await store.search_lecture_ids(
            "база отсутствует", "words", None, 10
        )
        assert missing_word["items"] == []
        phrase_result = await store.search_lecture_ids(
            "база данных", "phrase", None, 10
        )
        assert phrase_result["items"] == [str(lecture_id)]
        reversed_result = await store.search_lecture_ids(
            "данные база", "phrase", None, 10
        )
        assert reversed_result["items"] == []
        phrase = store.client.search(
            index=store.index_name,
            query={"match_phrase": {"content": "база данных"}},
        )
        assert phrase["hits"]["total"]["value"] == 1
        reverse_phrase = store.client.search(
            index=store.index_name,
            query={"match_phrase": {"content": "данные база"}},
        )
        assert reverse_phrase["hits"]["total"]["value"] == 0
    finally:
        if store.client.indices.exists(index=store.index_name):
            store.client.indices.delete(index=store.index_name)
        await store.close()
