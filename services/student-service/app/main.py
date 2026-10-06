from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect

from app.db import get_session
from app.models import Student, StudentGroup

app = FastAPI(
    title="Student Service", version="1.0.0", description="Students and groups API"
)


def dump(row: Any) -> dict[str, Any]:
    return {c.key: getattr(row, c.key) for c in inspect(row).mapper.column_attrs}


def register(path: str, model: Any, filters: tuple[str, ...] = ()):
    @app.get(f"/api/v1/students/{path}", tags=[path])
    async def list_items(
        request: Request,
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=500),
        session: AsyncSession = Depends(get_session),
    ):
        query = select(model)
        for key in filters:
            value = request.query_params.get(key)
            if value is not None:
                typ = getattr(model, key).type.python_type
                value = UUID(value) if typ is UUID else typ(value)
                query = query.where(getattr(model, key) == value)
        return [
            dump(x)
            for x in (await session.scalars(query.offset(offset).limit(limit))).all()
        ]

    @app.post(f"/api/v1/students/{path}", status_code=201, tags=[path])
    async def create(
        payload: dict[str, Any], session: AsyncSession = Depends(get_session)
    ):
        row = model(**payload)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return dump(row)

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
        allowed = {c.key for c in inspect(model).mapper.column_attrs}
        for key, value in payload.items():
            if key in allowed and key != "id":
                setattr(row, key, value)
        await session.commit()
        await session.refresh(row)
        return dump(row)

    @app.delete(f"/api/v1/students/{path}/{{item_id}}", status_code=204, tags=[path])
    async def delete(item_id: UUID, session: AsyncSession = Depends(get_session)):
        row = await session.get(model, item_id)
        if row is None:
            raise HTTPException(404, "Resource not found")
        await session.delete(row)
        await session.commit()


register("groups", StudentGroup, ("specialty_id", "department_id", "enrollment_year"))
register("students", Student, ("group_id", "status", "email", "student_card_number"))


@app.get("/api/v1/students/groups/{group_id}/students", tags=["groups"])
async def group_students(group_id: UUID, session: AsyncSession = Depends(get_session)):
    return [
        dump(x)
        for x in (
            await session.scalars(select(Student).where(Student.group_id == group_id))
        ).all()
    ]


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Return the health status of the student service."""
    return {"status": "ok"}
