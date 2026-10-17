from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect

from app.clients import require_exists
from app.db import SessionLocal, get_session
from app.graph_store import GraphUnavailable, student_graph
from app.models import Student, StudentGroup
from app.request_id import get_request_id, request_id_middleware
from app.schemas import (
    GraphPage,
    GroupCreate,
    StudentCreate,
    StudentGraphResponse,
)
from app.student_cache import (
    cache_student,
    close_cache,
    get_cached_student,
    invalidate_student,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.getenv("PROJECTIONS_BOOTSTRAP_ON_STARTUP", "false").lower() == "true":
        async with SessionLocal() as session:
            await student_graph.rebuild(session)
    yield
    await student_graph.close()
    await close_cache()


app = FastAPI(
    title="Student Service",
    version="1.0.0",
    description="Students and groups API",
    lifespan=lifespan,
)
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
    if "students_email" in text:
        code = "EMAIL_ALREADY_EXISTS"
    elif "students_student_card_number" in text:
        code = "STUDENT_CARD_NUMBER_ALREADY_EXISTS"
    elif "student_groups_name" in text:
        code = "GROUP_NAME_ALREADY_EXISTS"
    else:
        code = "DATA_CONFLICT"
    return JSONResponse(
        status_code=409,
        content=error_body(code, "Resource conflicts with existing data"),
    )


def dump(row: Any) -> dict[str, Any]:
    return {c.key: getattr(row, c.key) for c in inspect(row).mapper.column_attrs}


async def sync_graph(row: Any) -> None:
    try:
        if isinstance(row, StudentGroup):
            await student_graph.upsert_group(row)
        elif isinstance(row, Student):
            await student_graph.upsert_student(row)
    except GraphUnavailable:
        logger.warning("Could not update Neo4j student projection", exc_info=True)


async def delete_from_graph(model: Any, item_id: UUID) -> None:
    try:
        label = "StudentGroup" if model is StudentGroup else "Student"
        await student_graph.delete_entity(label, item_id)
    except GraphUnavailable:
        logger.warning("Could not delete Neo4j student projection", exc_info=True)


def register(path: str, model: Any, schema: Any, filters: tuple[str, ...] = ()):
    @app.get(f"/api/v1/students/{path}", tags=[path])
    async def list_items(
        request: Request,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        specialty_id: UUID | None = Query(None),
        department_id: UUID | None = Query(None),
        enrollment_year: int | None = Query(None, gt=0),
        group_id: UUID | None = Query(None),
        status: str | None = Query(None),
        email: str | None = Query(None),
        student_card_number: str | None = Query(None),
        session: AsyncSession = Depends(get_session),
    ):
        query = select(model)
        explicit = {
            "specialty_id": specialty_id,
            "department_id": department_id,
            "enrollment_year": enrollment_year,
            "group_id": group_id,
            "status": status,
            "email": email,
            "student_card_number": student_card_number,
        }
        for key in filters:
            value = explicit[key]
            if value is not None:
                query = query.where(getattr(model, key) == value)
        total = await session.scalar(select(func.count()).select_from(query.subquery()))
        rows = (await session.scalars(query.offset(offset).limit(limit))).all()
        return {
            "items": [dump(x) for x in rows],
            "limit": limit,
            "offset": offset,
            "total": total or 0,
        }

    @app.post(f"/api/v1/students/{path}", status_code=201, tags=[path])
    async def create(
        payload: dict[str, Any], session: AsyncSession = Depends(get_session)
    ):
        data = schema.model_validate(payload).model_dump()
        if model is StudentGroup:
            await require_exists(
                "academic", "/api/v1/academic/specialties", data["specialty_id"]
            )
            await require_exists(
                "academic", "/api/v1/academic/departments", data["department_id"]
            )
        else:
            if await session.get(StudentGroup, data["group_id"]) is None:
                raise HTTPException(
                    404,
                    {
                        "code": "GROUP_NOT_FOUND",
                        "message": "Referenced group does not exist",
                        "details": {"group_id": str(data["group_id"])},
                    },
                )
        row = model(**data)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        await sync_graph(row)
        result = dump(row)
        if model is Student:
            await cache_student(jsonable_encoder(result))
        return result

    @app.get(f"/api/v1/students/{path}/{{item_id}}", tags=[path])
    async def get(item_id: UUID, session: AsyncSession = Depends(get_session)):
        row = await session.get(model, item_id)
        if row is None:
            raise HTTPException(404, "Resource not found")
        return dump(row)

    @app.patch(f"/api/v1/students/{path}/{{item_id}}", tags=[path])
    async def patch(
        item_id: UUID,
        payload: dict[str, Any],
        session: AsyncSession = Depends(get_session),
    ):
        row = await session.get(model, item_id)
        if row is None:
            raise HTTPException(404, "Resource not found")
        previous_student_card_number = (
            row.student_card_number if model is Student else None
        )
        allowed = {c.key for c in inspect(model).mapper.column_attrs}
        current = {key: getattr(row, key) for key in schema.model_fields}
        data = schema.model_validate({**current, **payload}).model_dump()
        if model is Student and "group_id" in payload:
            if await session.get(StudentGroup, data["group_id"]) is None:
                raise HTTPException(
                    404,
                    {
                        "code": "GROUP_NOT_FOUND",
                        "message": "Referenced group does not exist",
                        "details": {"group_id": str(data["group_id"])},
                    },
                )
        for key, value in data.items():
            if key in allowed and key != "id":
                setattr(row, key, value)
        await session.commit()
        await session.refresh(row)
        await sync_graph(row)
        result = dump(row)
        if model is Student:
            await invalidate_student(previous_student_card_number)
            await cache_student(jsonable_encoder(result))
        return result

    @app.delete(f"/api/v1/students/{path}/{{item_id}}", status_code=204, tags=[path])
    async def delete(item_id: UUID, session: AsyncSession = Depends(get_session)):
        row = await session.get(model, item_id)
        if row is None:
            raise HTTPException(404, "Resource not found")
        student_card_number = row.student_card_number if model is Student else None
        await session.delete(row)
        await session.commit()
        await delete_from_graph(model, item_id)
        if model is Student:
            await invalidate_student(student_card_number)


register(
    "groups",
    StudentGroup,
    GroupCreate,
    ("specialty_id", "department_id", "enrollment_year"),
)


@app.get(
    "/api/v1/students/graph/universities/{university_id}/students",
    tags=["graph"],
    response_model=GraphPage[StudentGraphResponse],
)
async def university_students_from_graph(
    university_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """Read all students of a university from Neo4j."""
    try:
        result = await student_graph.university_students(university_id, offset, limit)
    except GraphUnavailable as exc:
        raise HTTPException(
            503,
            {
                "code": "GRAPH_UNAVAILABLE",
                "message": "Student graph is unavailable",
                "details": {},
            },
        ) from exc
    if result is None:
        raise HTTPException(404, "University not found in graph")
    return result


@app.get(
    "/api/v1/students/graph/students/{student_id}",
    tags=["graph"],
    response_model=StudentGraphResponse,
)
async def student_with_group_from_graph(student_id: UUID):
    """Read a student, group and university path entirely from Neo4j."""
    try:
        result = await student_graph.student_context(student_id)
    except GraphUnavailable as exc:
        raise HTTPException(
            503,
            {
                "code": "GRAPH_UNAVAILABLE",
                "message": "Student graph is unavailable",
                "details": {},
            },
        ) from exc
    if result is None:
        raise HTTPException(404, "Student not found in graph")
    return result


@app.get("/api/v1/students/students/by-card/{student_card_number}", tags=["students"])
async def student_by_card(
    student_card_number: str,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    """Return one student by their unique student card number using Redis cache."""
    cached = await get_cached_student(student_card_number)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return cached

    row = (
        await session.scalars(
            select(Student).where(Student.student_card_number == student_card_number)
        )
    ).first()
    if row is None:
        raise HTTPException(
            404,
            {
                "code": "STUDENT_NOT_FOUND",
                "message": "Student with this card number does not exist",
                "details": {"student_card_number": student_card_number},
            },
        )
    result = dump(row)
    await cache_student(jsonable_encoder(result))
    response.headers["X-Cache"] = "MISS"
    return result


register(
    "students",
    Student,
    StudentCreate,
    ("group_id", "status", "email", "student_card_number"),
)


@app.get("/api/v1/students/groups/{group_id}/students", tags=["groups"])
async def group_students(
    group_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    query = select(Student).where(Student.group_id == group_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await session.scalars(query.offset(offset).limit(limit))).all()
    return {
        "items": [dump(x) for x in rows],
        "limit": limit,
        "offset": offset,
        "total": total or 0,
    }


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Return the health status of the student service."""
    return {"status": "ok"}
