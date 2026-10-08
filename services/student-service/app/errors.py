from fastapi import HTTPException


def api_error(
    status_code: int, code: str, message: str, details: dict | None = None
) -> HTTPException:
    return HTTPException(
        status_code, {"code": code, "message": message, "details": details or {}}
    )
