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
