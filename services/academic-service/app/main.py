from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api import router

app = FastAPI(
    title="Academic Service",
    version="1.0.0",
    description="University academic data API",
)
app.include_router(router)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": exc.errors(),
            }
        },
    )


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    detail = (
        exc.detail
        if isinstance(exc.detail, dict)
        else {"code": "HTTP_ERROR", "message": str(exc.detail), "details": {}}
    )
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
        content={
            "error": {
                "code": code,
                "message": "Resource conflicts with existing data",
                "details": {},
            }
        },
    )


@app.get("/health", tags=["system"], summary="Health check")
async def health() -> dict[str, str]:
    """Return the health status of the academic service."""
    return {"status": "ok"}
