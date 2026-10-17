from __future__ import annotations

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
