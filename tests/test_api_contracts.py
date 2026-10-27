from __future__ import annotations

import importlib

from fastapi.testclient import TestClient
from sqlalchemy.inspection import inspect


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
            "/api/v1/academic/search/documents",
            "/api/v1/academic/departments/{department_id}/specialties",
            "/api/v1/academic/lectures/{lecture_id}/materials",
        ),
        "services/student-service": (
            "/api/v1/students/groups",
            "/api/v1/students/students",
            "/api/v1/students/groups/{group_id}/students",
            "/api/v1/students/graph/universities/{university_id}/students",
        ),
        "services/schedule-service": (
            "/api/v1/schedule",
            "/api/v1/schedule/groups/{group_id}",
            "/api/v1/schedule/students/{student_id}",
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


def test_student_card_lookup_is_exposed_before_uuid_route(load_app):
    module = load_app("services/student-service")
    paths = list(module.app.openapi()["paths"])

    lookup = "/api/v1/students/students/by-card/{student_card_number}"
    by_id = "/api/v1/students/students/{item_id}"
    assert lookup in paths
    assert paths.index(lookup) < paths.index(by_id)


def test_graph_diagnostics_are_exposed(load_app):
    module = load_app("services/academic-service")

    paths = module.app.openapi()["paths"]
    assert "/api/v1/academic/graph/stats" in paths
    assert "/api/v1/academic/graph/universities/{university_id}" in paths

    student_paths = load_app("services/student-service").app.openapi()["paths"]
    assert (
        "/api/v1/students/graph/universities/{university_id}/students" in student_paths
    )
    assert "/api/v1/students/graph/students/{student_id}" in student_paths

    schedule_paths = load_app("services/schedule-service").app.openapi()["paths"]
    assert "/api/v1/schedule/students/{student_id}" in schedule_paths


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


def test_material_content_is_not_mapped_to_postgresql(load_app):
    load_app("services/academic-service")
    models = importlib.import_module("app.models")
    columns = {
        column.key for column in inspect(models.LectureMaterial).mapper.column_attrs
    }

    assert "content_ref" in columns
    assert "content_text" not in columns
    assert "metadata_json" not in columns


def test_document_search_projection_contains_only_document_fields(load_app):
    load_app("services/academic-service")
    search_store = importlib.import_module("app.search_store")

    assert set(search_store.LECTURE_DOCUMENT_INDEX_PROPERTIES) == {
        "document_type",
        "lecture_id",
        "material_id",
        "content_type",
        "content",
    }


def test_document_search_has_typed_openapi_response(load_app):
    schema = load_app("services/academic-service").app.openapi()
    operation = schema["paths"]["/api/v1/academic/search/documents"]["get"]
    parameters = {parameter["name"] for parameter in operation["parameters"]}
    response = operation["responses"]["200"]["content"]["application/json"]["schema"]

    assert {
        "q",
        "document_type",
        "lecture_id",
        "content_type",
        "limit",
        "offset",
    } <= parameters
    assert response["$ref"].endswith("/SearchDocumentPage")


def test_material_openapi_has_composed_response_schema(load_app):
    module = load_app("services/academic-service")
    schema = module.app.openapi()
    material = schema["components"]["schemas"]["MaterialResponse"]

    assert {"id", "lecture_id", "content_text", "metadata_json"} <= set(
        material["properties"]
    )
    assert "content_ref" not in material["properties"]
    response = schema["paths"]["/api/v1/academic/materials/{item_id}"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    assert response["$ref"].endswith("/MaterialResponse")
    create_body = schema["paths"]["/api/v1/academic/materials"]["post"]["requestBody"][
        "content"
    ]["application/json"]["schema"]
    update_body = schema["paths"]["/api/v1/academic/materials/{item_id}"]["patch"][
        "requestBody"
    ]["content"]["application/json"]["schema"]
    assert create_body["$ref"].endswith("/MaterialCreate")
    assert update_body["$ref"].endswith("/MaterialUpdate")


def test_neo4j_projection_ownership_is_split_by_domain(load_app):
    load_app("services/academic-service")
    graph = importlib.import_module("app.academic_graph")

    assert {config[0] for config in graph.ENTITY_CONFIG.values()} == {
        "University",
        "Institute",
        "Department",
        "Specialty",
    }

    load_app("services/student-service")
    student_graph = importlib.import_module("app.graph_store")
    assert hasattr(student_graph, "StudentGraphStore")

    load_app("services/schedule-service")
    schedule_graph = importlib.import_module("app.graph_store")
    assert hasattr(schedule_graph, "ScheduleGraphStore")

    attendance = load_app("services/attendance-service")
    paths = attendance.app.openapi()["paths"]
    assert all("/graph/" not in path for path in paths)
