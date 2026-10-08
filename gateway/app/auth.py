from __future__ import annotations

import os
from typing import Any

import jwt
from fastapi import HTTPException, Request


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code, {"code": code, "message": message, "details": {}})


def authenticate(request: Request) -> dict[str, Any]:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise _error(401, "UNAUTHORIZED", "Bearer token is required")
    token = header.removeprefix("Bearer ").strip()
    try:
        return jwt.decode(
            token,
            os.getenv("JWT_SECRET", "change-me-in-production"),
            algorithms=[os.getenv("JWT_ALGORITHM", "HS256")],
            options={"require": ["sub", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise _error(401, "UNAUTHORIZED", "Token is invalid or expired") from exc


def authorize(request: Request, claims: dict[str, Any]) -> None:
    method = request.method.upper()
    roles = set(claims.get("roles", []))
    if method == "DELETE" and "admin" not in roles:
        raise _error(403, "FORBIDDEN", "Admin role is required")
    if method in {"POST", "PUT", "PATCH"} and not roles.intersection(
        {"admin", "teacher"}
    ):
        raise _error(403, "FORBIDDEN", "Admin or teacher role is required")
