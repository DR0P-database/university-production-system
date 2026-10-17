import os
from uuid import UUID

import httpx

from app.errors import api_error
from app.request_id import REQUEST_ID_HEADER, get_request_id


async def require_exists(service: str, path: str, item_id: UUID) -> None:
    base = os.getenv(f"{service.upper()}_SERVICE_URL", f"http://{service}-service:8000")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(
                f"{base}{path}/{item_id}",
                headers={REQUEST_ID_HEADER: get_request_id()},
            )
    except httpx.HTTPError as exc:
        raise api_error(
            503, "DEPENDENCY_UNAVAILABLE", f"{service} service is unavailable"
        ) from exc
    if response.status_code == 404:
        code = (
            "SPECIALTY_NOT_FOUND"
            if "specialties" in path
            else "DEPARTMENT_NOT_FOUND"
            if "departments" in path
            else "GROUP_NOT_FOUND"
        )
        raise api_error(404, code, f"Referenced resource does not exist: {item_id}")
    if response.is_error:
        raise api_error(
            503,
            "DEPENDENCY_UNAVAILABLE",
            f"{service} service returned {response.status_code}",
        )
