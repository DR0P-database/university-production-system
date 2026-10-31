from __future__ import annotations

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
from app.db import get_session
from app.errors import api_error
from app.models import Attendance
from app.partitions import ensure_partitions
from app.request_id import get_request_id, request_id_middleware
from app.schemas import AttendanceBatchMark, AttendanceMark

app = FastAPI(
    title="Attendance Service",
    version="1.0.0",
    description="Attendance journal API",
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


@app.get("/api/v1/attendance", tags=["attendance"])
async def list_attendance(
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    schedule_id: UUID | None = Query(None),
    student_id: UUID | None = Query(None),
    week_start_date: date | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    query = select(Attendance)
    explicit = {
        "schedule_id": schedule_id,
        "student_id": student_id,
        "week_start_date": week_start_date,
    }
    for key in ("schedule_id", "student_id", "week_start_date"):
        value = explicit[key]
        if value is not None:
            query = query.where(getattr(Attendance, key) == value)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await session.scalars(query.offset(offset).limit(limit))).all()
    return {
        "items": [dump(x) for x in rows],
        "limit": limit,
        "offset": offset,
        "total": total or 0,
    }


@app.get("/api/v1/attendance/{attendance_id}", tags=["attendance"])
async def get_attendance(
    attendance_id: UUID, session: AsyncSession = Depends(get_session)
):
    row = (
        await session.scalars(select(Attendance).where(Attendance.id == attendance_id))
    ).first()
    if row is None:
        raise HTTPException(404, "Attendance record not found")
    return dump(row)


async def upsert_row(
    schedule_id: UUID, student_id: UUID, payload: dict[str, Any], session: AsyncSession
) -> Attendance:
    week = (
        date.fromisoformat(payload["week_start_date"])
        if isinstance(payload.get("week_start_date"), str)
        else payload.get("week_start_date")
    )
    row = (
        await session.scalars(
            select(Attendance).where(
                Attendance.schedule_id == schedule_id,
                Attendance.student_id == student_id,
                Attendance.week_start_date == week,
            )
        )
    ).first()
    if row is None:
        row = Attendance(schedule_id=schedule_id, student_id=student_id, **payload)
        session.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
    await session.flush()
    return row


@app.put(
    "/api/v1/attendance/schedules/{schedule_id}/students/{student_id}",
    tags=["attendance"],
)
async def mark_attendance(
    schedule_id: UUID,
    student_id: UUID,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
):
    """Create or update one attendance mark idempotently."""
    data = AttendanceMark.model_validate(payload).model_dump()
    schedule = await fetch_json("schedule", "/api/v1/schedule", schedule_id)
    student = await fetch_json("student", "/api/v1/students/students", student_id)
    if schedule["group_id"] != student["group_id"]:
        raise api_error(
            400,
            "STUDENT_NOT_IN_SCHEDULE_GROUP",
            "Student does not belong to the schedule group",
        )
    await ensure_partitions([data["week_start_date"]])
    row = await upsert_row(schedule_id, student_id, data, session)
    await session.commit()
    await session.refresh(row)
    return dump(row)


@app.put("/api/v1/attendance/schedules/{schedule_id}", tags=["attendance"])
async def mark_schedule_attendance(
    schedule_id: UUID,
    payload: list[dict[str, Any]],
    session: AsyncSession = Depends(get_session),
):
    """Replace or create attendance marks for a schedule."""
    schedule = await fetch_json("schedule", "/api/v1/schedule", schedule_id)
    validated_items = []
    for item in payload:
        data = AttendanceBatchMark.model_validate(item).model_dump()
        student_id = data.pop("student_id")
        student = await fetch_json("student", "/api/v1/students/students", student_id)
        if schedule["group_id"] != student["group_id"]:
            raise api_error(
                400,
                "STUDENT_NOT_IN_SCHEDULE_GROUP",
                "Student does not belong to the schedule group",
            )
        validated_items.append((student_id, data))

    await ensure_partitions(data["week_start_date"] for _, data in validated_items)
    rows = [
        await upsert_row(schedule_id, student_id, data, session)
        for student_id, data in validated_items
    ]
    await session.commit()
    for row in rows:
        await session.refresh(row)
    return [dump(row) for row in rows]


@app.get("/api/v1/attendance/schedules/{schedule_id}", tags=["attendance"])
async def schedule_journal(
    schedule_id: UUID,
    week_start_date: date | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    query = select(Attendance).where(Attendance.schedule_id == schedule_id)
    if week_start_date is not None:
        query = query.where(Attendance.week_start_date == week_start_date)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await session.scalars(query.offset(offset).limit(limit))).all()
    return {
        "items": [dump(x) for x in rows],
        "limit": limit,
        "offset": offset,
        "total": total or 0,
    }


@app.get("/api/v1/attendance/students/{student_id}", tags=["attendance"])
async def student_history(
    student_id: UUID,
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    if date_from is not None and date_to is not None and date_from > date_to:
        raise api_error(
            400, "INVALID_DATE_RANGE", "date_from must not be after date_to"
        )
    query = select(Attendance).where(Attendance.student_id == student_id)
    if date_from is not None:
        query = query.where(Attendance.week_start_date >= date_from)
    if date_to is not None:
        query = query.where(Attendance.week_start_date <= date_to)
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
    """Return the health status of the attendance service."""
    return {"status": "ok"}
