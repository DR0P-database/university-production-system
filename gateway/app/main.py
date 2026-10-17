from __future__ import annotations

import os
from contextlib import asynccontextmanager

import httpx
from app.auth import authenticate, authorize
from app.request_id import REQUEST_ID_HEADER, get_request_id, request_id_middleware
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

SERVICE_PREFIXES = {
    "academic": os.getenv("ACADEMIC_SERVICE_URL", "http://academic-service:8000"),
    "students": os.getenv("STUDENT_SERVICE_URL", "http://student-service:8000"),
    "schedule": os.getenv("SCHEDULE_SERVICE_URL", "http://schedule-service:8000"),
    "attendance": os.getenv("ATTENDANCE_SERVICE_URL", "http://attendance-service:8000"),
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    timeout = float(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "5"))
    app.state.client = httpx.AsyncClient(timeout=timeout)
    yield
    await app.state.client.aclose()


app = FastAPI(title="University API Gateway", version="1.0.0", lifespan=lifespan)
app.middleware("http")(request_id_middleware)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    detail = (
        exc.detail
        if isinstance(exc.detail, dict)
        else {"code": "HTTP_ERROR", "message": str(exc.detail), "details": {}}
    )
    detail.setdefault("request_id", get_request_id())
    return JSONResponse(status_code=exc.status_code, content={"error": detail})


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
    claims = authenticate(request)
    authorize(request, claims)
    base_url = SERVICE_PREFIXES.get(service)
    if base_url is None:
        raise HTTPException(
            404,
            {
                "code": "SERVICE_NOT_FOUND",
                "message": "Unknown service",
                "details": {"service": service},
            },
        )
    upstream = f"{base_url}/api/v1/{service}/{path}"
    try:
        response = await request.app.state.client.request(
            request.method,
            upstream,
            params=request.query_params,
            content=await request.body(),
            headers={
                "content-type": request.headers.get("content-type", "application/json"),
                "authorization": request.headers.get("authorization", ""),
                REQUEST_ID_HEADER: get_request_id(),
            },
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            503,
            {
                "code": "UPSTREAM_TIMEOUT",
                "message": f"{service} service timed out",
                "details": {"service": service},
            },
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            503,
            {
                "code": "DEPENDENCY_UNAVAILABLE",
                "message": f"{service} service is unavailable",
                "details": {"service": service},
            },
        ) from exc
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers={
            "content-type": response.headers.get("content-type", "application/json"),
            REQUEST_ID_HEADER: get_request_id(),
        },
    )
