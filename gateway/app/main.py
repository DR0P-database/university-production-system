from __future__ import annotations

import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response

SERVICE_PREFIXES = {
    "academic": os.getenv("ACADEMIC_SERVICE_URL", "http://academic-service:8000"),
    "students": os.getenv("STUDENT_SERVICE_URL", "http://student-service:8000"),
    "schedule": os.getenv("SCHEDULE_SERVICE_URL", "http://schedule-service:8000"),
    "attendance": os.getenv("ATTENDANCE_SERVICE_URL", "http://attendance-service:8000"),
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(timeout=30.0)
    yield
    await app.state.client.aclose()


app = FastAPI(title="University API Gateway", version="1.0.0", lifespan=lifespan)


@app.get("/health", tags=["system"], summary="Gateway health check")
async def health() -> dict[str, str]:
    """Return the health status of the gateway."""
    return {"status": "ok"}


@app.api_route(
    "/api/v1/{service}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
async def proxy(service: str, path: str, request: Request) -> Response:
    """Forward an API request to the selected internal service."""
    base_url = SERVICE_PREFIXES.get(service)
    if base_url is None:
        return Response(status_code=404, content="Unknown service")
    upstream = f"{base_url}/api/v1/{service}/{path}"
    response = await request.app.state.client.request(
        request.method,
        upstream,
        params=request.query_params,
        content=await request.body(),
        headers={
            "content-type": request.headers.get("content-type", "application/json")
        },
    )
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers={
            "content-type": response.headers.get("content-type", "application/json")
        },
    )
