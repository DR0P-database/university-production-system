from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from uuid import uuid4

from fastapi import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str:
    return _request_id.get() or str(uuid4())


async def request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())
    token = _request_id.set(request_id)
    request.state.request_id = request_id
    try:
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
    finally:
        _request_id.reset(token)
