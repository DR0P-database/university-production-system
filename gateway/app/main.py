from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, Response, Security
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from app.auth import (
    LoginRequest,
    TokenResponse,
    authenticate_account,
    create_access_token,
    require_access_token,
)
from app.openapi import fetch_service_schemas, merge_openapi_schemas
from app.request_id import REQUEST_ID_HEADER, get_request_id, request_id_middleware

SERVICE_PREFIXES = {
    "academic": os.getenv("ACADEMIC_SERVICE_URL", "http://academic-service:8000"),
    "students": os.getenv("STUDENT_SERVICE_URL", "http://student-service:8000"),
    "schedule": os.getenv("SCHEDULE_SERVICE_URL", "http://schedule-service:8000"),
    "attendance": os.getenv("ATTENDANCE_SERVICE_URL", "http://attendance-service:8000"),
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    timeout = float(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "5"))
    app.state.client = httpx.AsyncClient(timeout=timeout)
    app.state.merged_openapi = None
    yield
    await app.state.client.aclose()


app = FastAPI(
    title="University API Gateway",
    version="1.0.0",
    lifespan=lifespan,
    openapi_url=None,
    docs_url=None,
    redoc_url=None,
)
app.middleware("http")(request_id_middleware)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    detail = (
        exc.detail
        if isinstance(exc.detail, dict)
        else {"code": "HTTP_ERROR", "message": str(exc.detail), "details": {}}
    )
    detail.setdefault("request_id", get_request_id())
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": detail},
        headers=exc.headers,
    )


@app.get("/health", tags=["system"], summary="Gateway health check")
async def health() -> dict[str, str]:
    """Return the health status of the gateway."""
    return {"status": "ok"}


@app.post("/api/v1/auth/token", response_model=TokenResponse, tags=["auth"])
async def issue_token(payload: LoginRequest) -> TokenResponse:
    """Authenticate a configured account and issue a short-lived access token."""
    account = authenticate_account(payload.username, payload.password)
    return create_access_token(account)


@app.get("/openapi.json", include_in_schema=False)
async def openapi_schema(request: Request) -> JSONResponse:
    """Return one public contract assembled from all internal services."""
    if request.app.state.merged_openapi is None:
        try:
            service_schemas = await fetch_service_schemas(
                request.app.state.client, SERVICE_PREFIXES
            )
            request.app.state.merged_openapi = merge_openapi_schemas(
                request.app.routes, service_schemas
            )
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(
                503,
                {
                    "code": "OPENAPI_UNAVAILABLE",
                    "message": "Unable to assemble the API documentation",
                    "details": {"reason": str(exc)},
                },
            ) from exc
    return JSONResponse(request.app.state.merged_openapi)


@app.get("/docs", include_in_schema=False)
async def swagger_ui() -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="University API Gateway - Swagger UI",
    )


@app.get("/redoc", include_in_schema=False)
async def redoc() -> HTMLResponse:
    return get_redoc_html(
        openapi_url="/openapi.json",
        title="University API Gateway - ReDoc",
    )


@app.api_route(
    "/api/v1/{service}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    dependencies=[Security(require_access_token)],
    include_in_schema=False,
)
async def proxy(service: str, path: str, request: Request) -> Response:
    """Forward an authenticated API request to an internal service."""
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
