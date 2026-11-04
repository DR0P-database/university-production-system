from uuid import UUID

import httpx
from fastapi.testclient import TestClient


def test_capacity_counts_active_cohort_and_filters_requirements(load_app):
    module = load_app("services/room-report-service")
    course_id = str(UUID(int=1))
    calls = []

    def handler(request):
        calls.append(request)
        path = request.url.path
        if path.endswith("/courses/" + course_id):
            return httpx.Response(
                200, json={"id": course_id, "semester": 1, "specialty_id": course_id}
            )
        if path.endswith("/groups"):
            assert request.url.params["enrollment_year"] == "2026"
            rows = [{"id": course_id}]
        elif path.endswith("/students"):
            assert request.url.params["status"] == "active"
            rows = [{"id": "a"}, {"id": "b"}]
        else:
            rows = [
                {"id": course_id, "order_number": 1, "requirements": "Проектор"},
                {"id": "other", "order_number": 2, "requirements": None},
            ]
        return httpx.Response(200, json={"items": rows, "total": len(rows)})

    with TestClient(module.app) as client:
        module.app.state.client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )
        query = dict(course_id=course_id, semester=1, study_year=1, academic_year=2026)
        response = client.get("/api/v1/reports/capacity", params=query)
        assert response.status_code == 200
        assert response.json()["required_seats"] == 2
        assert len(response.json()["items"]) == 1
        response = client.get(
            "/api/v1/reports/capacity",
            params={**query, "equipment_term": "микроскоп"},
        )
        assert response.json()["items"] == []
        assert response.json()["required_seats"] == 0
        assert (
            client.get(
                "/api/v1/reports/capacity", params={**query, "study_year": 2}
            ).status_code
            == 422
        )
        module.app.state.client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(503))
        )
        assert client.get("/api/v1/reports/capacity", params=query).status_code == 503


def test_scheduled_courses_excludes_cancelled_and_filters_year(load_app):
    module = load_app("services/room-report-service")

    def handler(request):
        path = request.url.path
        if path == "/api/v1/schedule":
            assert request.url.params["date_from"] == "2026-01-01"
            assert request.url.params["date_to"] == "2026-12-31"
            rows = [
                dict(lecture_id="a", status="completed", scheduled_date="2026-09-01"),
                dict(lecture_id="b", status="cancelled", scheduled_date="2026-09-02"),
            ]
        elif path.endswith("/lectures"):
            assert request.url.params.get_list("ids") == ["a"]
            rows = [dict(id="a", course_id="course")]
        else:
            return httpx.Response(200, json=dict(id="course", name="Test", semester=1))
        return httpx.Response(200, json={"items": rows, "total": len(rows)})

    with TestClient(module.app) as client:
        module.app.state.client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )
        response = client.get("/api/v1/reports/courses", params={"year": 2026})
        assert response.status_code == 200
        assert response.json()["items"][0]["scheduled_lesson_count"] == 1
        assert (
            client.get(
                "/api/v1/reports/courses", params={"year": 2026, "study_year": 2}
            ).json()["items"]
            == []
        )
        assert (
            client.get(
                "/api/v1/reports/courses",
                params={"year": 2026, "study_year": 2, "semester": 1},
            ).status_code
            == 422
        )


def test_course_filters_are_declared_in_openapi(load_app):
    module = load_app("services/academic-service")
    parameters = module.app.openapi()["paths"]["/api/v1/academic/courses"]["get"][
        "parameters"
    ]
    names = {parameter["name"] for parameter in parameters}
    assert {"semester", "study_year", "specialty_id", "limit", "offset"} <= names
