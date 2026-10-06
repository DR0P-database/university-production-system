from fastapi import FastAPI

from app.api import router

app = FastAPI(
    title="Academic Service",
    version="1.0.0",
    description="University academic data API",
)
app.include_router(router)


@app.get("/health", tags=["system"], summary="Health check")
async def health() -> dict[str, str]:
    """Return the health status of the academic service."""
    return {"status": "ok"}
