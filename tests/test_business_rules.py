from __future__ import annotations

import sys
from datetime import date
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

LECTURE_ID = "00000000-0000-0000-0000-000000000106"
GROUP_ID = "00000000-0000-0000-0000-000000000201"
OTHER_GROUP_ID = "00000000-0000-0000-0000-000000000211"
SCHEDULE_ID = "00000000-0000-0000-0000-000000000301"
STUDENT_ID = "00000000-0000-0000-0000-000000000202"


class EmptyResult:
    def first(self):
        return None

    def all(self):
        return []


class FakeSession:
    def __init__(self, existing=None):
        self.existing = existing
        self.added = []
        self.commits = 0

    def add(self, row):
        self.added.append(row)

    async def scalar(self, query):
        return 0

    async def scalars(self, query):
        if self.existing is None:
            return EmptyResult()

        existing = self.existing

        class ExistingResult:
            def first(self):
                return existing

            def all(self):
                return [existing]

        return ExistingResult()

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def refresh(self, row):
        return None


class ConflictSession(FakeSession):
    async def commit(self):
        raise IntegrityError(
            "INSERT INTO student_groups",
            {},
            RuntimeError("uq_student_groups_name"),
        )


def override_session(app, dependency, session):
    async def override():
        yield session

    app.dependency_overrides[dependency] = override


async def test_department_specialty_list_keeps_department_filter(load_app):
    load_app("services/academic-service")
    api_module = sys.modules["app.api"]

    class QuerySession(FakeSession):
        selected = None

        async def scalars(self, query):
            self.selected = query
            return EmptyResult()

    session = QuerySession()
    department_id = UUID("00000000-0000-0000-0000-000000000103")

    await api_module.list_rows(
        api_module.DepartmentSpecialty,
        session,
        {"department_id": department_id},
        0,
        50,
    )

    assert session.selected is not None
    assert "department_specialties.department_id" in str(session.selected.whereclause)


def test_schedule_rejects_specialty_mismatch_before_writing(load_app, monkeypatch):
    module = load_app("services/schedule-service")
    session = FakeSession()
    override_session(module.app, module.get_session, session)

    async def fetch(service, path, item_id):
        if "lectures" in path:
            return {"course_id": "00000000-0000-0000-0000-000000000105"}
        if "courses" in path:
            return {"specialty_id": "00000000-0000-0000-0000-000000000104"}
        return {"specialty_id": "00000000-0000-0000-0000-000000000114"}

    monkeypatch.setattr(module, "fetch_json", fetch)
    payload = {
        "lecture_id": LECTURE_ID,
        "group_id": OTHER_GROUP_ID,
        "scheduled_date": "2026-10-14",
        "week_start_date": "2026-10-12",
        "start_time": "10:00:00",
        "end_time": "11:30:00",
    }
    with TestClient(module.app) as client:
        response = client.post("/api/v1/schedule", json=payload)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SPECIALTY_MISMATCH"
    assert session.added == []
    assert session.commits == 0


def test_schedule_returns_404_for_missing_lecture(load_app, monkeypatch):
    module = load_app("services/schedule-service")
    session = FakeSession()
    override_session(module.app, module.get_session, session)

    async def fetch(service, path, item_id):
        raise module.api_error(
            404, "LECTURE_NOT_FOUND", "Referenced lecture does not exist"
        )

    monkeypatch.setattr(module, "fetch_json", fetch)
    payload = {
        "lecture_id": LECTURE_ID,
        "group_id": GROUP_ID,
        "scheduled_date": "2026-10-14",
        "week_start_date": "2026-10-12",
        "start_time": "10:00:00",
        "end_time": "11:30:00",
    }
    with TestClient(module.app) as client:
        response = client.post("/api/v1/schedule", json=payload)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "LECTURE_NOT_FOUND"
    assert session.added == []


def test_schedule_returns_404_for_missing_group(load_app, monkeypatch):
    module = load_app("services/schedule-service")
    session = FakeSession()
    override_session(module.app, module.get_session, session)

    async def fetch(service, path, item_id):
        if "lectures" in path:
            return {"course_id": "00000000-0000-0000-0000-000000000105"}
        if "courses" in path:
            return {"specialty_id": "00000000-0000-0000-0000-000000000104"}
        raise module.api_error(
            404, "GROUP_NOT_FOUND", "Referenced group does not exist"
        )

    monkeypatch.setattr(module, "fetch_json", fetch)
    payload = {
        "lecture_id": LECTURE_ID,
        "group_id": GROUP_ID,
        "scheduled_date": "2026-10-14",
        "week_start_date": "2026-10-12",
        "start_time": "10:00:00",
        "end_time": "11:30:00",
    }
    with TestClient(module.app) as client:
        response = client.post("/api/v1/schedule", json=payload)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "GROUP_NOT_FOUND"
    assert session.added == []


def test_attendance_batch_does_not_partially_write_on_group_mismatch(
    load_app, monkeypatch
):
    module = load_app("services/attendance-service")
    session = FakeSession()
    override_session(module.app, module.get_session, session)

    async def fetch(service, path, item_id):
        if service == "schedule":
            return {"group_id": GROUP_ID}
        group_id = GROUP_ID if str(item_id) == STUDENT_ID else OTHER_GROUP_ID
        return {"group_id": group_id}

    monkeypatch.setattr(module, "fetch_json", fetch)
    payload = [
        {
            "student_id": STUDENT_ID,
            "week_start_date": "2026-10-12",
            "is_present": True,
        },
        {
            "student_id": "00000000-0000-0000-0000-000000000212",
            "week_start_date": "2026-10-12",
            "is_present": True,
        },
    ]
    with TestClient(module.app) as client:
        response = client.put(
            f"/api/v1/attendance/schedules/{SCHEDULE_ID}", json=payload
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "STUDENT_NOT_IN_SCHEDULE_GROUP"
    assert session.added == []
    assert session.commits == 0


def test_repeated_attendance_updates_existing_record(load_app, monkeypatch):
    module = load_app("services/attendance-service")
    existing = module.Attendance(
        id=UUID("00000000-0000-0000-0000-000000000401"),
        schedule_id=UUID(SCHEDULE_ID),
        student_id=UUID(STUDENT_ID),
        week_start_date=date(2026, 10, 12),
        is_present=False,
    )
    session = FakeSession(existing=existing)
    override_session(module.app, module.get_session, session)

    async def fetch(service, path, item_id):
        return {"group_id": GROUP_ID}

    monkeypatch.setattr(module, "fetch_json", fetch)
    payload = {"week_start_date": "2026-10-12", "is_present": True}
    with TestClient(module.app) as client:
        response = client.put(
            f"/api/v1/attendance/schedules/{SCHEDULE_ID}/students/{STUDENT_ID}",
            json=payload,
        )

    assert response.status_code == 200
    assert response.json()["is_present"] is True
    assert session.added == []
    assert session.commits == 1


def test_student_lookup_by_card_returns_cached_student(load_app, monkeypatch):
    module = load_app("services/student-service")
    session = FakeSession()
    override_session(module.app, module.get_session, session)
    cached_student = {
        "id": STUDENT_ID,
        "group_id": GROUP_ID,
        "first_name": "Иван",
        "last_name": "Иванов",
        "patronymic": "Иванович",
        "email": "seed.student.0001@example.edu",
        "phone": "+79990000001",
        "student_card_number": "SEED-000001",
        "enrollment_date": "2026-09-01",
        "status": "active",
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
    }

    async def cache_get(student_card_number):
        assert student_card_number == "SEED-000001"
        return cached_student

    monkeypatch.setattr(module, "get_cached_student", cache_get)
    with TestClient(module.app) as client:
        response = client.get("/api/v1/students/students/by-card/SEED-000001")

    assert response.status_code == 200
    assert response.headers["X-Cache"] == "HIT"
    assert response.json() == cached_student


def test_student_lookup_falls_back_to_postgres_and_populates_cache(
    load_app, monkeypatch
):
    module = load_app("services/student-service")
    existing = module.Student(
        id=UUID(STUDENT_ID),
        group_id=UUID(GROUP_ID),
        first_name="Иван",
        last_name="Иванов",
        patronymic="Иванович",
        email="seed.student.0001@example.edu",
        phone="+79990000001",
        student_card_number="SEED-000001",
        enrollment_date=date(2026, 9, 1),
        status="active",
    )
    session = FakeSession(existing=existing)
    override_session(module.app, module.get_session, session)
    cached = {}

    async def cache_get(_student_card_number):
        return None

    async def cache_set(student):
        cached.update(student)

    monkeypatch.setattr(module, "get_cached_student", cache_get)
    monkeypatch.setattr(module, "cache_student", cache_set)
    with TestClient(module.app) as client:
        response = client.get("/api/v1/students/students/by-card/SEED-000001")

    assert response.status_code == 200
    assert response.headers["X-Cache"] == "MISS"
    assert response.json()["id"] == STUDENT_ID
    assert cached["student_card_number"] == "SEED-000001"


def test_graph_read_reports_unavailable_projection(load_app, monkeypatch):
    module = load_app("services/academic-service")
    graph_module = sys.modules["app.academic_graph"]

    async def unavailable():
        raise graph_module.GraphUnavailable("test")

    monkeypatch.setattr(module.academic_graph, "stats", unavailable)
    with TestClient(module.app) as client:
        response = client.get("/api/v1/academic/graph/stats")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "GRAPH_UNAVAILABLE"


def test_document_search_returns_elasticsearch_projection(load_app, monkeypatch):
    module = load_app("services/academic-service")
    lecture_id = "00000000-0000-0000-0000-000000000106"
    material_id = "00000000-0000-0000-0000-000000000107"

    async def search(query, **options):
        assert query == "нормализация"
        assert options["document_type"] == "material"
        return {
            "items": [
                {
                    "document_id": f"material:{material_id}",
                    "document_type": "material",
                    "lecture_id": lecture_id,
                    "material_id": material_id,
                    "content_type": "text",
                    "content": "Нормализация данных",
                    "score": 1.5,
                }
            ],
            "limit": options["limit"],
            "offset": options["offset"],
            "total": 1,
        }

    monkeypatch.setattr(module.search_store, "search", search)
    with TestClient(module.app) as client:
        response = client.get(
            "/api/v1/academic/search/documents",
            params={"q": "нормализация", "document_type": "material"},
        )

    assert response.status_code == 200
    assert response.json()["items"][0]["material_id"] == material_id


def test_graph_stats_are_returned_for_bootstrap_verification(load_app, monkeypatch):
    module = load_app("services/academic-service")

    async def stats():
        return {
            "universities": 2,
            "institutes": 4,
            "departments": 8,
            "specialties": 8,
            "groups": 34,
            "students": 1000,
            "schedules": 408,
            "relationships": 1496,
        }

    monkeypatch.setattr(module.academic_graph, "stats", stats)
    with TestClient(module.app) as client:
        response = client.get("/api/v1/academic/graph/stats")

    assert response.status_code == 200
    assert response.json() == {
        "universities": 2,
        "institutes": 4,
        "departments": 8,
        "specialties": 8,
        "groups": 34,
        "students": 1000,
        "schedules": 408,
        "relationships": 1496,
    }


async def test_student_cache_uses_24_hour_default_ttl(load_app, monkeypatch):
    load_app("services/student-service")
    cache_module = sys.modules["app.student_cache"]
    written = {}

    class FakeRedis:
        async def set(self, key, value, *, ex):
            written.update(key=key, value=value, ex=ex)

    monkeypatch.setenv("REDIS_ENABLED", "true")
    monkeypatch.delenv("STUDENT_CACHE_TTL_SECONDS", raising=False)
    monkeypatch.setattr(cache_module, "_client", FakeRedis())

    await cache_module.cache_student(
        {"id": STUDENT_ID, "student_card_number": "SEED-000001"}
    )

    assert written["key"] == "student:card:SEED-000001"
    assert written["ex"] == 86400


def test_unique_group_name_conflict_returns_409(load_app, monkeypatch):
    module = load_app("services/student-service")
    session = ConflictSession()
    override_session(module.app, module.get_session, session)

    async def exists(service, path, item_id):
        return None

    monkeypatch.setattr(module, "require_exists", exists)
    payload = {
        "specialty_id": "00000000-0000-0000-0000-000000000104",
        "department_id": "00000000-0000-0000-0000-000000000103",
        "name": "SEED-U1-G01",
        "enrollment_year": 2026,
    }
    with TestClient(module.app) as client:
        response = client.post("/api/v1/students/groups", json=payload)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GROUP_NAME_ALREADY_EXISTS"
