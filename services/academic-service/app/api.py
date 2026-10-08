from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect

from app.db import get_session
from app.models import (
    Department,
    DepartmentSpecialty,
    Institute,
    Lecture,
    LectureCourse,
    LectureMaterial,
    Specialty,
    University,
)
from app.schemas import (
    CourseCreate,
    DepartmentCreate,
    InstituteCreate,
    LectureCreate,
    MaterialCreate,
    RelationCreate,
    RelationUpdate,
    SpecialtyCreate,
    UniversityCreate,
)

router = APIRouter(prefix="/api/v1/academic")


def dump(obj: Any) -> dict[str, Any]:
    return {c.key: getattr(obj, c.key) for c in inspect(obj).mapper.column_attrs}


async def list_rows(
    model: Any, session: AsyncSession, filters: dict[str, Any], offset: int, limit: int
):
    query = select(model)
    department_id = filters.pop("department_id", None)
    if department_id is not None and model is Specialty:
        query = query.join(
            DepartmentSpecialty, DepartmentSpecialty.specialty_id == Specialty.id
        )
        query = query.where(DepartmentSpecialty.department_id == department_id)
    for key, value in filters.items():
        if value is not None and hasattr(model, key):
            query = query.where(getattr(model, key) == value)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await session.scalars(query.offset(offset).limit(limit))).all()
    return {
        "items": [dump(row) for row in rows],
        "limit": limit,
        "offset": offset,
        "total": total or 0,
    }


async def get_row(model: Any, item_id: UUID, session: AsyncSession):
    row = await session.get(model, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    return row


def register_crud(
    path: str, model: Any, tag: str, schema: Any, filters: tuple[str, ...] = ()
) -> None:
    @router.get(f"/{path}", tags=[tag], summary=f"List {path}")
    async def list_items(
        request: Request,
        session: AsyncSession = Depends(get_session),
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        department_id: UUID | None = Query(
            None, description="Filter specialties by department UUID"
        ),
    ):
        values = {key: request.query_params.get(key) for key in filters}
        if "department_id" in values:
            values["department_id"] = department_id
        for key, value in values.items():
            if value is not None:
                try:
                    column = getattr(model, key)
                    if column.type.python_type.__name__ == "UUID":
                        values[key] = UUID(value)
                    elif column.type.python_type is int:
                        values[key] = int(value)
                except (ValueError, AttributeError):
                    raise HTTPException(422, f"Invalid filter: {key}") from None
        return await list_rows(model, session, values, offset, limit)

    @router.post(
        f"/{path}",
        status_code=status.HTTP_201_CREATED,
        tags=[tag],
        summary=f"Create {path[:-1]}",
    )
    async def create_item(
        payload: dict[str, Any], session: AsyncSession = Depends(get_session)
    ):
        data = schema.model_validate(payload).model_dump()
        row = model(**data)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return dump(row)

    @router.get(f"/{path}/{{item_id}}", tags=[tag], summary=f"Get {path[:-1]}")
    async def get_item(item_id: UUID, session: AsyncSession = Depends(get_session)):
        return dump(await get_row(model, item_id, session))

    @router.patch(f"/{path}/{{item_id}}", tags=[tag], summary=f"Update {path[:-1]}")
    async def update_item(
        item_id: UUID,
        payload: dict[str, Any],
        session: AsyncSession = Depends(get_session),
    ):
        row = await get_row(model, item_id, session)
        allowed = {c.key for c in inspect(model).mapper.column_attrs}
        current = {key: dump(row).get(key) for key in schema.model_fields}
        data = schema.model_validate({**current, **payload}).model_dump()
        for key, value in data.items():
            if key in allowed and key != "id":
                setattr(row, key, value)
        await session.commit()
        await session.refresh(row)
        return dump(row)

    @router.delete(
        f"/{path}/{{item_id}}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=[tag],
        summary=f"Delete {path[:-1]}",
    )
    async def delete_item(item_id: UUID, session: AsyncSession = Depends(get_session)):
        row = await get_row(model, item_id, session)
        await session.delete(row)
        await session.commit()


register_crud("universities", University, "universities", UniversityCreate)
register_crud(
    "institutes", Institute, "institutes", InstituteCreate, ("university_id",)
)
register_crud(
    "departments", Department, "departments", DepartmentCreate, ("institute_id",)
)
register_crud(
    "specialties",
    Specialty,
    "specialties",
    SpecialtyCreate,
    ("degree_level", "code", "department_id"),
)
register_crud(
    "courses", LectureCourse, "courses", CourseCreate, ("specialty_id", "semester")
)
register_crud(
    "lectures", Lecture, "lectures", LectureCreate, ("course_id", "lecture_type")
)
register_crud(
    "materials",
    LectureMaterial,
    "materials",
    MaterialCreate,
    ("lecture_id", "content_type"),
)


@router.get("/departments/{department_id}/specialties", tags=["department-specialties"])
async def list_department_specialties(
    department_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    return await list_rows(
        DepartmentSpecialty,
        session,
        {"department_id": department_id},
        offset,
        limit,
    )


@router.post(
    "/departments/{department_id}/specialties",
    status_code=201,
    tags=["department-specialties"],
)
async def assign_department_specialty(
    department_id: UUID,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
):
    data = RelationCreate.model_validate(payload).model_dump()
    row = DepartmentSpecialty(department_id=department_id, **data)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return dump(row)


@router.patch(
    "/departments/{department_id}/specialties/{specialty_id}",
    tags=["department-specialties"],
)
async def update_department_specialty(
    department_id: UUID,
    specialty_id: UUID,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(
        DepartmentSpecialty,
        {"department_id": department_id, "specialty_id": specialty_id},
    )
    if row is None:
        raise HTTPException(404, "Relationship not found")
    data = RelationUpdate.model_validate(payload).model_dump()
    row.is_primary = data["is_primary"]
    await session.commit()
    await session.refresh(row)
    return dump(row)


@router.delete(
    "/departments/{department_id}/specialties/{specialty_id}",
    status_code=204,
    tags=["department-specialties"],
)
async def remove_department_specialty(
    department_id: UUID,
    specialty_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    await session.execute(
        delete(DepartmentSpecialty).where(
            DepartmentSpecialty.department_id == department_id,
            DepartmentSpecialty.specialty_id == specialty_id,
        )
    )
    await session.commit()


@router.get("/lectures/{lecture_id}/materials", tags=["materials"])
async def list_lecture_materials(
    lecture_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    return await list_rows(
        LectureMaterial, session, {"lecture_id": lecture_id}, offset, limit
    )
