import os
from uuid import UUID

import httpx

from app.errors import api_error


async def require_exists(service: str, path: str, item_id: UUID) -> None:
    base = os.getenv(f"{service.upper()}_SERVICE_URL", f"http://{service}-service:8000")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{base}{path}/{item_id}")
    except httpx.HTTPError as exc:
        raise api_error(
            503, "DEPENDENCY_UNAVAILABLE", f"{service} service is unavailable"
        ) from exc
    if response.status_code == 404:
        code = "SCHEDULE_NOT_FOUND" if service == "schedule" else "STUDENT_NOT_FOUND"
        raise api_error(404, code, f"Referenced resource does not exist: {item_id}")
    if response.is_error:
        raise api_error(
            503,
            "DEPENDENCY_UNAVAILABLE",
            f"{service} service returned {response.status_code}",
        )


async def fetch_json(service: str, path: str, item_id: UUID) -> dict:
    base = os.getenv(f"{service.upper()}_SERVICE_URL", f"http://{service}-service:8000")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{base}{path}/{item_id}")
    except httpx.HTTPError as exc:
        raise api_error(
            503, "DEPENDENCY_UNAVAILABLE", f"{service} service is unavailable"
        ) from exc
    if response.status_code == 404:
        code = "SCHEDULE_NOT_FOUND" if service == "schedule" else "STUDENT_NOT_FOUND"
        raise api_error(404, code, f"Referenced resource does not exist: {item_id}")
    if response.is_error:
        raise api_error(
            503,
            "DEPENDENCY_UNAVAILABLE",
            f"{service} service returned {response.status_code}",
        )
    return response.json()
