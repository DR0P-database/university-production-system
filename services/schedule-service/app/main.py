from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect

from app.db import get_session
from app.models import Schedule

app = FastAPI(
    title="Schedule Service", version="1.0.0", description="University schedule API"
)


def dump(row: Any) -> dict[str, Any]:
    return {c.key: getattr(row, c.key) for c in inspect(row).mapper.column_attrs}


@app.get("/api/v1/schedule", tags=["schedule"])
async def list_schedule(
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    query = select(Schedule)
    for key in ("group_id", "lecture_id", "status"):
        value = request.query_params.get(key)
        if value is not None:
            query = query.where(
                getattr(Schedule, key)
                == (UUID(value) if key.endswith("_id") else value)
            )
    for key in ("scheduled_date", "week_start_date"):
        value = request.query_params.get(key)
        if value is not None:
            query = query.where(getattr(Schedule, key) == date.fromisoformat(value))
    return [
        dump(x)
        for x in (await session.scalars(query.offset(offset).limit(limit))).all()
    ]


@app.post("/api/v1/schedule", status_code=201, tags=["schedule"])
async def create_schedule(
    payload: dict[str, Any], session: AsyncSession = Depends(get_session)
):
    row = Schedule(**payload)
    session.add(row)
    await session.commit()
    await session.refresh(row)
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
    allowed = {c.key for c in inspect(Schedule).mapper.column_attrs}
    for key, value in payload.items():
        if key in allowed and key != "id":
            setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
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


@app.get("/api/v1/schedule/groups/{group_id}", tags=["schedule"])
async def group_schedule(group_id: UUID, session: AsyncSession = Depends(get_session)):
    return [
        dump(x)
        for x in (
            await session.scalars(select(Schedule).where(Schedule.group_id == group_id))
        ).all()
    ]


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Return the health status of the schedule service."""
    return {"status": "ok"}
