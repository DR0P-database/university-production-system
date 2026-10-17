from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.api import router
from app.request_id import get_request_id, request_id_middleware

app = FastAPI(
    title="Academic Service",
    version="1.0.0",
    description="University academic data API",
)
app.include_router(router)
app.middleware("http")(request_id_middleware)


def error_body(code: str, message: str, details: object = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": jsonable_encoder(details or {}),
            "request_id": get_request_id(),
        }
    }


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_body(
            "VALIDATION_ERROR", "Request validation failed", exc.errors()
        ),
    )


@app.exception_handler(ValidationError)
async def pydantic_validation_error(_: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_body(
            "VALIDATION_ERROR", "Request validation failed", exc.errors()
        ),
    )


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    detail = (
        exc.detail
        if isinstance(exc.detail, dict)
        else {"code": "HTTP_ERROR", "message": str(exc.detail), "details": {}}
    )
    detail.setdefault("request_id", get_request_id())
    return JSONResponse(status_code=exc.status_code, content={"error": detail})


@app.exception_handler(IntegrityError)
async def integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
    text = str(exc.orig).lower()
    code = (
        "SPECIALTY_CODE_ALREADY_EXISTS"
        if "specialties_code" in text
        else "DATA_CONFLICT"
    )
    return JSONResponse(
        status_code=409,
        content=error_body(code, "Resource conflicts with existing data"),
    )


@app.get("/health", tags=["system"], summary="Health check")
async def health() -> dict[str, str]:
    """Return the health status of the academic service."""
    return {"status": "ok"}
