from __future__ import annotations

from fastapi.testclient import TestClient


def test_every_app_exposes_health_and_request_id(load_app):
    for path in (
        "gateway",
        "services/academic-service",
        "services/student-service",
        "services/schedule-service",
        "services/attendance-service",
    ):
        module = load_app(path)
        with TestClient(module.app) as client:
            response = client.get("/health", headers={"X-Request-ID": "test-request"})
        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == "test-request"


def test_collection_endpoints_document_pagination(load_app):
    cases = {
        "services/academic-service": (
            "/api/v1/academic/universities",
            "/api/v1/academic/institutes",
            "/api/v1/academic/departments",
            "/api/v1/academic/specialties",
            "/api/v1/academic/courses",
            "/api/v1/academic/lectures",
            "/api/v1/academic/materials",
            "/api/v1/academic/departments/{department_id}/specialties",
            "/api/v1/academic/lectures/{lecture_id}/materials",
        ),
        "services/student-service": (
            "/api/v1/students/groups",
            "/api/v1/students/students",
            "/api/v1/students/groups/{group_id}/students",
        ),
        "services/schedule-service": (
            "/api/v1/schedule",
            "/api/v1/schedule/groups/{group_id}",
        ),
        "services/attendance-service": (
            "/api/v1/attendance",
            "/api/v1/attendance/schedules/{schedule_id}",
            "/api/v1/attendance/students/{student_id}",
        ),
    }

    for service, paths in cases.items():
        schema = load_app(service).app.openapi()
        for path in paths:
            parameters = {
                parameter["name"]
                for parameter in schema["paths"][path]["get"]["parameters"]
            }
            assert {"limit", "offset"} <= parameters, (service, path)


def test_schedule_documents_date_range_and_rejects_invalid_range(load_app):
    module = load_app("services/schedule-service")
    operation = module.app.openapi()["paths"]["/api/v1/schedule"]["get"]
    parameters = {parameter["name"] for parameter in operation["parameters"]}
    assert {"date_from", "date_to"} <= parameters

    with TestClient(module.app) as client:
        response = client.get(
            "/api/v1/schedule?date_from=2026-10-17&date_to=2026-10-01"
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_DATE_RANGE"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_attendance_history_documents_and_validates_date_range(load_app):
    module = load_app("services/attendance-service")
    path = "/api/v1/attendance/students/{student_id}"
    operation = module.app.openapi()["paths"][path]["get"]
    parameters = {parameter["name"] for parameter in operation["parameters"]}
    assert {"date_from", "date_to"} <= parameters

    student_id = "00000000-0000-0000-0000-000000000202"
    with TestClient(module.app) as client:
        response = client.get(
            f"/api/v1/attendance/students/{student_id}"
            "?date_from=2026-10-17&date_to=2026-10-01"
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_DATE_RANGE"


def test_manual_payload_validation_is_a_structured_422(load_app):
    module = load_app("services/schedule-service")
    payload = {
        "lecture_id": "00000000-0000-0000-0000-000000000106",
        "group_id": "00000000-0000-0000-0000-000000000201",
        "scheduled_date": "2026-10-14",
        "week_start_date": "2026-10-12",
        "start_time": "11:30:00",
        "end_time": "10:00:00",
    }
    with TestClient(module.app) as client:
        response = client.post("/api/v1/schedule", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
