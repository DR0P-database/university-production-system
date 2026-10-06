from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect

from app.db import get_session
from app.models import Attendance

app = FastAPI(
    title="Attendance Service", version="1.0.0", description="Attendance journal API"
)


def dump(row: Any) -> dict[str, Any]:
    return {c.key: getattr(row, c.key) for c in inspect(row).mapper.column_attrs}


@app.get("/api/v1/attendance", tags=["attendance"])
async def list_attendance(
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    query = select(Attendance)
    for key in ("schedule_id", "student_id", "week_start_date"):
        value = request.query_params.get(key)
        if value is not None:
            value = UUID(value) if key.endswith("_id") else date.fromisoformat(value)
            query = query.where(getattr(Attendance, key) == value)
    return [
        dump(x)
        for x in (await session.scalars(query.offset(offset).limit(limit))).all()
    ]


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


async def upsert(
    schedule_id: UUID, student_id: UUID, payload: dict[str, Any], session: AsyncSession
):
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
    await session.commit()
    await session.refresh(row)
    return dump(row)


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
    return await upsert(schedule_id, student_id, payload, session)


@app.put("/api/v1/attendance/schedules/{schedule_id}", tags=["attendance"])
async def mark_schedule_attendance(
    schedule_id: UUID,
    payload: list[dict[str, Any]],
    session: AsyncSession = Depends(get_session),
):
    """Replace or create attendance marks for a schedule."""
    result = []
    for item in payload:
        result.append(
            await upsert(schedule_id, UUID(str(item.pop("student_id"))), item, session)
        )
    return result


@app.get("/api/v1/attendance/schedules/{schedule_id}", tags=["attendance"])
async def schedule_journal(
    schedule_id: UUID,
    week_start_date: date | None = None,
    session: AsyncSession = Depends(get_session),
):
    query = select(Attendance).where(Attendance.schedule_id == schedule_id)
    if week_start_date is not None:
        query = query.where(Attendance.week_start_date == week_start_date)
    return [dump(x) for x in (await session.scalars(query)).all()]


@app.get("/api/v1/attendance/students/{student_id}", tags=["attendance"])
async def student_history(
    student_id: UUID, session: AsyncSession = Depends(get_session)
):
    return [
        dump(x)
        for x in (
            await session.scalars(
                select(Attendance).where(Attendance.student_id == student_id)
            )
        ).all()
    ]


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Return the health status of the attendance service."""
    return {"status": "ok"}
