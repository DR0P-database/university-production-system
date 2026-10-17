from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

import httpx
import jwt
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


class RecordingClient:
    def __init__(self):
        self.headers = None

    async def request(self, method, url, **kwargs):
        self.headers = kwargs["headers"]
        return httpx.Response(
            200,
            request=httpx.Request(method, url),
            json={"status": "forwarded"},
        )

    async def aclose(self):
        return None


def test_gateway_returns_structured_503_and_forwards_request_id(load_app):
    module = load_app("gateway")
    module.app.dependency_overrides[module.require_access_token] = lambda: None
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


def test_token_allows_any_gateway_api_operation(load_app):
    module = load_app("gateway")
    upstream = RecordingClient()

    with TestClient(module.app) as client:
        module.app.state.client = upstream
        login = client.post(
            "/api/v1/auth/token",
            json={"username": "api-user", "password": "api-password"},
        )
        token = login.json()["access_token"]
        response = client.post(
            "/api/v1/students/students",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )

    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"
    assert response.status_code == 200
    assert "authorization" not in upstream.headers


def test_missing_token_is_rejected(load_app):
    module = load_app("gateway")

    with TestClient(module.app) as client:
        response = client.get("/api/v1/students/students")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_expired_token_is_rejected(load_app):
    module = load_app("gateway")
    auth = sys.modules["app.auth"]
    now = datetime.now(UTC)
    payload = {
        "sub": "expired-user",
        "type": "access",
        "iss": auth.settings.jwt_issuer,
        "aud": auth.settings.jwt_audience,
        "iat": now - timedelta(hours=2),
        "nbf": now - timedelta(hours=2),
        "exp": now - timedelta(hours=1),
        "jti": "expired-token-id",
    }
    token = jwt.encode(
        payload,
        auth.settings.jwt_secret.get_secret_value(),
        algorithm=auth.settings.jwt_algorithm,
    )

    with TestClient(module.app) as client:
        response = client.get(
            "/api/v1/schedule", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_invalid_credentials_are_rejected(load_app):
    module = load_app("gateway")

    with TestClient(module.app) as client:
        response = client.post(
            "/api/v1/auth/token",
            json={"username": "api-user", "password": "wrong-password"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
