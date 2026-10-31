from __future__ import annotations

import importlib
from urllib.parse import urlparse
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient


def uid(number):
    return str(UUID(int=number))


class ReportDependencies:
    def __init__(self, fail=None):
        self.fail = fail
        self.calls = []
        self.group = {
            "id": uid(1),
            "name": "ИВТ-1",
            "specialty_id": uid(2),
            "department_id": uid(3),
            "enrollment_year": 2020,
            "curator": None,
            "created_at": "2020-01-01T00:00:00Z",
            "updated_at": "2020-01-01T00:00:00Z",
        }
        self.students = [
            {
                "id": uid(i + 100),
                "group_id": uid(1),
                "first_name": "Имя",
                "last_name": str(i),
                "patronymic": None,
                "email": None,
                "phone": None,
                "student_card_number": str(i),
                "enrollment_date": "2020-09-01",
                "status": "active",
                "created_at": "2020-01-01T00:00:00Z",
                "updated_at": "2020-01-01T00:00:00Z",
            }
            for i in range(105)
        ]
        self.lessons = [
            {
                "id": uid(10),
                "lecture_id": uid(20),
                "group_id": uid(1),
                "scheduled_date": "2025-09-08",
                "status": "completed",
            },
            {
                "id": uid(11),
                "lecture_id": uid(20),
                "group_id": uid(1),
                "scheduled_date": "2025-09-09",
                "status": "completed",
            },
        ]

    async def get(self, url, *, params, headers):
        self.calls.append((url, params, headers))
        request = httpx.Request("GET", url)
        if self.fail and self.fail in url:
            return httpx.Response(503, request=request)
        p = httpx.QueryParams(params)
        path = urlparse(url).path
        if path.endswith("/search/lectures"):
            assert p["search_mode"] in {"words", "phrase"}
            data = {"items": [uid(20)], "next_cursor": None}
        else:
            if path.endswith("/academic/lectures"):
                rows = [{"id": uid(20), "lecture_type": "lecture"}]
            elif path == "/api/v1/schedule":
                rows = self.lessons
            elif path.endswith("/students/groups"):
                rows = [self.group]
                if p.get("department_id") and p["department_id"] != uid(3):
                    rows = []
            elif path.endswith("/students/students"):
                rows = self.students
            elif path == "/api/v1/attendance":
                rows = [
                    {
                        "schedule_id": uid(10),
                        "student_id": uid(100),
                        "week_start_date": "2025-09-08",
                        "is_present": True,
                    },
                    {
                        "schedule_id": uid(11),
                        "student_id": uid(100),
                        "week_start_date": "2025-09-08",
                        "is_present": True,
                    },
                    {
                        "schedule_id": uid(10),
                        "student_id": uid(101),
                        "week_start_date": "2025-09-08",
                        "is_present": True,
                    },
                ]
            else:
                raise AssertionError(path)
            offset, limit = int(p["offset"]), int(p["limit"])
            data = {"items": rows[offset : offset + limit], "total": len(rows)}
        return httpx.Response(200, request=request, json=data)


def report_query(**overrides):
    return {
        "term": "базы данных",
        "date_from": "2025-09-08",
        "date_to": "2025-09-09",
        **overrides,
    }


def test_report_ranks_all_students_before_limit_and_counts_missing_as_absent(load_app):
    module = load_app("services/report-service")
    dependency = ReportDependencies()
    with TestClient(module.app) as client:
        module.app.state.client = dependency
        response = client.get(
            "/api/v1/reports/attendance/lowest",
            params=report_query(),
            headers={"X-Request-ID": "example"},
        )
    assert response.status_code == 200
    report = response.json()
    assert report["term"] == "базы данных"
    assert report["search_mode"] == "words"
    assert len(report["items"]) == 10
    assert [item["student"]["id"] for item in report["items"]] == [
        uid(i) for i in range(102, 112)
    ]
    assert all(
        item["attendance_percent"] == 0 and item["lecture_count"] == 2
        for item in report["items"]
    )
    assert any(
        "offset=100" in str(httpx.QueryParams(params))
        for _, params, _ in dependency.calls
    )
    assert all(
        headers["X-Request-ID"] == "example" for _, _, headers in dependency.calls
    )


def test_report_percentage_phrase_filter_and_dependency_failure(load_app):
    module = load_app("services/report-service")
    dependency = ReportDependencies()
    dependency.students = dependency.students[:2]
    with TestClient(module.app) as client:
        module.app.state.client = dependency
        response = client.get(
            "/api/v1/reports/attendance/lowest",
            params=report_query(search_mode="phrase"),
        )
        assert response.status_code == 200
        assert [x["attendance_percent"] for x in response.json()["items"]] == [50, 100]
        module.app.state.client = ReportDependencies(fail="attendance")
        assert (
            client.get(
                "/api/v1/reports/attendance/lowest", params=report_query()
            ).status_code
            == 503
        )
        assert (
            client.get(
                "/api/v1/reports/attendance/lowest",
                params=report_query(date_from="2026-01-01"),
            ).status_code
            == 422
        )


@pytest.mark.asyncio
async def test_search_mode_uses_phrase_or_all_tokens(load_app, monkeypatch):
    load_app("services/academic-service")
    module = importlib.import_module("app.search_store")
    store = module.LectureDocumentSearchStore()
    calls = []

    async def ensure():
        return None

    def search(**kwargs):
        calls.append(kwargs)
        return {"aggregations": {"lectures": {"buckets": []}}}

    monkeypatch.setattr(store, "ensure_index", ensure)
    monkeypatch.setattr(store.client, "search", search)
    try:
        await store.search_lecture_ids("базы данных", "words", None, 100)
        await store.search_lecture_ids("базы данных", "phrase", None, 100)
    finally:
        await store.close()
    assert calls[0]["query"]["match"]["content"]["operator"] == "and"
    assert calls[1]["query"] == {"match_phrase": {"content": {"query": "базы данных"}}}


def test_report_rejects_mismatched_attendance_week(load_app):
    module = load_app("services/report-service")
    dependency = ReportDependencies()
    original_get = dependency.get

    async def invalid_week(url, **kwargs):
        response = await original_get(url, **kwargs)
        if urlparse(url).path == "/api/v1/attendance":
            data = response.json()
            data["items"][0]["week_start_date"] = "2025-09-01"
            return httpx.Response(200, request=response.request, json=data)
        return response

    dependency.get = invalid_week
    with TestClient(module.app) as client:
        module.app.state.client = dependency
        response = client.get(
            "/api/v1/reports/attendance/lowest", params=report_query()
        )
    assert response.status_code == 503


def test_attendance_rejects_week_different_from_schedule(load_app):
    module = load_app("services/attendance-service")
    with pytest.raises(module.HTTPException) as error:
        module.validate_schedule_week(
            {"scheduled_date": "2025-09-09"},
            module.date(2025, 9, 1),
        )
    assert error.value.status_code == 400
    assert error.value.detail["code"] == "ATTENDANCE_WEEK_MISMATCH"
