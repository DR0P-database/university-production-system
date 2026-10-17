from __future__ import annotations

import httpx
from fastapi.testclient import TestClient


class UnavailableClient:
    def __init__(self):
        self.request_id = None

    async def request(self, method, url, **kwargs):
        self.request_id = kwargs["headers"]["X-Request-ID"]
        request = httpx.Request(method, url)
        raise httpx.ConnectError("service is down", request=request)

    async def aclose(self):
        return None


class OpenAPIClient:
    async def get(self, url):
        host = url.split("//", 1)[-1].split("-service", 1)[0]
        service = "students" if host == "student" else host
        request = httpx.Request("GET", url)
        return httpx.Response(
            200,
            request=request,
            json={
                "openapi": "3.1.0",
                "info": {"title": service, "version": "1.0.0"},
                "paths": {
                    "/health": {
                        "get": {
                            "operationId": "health",
                            "responses": {"200": {"description": "OK"}},
                        }
                    },
                    f"/api/v1/{service}/items": {
                        "get": {
                            "operationId": "list_items",
                            "responses": {"200": {"description": "OK"}},
                        }
                    },
                },
            },
        )

    async def aclose(self):
        return None


def test_gateway_returns_structured_503_and_forwards_request_id(load_app, monkeypatch):
    module = load_app("gateway")
    monkeypatch.setattr(module, "authenticate", lambda request: {"sub": "test"})
    monkeypatch.setattr(module, "authorize", lambda request, claims: None)
    unavailable = UnavailableClient()

    with TestClient(module.app) as client:
        module.app.state.client = unavailable
        response = client.get(
            "/api/v1/academic/universities",
            headers={"X-Request-ID": "gateway-test-request"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert response.json()["error"]["request_id"] == "gateway-test-request"
    assert unavailable.request_id == "gateway-test-request"


def test_gateway_exposes_merged_service_openapi(load_app):
    module = load_app("gateway")

    with TestClient(module.app) as client:
        module.app.state.client = OpenAPIClient()
        response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert list(path for path in schema["paths"] if path == "/health") == ["/health"]
    assert "/api/v1/academic/items" in schema["paths"]
    assert "/api/v1/students/items" in schema["paths"]
    operation = schema["paths"]["/api/v1/academic/items"]["get"]
    assert operation["security"] == [{"BearerAuth": []}]
    assert operation["operationId"] == "academic_list_items"
    assert schema["components"]["securitySchemes"]["BearerAuth"]["scheme"] == "bearer"
