from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect

from app.clients import fetch_json
from app.db import SessionLocal, get_session
from app.errors import api_error
from app.graph_store import GraphUnavailable, schedule_graph
from app.models import Schedule
from app.request_id import get_request_id, request_id_middleware
from app.schemas import ScheduleCreate, SchedulePage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.getenv("PROJECTIONS_BOOTSTRAP_ON_STARTUP", "false").lower() == "true":
        async with SessionLocal() as session:
            try:
                await schedule_graph.rebuild(session)
            except GraphUnavailable:
                logger.warning(
                    "Could not rebuild Neo4j schedule projection during startup",
                    exc_info=True,
                )
    yield
    await schedule_graph.close()


app = FastAPI(
    title="Schedule Service",
    version="1.0.0",
    description="University schedule API",
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
    return JSONResponse(
        status_code=409,
        content=error_body("DATA_CONFLICT", "Resource conflicts with existing data"),
    )


def dump(row: Any) -> dict[str, Any]:
    return {c.key: getattr(row, c.key) for c in inspect(row).mapper.column_attrs}


async def sync_graph(row: Schedule) -> None:
    try:
        await schedule_graph.upsert(row)
    except GraphUnavailable:
        logger.warning("Could not update Neo4j schedule projection", exc_info=True)


async def delete_from_graph(schedule_id: UUID) -> None:
    try:
        await schedule_graph.delete(schedule_id)
    except GraphUnavailable:
        logger.warning("Could not delete Neo4j schedule projection", exc_info=True)


@app.get("/api/v1/schedule", tags=["schedule"])
async def list_schedule(
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    group_id: UUID | None = Query(None),
    lecture_id: UUID | None = Query(None),
    lecture_ids: list[UUID] | None = Query(None, max_length=100),
    group_ids: list[UUID] | None = Query(None, max_length=100),
    status: str | None = Query(None),
    scheduled_date: date | None = Query(None),
    week_start_date: date | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    if date_from is not None and date_to is not None and date_from > date_to:
        raise api_error(
            400, "INVALID_DATE_RANGE", "date_from must not be after date_to"
        )
    query = select(Schedule)
    if lecture_ids is not None:
        query = query.where(Schedule.lecture_id.in_(lecture_ids))
    if group_ids is not None:
        query = query.where(Schedule.group_id.in_(group_ids))
    explicit = {
        "group_id": group_id,
        "lecture_id": lecture_id,
        "status": status,
        "scheduled_date": scheduled_date,
        "week_start_date": week_start_date,
    }
    for key in ("group_id", "lecture_id", "status"):
        value = explicit[key]
        if value is not None:
            query = query.where(getattr(Schedule, key) == value)
    for key in ("scheduled_date", "week_start_date"):
        value = explicit[key]
        if value is not None:
            query = query.where(getattr(Schedule, key) == value)
    if date_from is not None:
        query = query.where(Schedule.scheduled_date >= date_from)
    if date_to is not None:
        query = query.where(Schedule.scheduled_date <= date_to)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await session.scalars(query.order_by(Schedule.id).offset(offset).limit(limit))
    ).all()
    return {
        "items": [dump(x) for x in rows],
        "limit": limit,
        "offset": offset,
        "total": total or 0,
    }


@app.post("/api/v1/schedule", status_code=201, tags=["schedule"])
async def create_schedule(
    payload: dict[str, Any], session: AsyncSession = Depends(get_session)
):
    data = ScheduleCreate.model_validate(payload).model_dump()
    lecture = await fetch_json(
        "academic", "/api/v1/academic/lectures", data["lecture_id"]
    )
    course = await fetch_json(
        "academic", "/api/v1/academic/courses", lecture["course_id"]
    )
    group = await fetch_json("student", "/api/v1/students/groups", data["group_id"])
    if course["specialty_id"] != group["specialty_id"]:
        raise api_error(
            400,
            "SPECIALTY_MISMATCH",
            "Lecture and group belong to different specialties",
        )
    row = Schedule(**data)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    await sync_graph(row)
    return dump(row)


@app.get("/api/v1/schedule/{schedule_id}", tags=["schedule"])
async def get_schedule(schedule_id: UUID, session: AsyncSession = Depends(get_session)):
    row = await session.get(Schedule, schedule_id)
    if row is None:
        raise HTTPException(404, "Schedule not found")
    return dump(row)


@app.patch("/api/v1/schedule/{schedule_id}", tags=["schedule"])
async def patch_schedule(
    schedule_id: UUID,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(Schedule, schedule_id)
    if row is None:
        raise HTTPException(404, "Schedule not found")
    current = {key: getattr(row, key) for key in ScheduleCreate.model_fields}
    data = ScheduleCreate.model_validate({**current, **payload}).model_dump()
    if "lecture_id" in payload or "group_id" in payload:
        lecture = await fetch_json(
            "academic", "/api/v1/academic/lectures", data["lecture_id"]
        )
        course = await fetch_json(
            "academic", "/api/v1/academic/courses", lecture["course_id"]
        )
        group = await fetch_json("student", "/api/v1/students/groups", data["group_id"])
        if course["specialty_id"] != group["specialty_id"]:
            raise api_error(
                400,
                "SPECIALTY_MISMATCH",
                "Lecture and group belong to different specialties",
            )
    allowed = {c.key for c in inspect(Schedule).mapper.column_attrs}
    for key, value in data.items():
        if key in allowed and key != "id":
            setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    await sync_graph(row)
    return dump(row)


@app.delete("/api/v1/schedule/{schedule_id}", status_code=204, tags=["schedule"])
async def delete_schedule(
    schedule_id: UUID, session: AsyncSession = Depends(get_session)
):
    row = await session.get(Schedule, schedule_id)
    if row is None:
        raise HTTPException(404, "Schedule not found")
    await session.delete(row)
    await session.commit()
    await delete_from_graph(schedule_id)


@app.get("/api/v1/schedule/groups/{group_id}", tags=["schedule"])
async def group_schedule(
    group_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    query = select(Schedule).where(Schedule.group_id == group_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await session.scalars(query.offset(offset).limit(limit))).all()
    return {
        "items": [dump(x) for x in rows],
        "limit": limit,
        "offset": offset,
        "total": total or 0,
    }


@app.get(
    "/api/v1/schedule/students/{student_id}",
    tags=["graph"],
    response_model=SchedulePage,
)
async def student_schedule_from_graph(
    student_id: UUID,
    status: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """Read a student's group schedule entirely from Neo4j."""
    if date_from is not None and date_to is not None and date_from > date_to:
        raise api_error(
            400, "INVALID_DATE_RANGE", "date_from must not be after date_to"
        )
    try:
        result = await schedule_graph.student_schedule(
            student_id,
            status=status,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=limit,
        )
    except GraphUnavailable as exc:
        raise HTTPException(
            503,
            {
                "code": "GRAPH_UNAVAILABLE",
                "message": "Schedule graph is unavailable",
                "details": {},
            },
        ) from exc
    if result is None:
        raise HTTPException(404, "Student not found in graph")
    return result


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Return the health status of the schedule service."""
    return {"status": "ok"}
