from __future__ import annotations

import logging
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect

from app.academic_graph import GraphUnavailable, academic_graph
from app.content_store import content_store
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
from app.projections import (
    sync_course_projections,
    sync_lecture_projection,
)
from app.schemas import (
    AcademicGraphStatsResponse,
    CourseCreate,
    CourseResponse,
    DepartmentCreate,
    DepartmentResponse,
    InstituteCreate,
    InstituteResponse,
    LectureCreate,
    LectureResponse,
    MaterialCreate,
    MaterialResponse,
    MaterialUpdate,
    Page,
    RelationCreate,
    RelationResponse,
    RelationUpdate,
    SearchDocumentPage,
    SpecialtyCreate,
    SpecialtyResponse,
    UniversityCreate,
    UniversityGraphResponse,
    UniversityResponse,
)
from app.search_store import SearchUnavailable, search_store

router = APIRouter(prefix="/api/v1/academic")
logger = logging.getLogger(__name__)

PARENT_REFERENCES = {
    Institute: (University, "university_id", "UNIVERSITY_NOT_FOUND"),
    Department: (Institute, "institute_id", "INSTITUTE_NOT_FOUND"),
    LectureCourse: (Specialty, "specialty_id", "SPECIALTY_NOT_FOUND"),
    Lecture: (LectureCourse, "course_id", "COURSE_NOT_FOUND"),
    LectureMaterial: (Lecture, "lecture_id", "LECTURE_NOT_FOUND"),
}


def dump(obj: Any) -> dict[str, Any]:
    return {c.key: getattr(obj, c.key) for c in inspect(obj).mapper.column_attrs}


async def list_rows(
    model: Any, session: AsyncSession, filters: dict[str, Any], offset: int, limit: int
):
    query = select(model)
    department_id = filters.get("department_id")
    if department_id is not None and model is Specialty:
        filters.pop("department_id")
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


async def validate_parent(model: Any, data: dict[str, Any], session: AsyncSession):
    reference = PARENT_REFERENCES.get(model)
    if reference is None:
        return
    parent_model, field, code = reference
    parent_id = data[field]
    if await session.get(parent_model, parent_id) is None:
        raise HTTPException(
            404,
            {
                "code": code,
                "message": "Referenced resource does not exist",
                "details": {field: str(parent_id)},
            },
        )


async def sync_graph_entity(row: Any) -> None:
    try:
        await academic_graph.upsert_entity(row)
    except GraphUnavailable:
        logger.warning("Could not update Neo4j academic projection", exc_info=True)


async def delete_graph_entity(model: Any, item_id: UUID) -> None:
    try:
        await academic_graph.delete_entity(model, item_id)
    except GraphUnavailable:
        logger.warning("Could not delete Neo4j academic projection", exc_info=True)


async def sync_graph_relation(row: DepartmentSpecialty) -> None:
    try:
        await academic_graph.upsert_department_specialty(
            row.department_id, row.specialty_id, row.is_primary
        )
    except GraphUnavailable:
        logger.warning("Could not update Neo4j academic relation", exc_info=True)


def register_crud(
    path: str,
    model: Any,
    tag: str,
    schema: Any,
    response_schema: Any,
    filters: tuple[str, ...] = (),
) -> None:
    @router.get(
        f"/{path}",
        tags=[tag],
        summary=f"List {path}",
        response_model=Page[response_schema],
    )
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
        response_model=response_schema,
    )
    async def create_item(
        payload: dict[str, Any], session: AsyncSession = Depends(get_session)
    ):
        data = schema.model_validate(payload).model_dump()
        await validate_parent(model, data, session)
        row = model(**data)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        await sync_graph_entity(row)
        if model is Lecture:
            await sync_lecture_projection(session, row.id)
        return dump(row)

    @router.get(
        f"/{path}/{{item_id}}",
        tags=[tag],
        summary=f"Get {path[:-1]}",
        response_model=response_schema,
    )
    async def get_item(item_id: UUID, session: AsyncSession = Depends(get_session)):
        return dump(await get_row(model, item_id, session))

    @router.patch(
        f"/{path}/{{item_id}}",
        tags=[tag],
        summary=f"Update {path[:-1]}",
        response_model=response_schema,
    )
    async def update_item(
        item_id: UUID,
        payload: dict[str, Any],
        session: AsyncSession = Depends(get_session),
    ):
        row = await get_row(model, item_id, session)
        allowed = {c.key for c in inspect(model).mapper.column_attrs}
        current = {key: dump(row).get(key) for key in schema.model_fields}
        data = schema.model_validate({**current, **payload}).model_dump()
        reference = PARENT_REFERENCES.get(model)
        if reference is not None and reference[1] in payload:
            await validate_parent(model, data, session)
        for key, value in data.items():
            if key in allowed and key != "id":
                setattr(row, key, value)
        await session.commit()
        await session.refresh(row)
        await sync_graph_entity(row)
        if model is Lecture:
            await sync_lecture_projection(session, row.id)
        elif model is LectureCourse:
            await sync_course_projections(session, row.id)
        return dump(row)

    @router.delete(
        f"/{path}/{{item_id}}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=[tag],
        summary=f"Delete {path[:-1]}",
    )
    async def delete_item(item_id: UUID, session: AsyncSession = Depends(get_session)):
        row = await get_row(model, item_id, session)
        lecture_ids: list[UUID] = []
        material_ids: list[UUID] = []
        if model is Lecture:
            lecture_ids = [row.id]
            material_ids = list(
                await session.scalars(
                    select(LectureMaterial.id).where(
                        LectureMaterial.lecture_id == row.id
                    )
                )
            )
        elif model is LectureCourse:
            lecture_ids = list(
                await session.scalars(
                    select(Lecture.id).where(Lecture.course_id == row.id)
                )
            )
            if lecture_ids:
                material_ids = list(
                    await session.scalars(
                        select(LectureMaterial.id).where(
                            LectureMaterial.lecture_id.in_(lecture_ids)
                        )
                    )
                )
        await session.delete(row)
        await session.commit()
        await delete_graph_entity(model, item_id)
        if material_ids:
            try:
                await content_store.delete_many(material_ids)
            except Exception:
                logger.exception("Could not remove orphaned MongoDB material contents")
        for lecture_id in lecture_ids:
            try:
                await sync_lecture_projection(session, lecture_id)
            except Exception:
                logger.exception("Could not remove lecture search projection")


register_crud(
    "universities", University, "universities", UniversityCreate, UniversityResponse
)
register_crud(
    "institutes",
    Institute,
    "institutes",
    InstituteCreate,
    InstituteResponse,
    ("university_id",),
)
register_crud(
    "departments",
    Department,
    "departments",
    DepartmentCreate,
    DepartmentResponse,
    ("institute_id",),
)
register_crud(
    "specialties",
    Specialty,
    "specialties",
    SpecialtyCreate,
    SpecialtyResponse,
    ("degree_level", "code", "department_id"),
)
register_crud(
    "courses",
    LectureCourse,
    "courses",
    CourseCreate,
    CourseResponse,
    ("specialty_id", "semester"),
)
register_crud(
    "lectures",
    Lecture,
    "lectures",
    LectureCreate,
    LectureResponse,
    ("course_id", "lecture_type"),
)


def dump_material(material: LectureMaterial, content: dict[str, Any]) -> dict[str, Any]:
    result = dump(material)
    result.pop("content_ref", None)
    result["content_text"] = content.get("content_text")
    result["metadata_json"] = content.get("metadata", {})
    return result


async def list_materials_response(
    session: AsyncSession,
    *,
    lecture_id: UUID | None,
    content_type: str | None,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    query = select(LectureMaterial)
    if lecture_id is not None:
        query = query.where(LectureMaterial.lecture_id == lecture_id)
    if content_type is not None:
        query = query.where(LectureMaterial.content_type == content_type)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    materials = list(await session.scalars(query.offset(offset).limit(limit)))
    contents = await content_store.get_many([material.id for material in materials])
    return {
        "items": [
            dump_material(material, contents.get(str(material.id), {}))
            for material in materials
        ],
        "limit": limit,
        "offset": offset,
        "total": total or 0,
    }


@router.get(
    "/materials",
    tags=["materials"],
    summary="List materials",
    response_model=Page[MaterialResponse],
)
async def list_materials(
    lecture_id: UUID | None = Query(None),
    content_type: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    return await list_materials_response(
        session,
        lecture_id=lecture_id,
        content_type=content_type,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/materials",
    status_code=status.HTTP_201_CREATED,
    tags=["materials"],
    summary="Create material",
    response_model=MaterialResponse,
)
async def create_material(
    payload: MaterialCreate, session: AsyncSession = Depends(get_session)
):
    data = payload.model_dump()
    await validate_parent(LectureMaterial, data, session)
    material_id = uuid4()
    content_ref = await content_store.put(
        material_id, data["content_text"], data["metadata_json"]
    )
    material = LectureMaterial(
        id=material_id,
        lecture_id=data["lecture_id"],
        content_type=data["content_type"],
        title=data["title"],
        file_url=data["file_url"],
        content_ref=content_ref,
    )
    session.add(material)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        await content_store.delete(material_id)
        raise
    await session.refresh(material)
    await sync_lecture_projection(session, material.lecture_id)
    return dump_material(
        material,
        {"content_text": data["content_text"], "metadata": data["metadata_json"]},
    )


@router.get(
    "/materials/{item_id}",
    tags=["materials"],
    summary="Get material",
    response_model=MaterialResponse,
)
async def get_material(item_id: UUID, session: AsyncSession = Depends(get_session)):
    material = await get_row(LectureMaterial, item_id, session)
    return dump_material(material, await content_store.get(item_id))


@router.patch(
    "/materials/{item_id}",
    tags=["materials"],
    summary="Update material",
    response_model=MaterialResponse,
)
async def update_material(
    item_id: UUID,
    payload: MaterialUpdate,
    session: AsyncSession = Depends(get_session),
):
    material = await get_row(LectureMaterial, item_id, session)
    previous_content = await content_store.get(item_id)
    current = dump_material(material, previous_content)
    changes = payload.model_dump(exclude_unset=True)
    data = MaterialCreate.model_validate(
        {key: current.get(key) for key in MaterialCreate.model_fields} | changes
    ).model_dump()
    if "lecture_id" in changes:
        await validate_parent(LectureMaterial, data, session)

    previous_lecture_id = material.lecture_id
    content_ref = await content_store.put(
        item_id, data["content_text"], data["metadata_json"]
    )
    material.lecture_id = data["lecture_id"]
    material.content_type = data["content_type"]
    material.title = data["title"]
    material.file_url = data["file_url"]
    material.content_ref = content_ref
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        await content_store.put(
            item_id,
            previous_content.get("content_text"),
            previous_content.get("metadata", {}),
        )
        raise
    await session.refresh(material)
    await sync_lecture_projection(session, previous_lecture_id)
    if material.lecture_id != previous_lecture_id:
        await sync_lecture_projection(session, material.lecture_id)
    return dump_material(
        material,
        {"content_text": data["content_text"], "metadata": data["metadata_json"]},
    )


@router.delete(
    "/materials/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["materials"],
    summary="Delete material",
)
async def delete_material(item_id: UUID, session: AsyncSession = Depends(get_session)):
    material = await get_row(LectureMaterial, item_id, session)
    lecture_id = material.lecture_id
    previous_content = await content_store.get(item_id)
    await content_store.delete(item_id)
    await session.delete(material)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        await content_store.put(
            item_id,
            previous_content.get("content_text"),
            previous_content.get("metadata", {}),
        )
        raise
    await sync_lecture_projection(session, lecture_id)


@router.get(
    "/departments/{department_id}/specialties",
    tags=["department-specialties"],
    response_model=Page[RelationResponse],
)
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
    response_model=RelationResponse,
)
async def assign_department_specialty(
    department_id: UUID,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
):
    data = RelationCreate.model_validate(payload).model_dump()
    await get_row(Department, department_id, session)
    await get_row(Specialty, data["specialty_id"], session)
    row = DepartmentSpecialty(department_id=department_id, **data)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    await sync_graph_relation(row)
    return dump(row)


@router.patch(
    "/departments/{department_id}/specialties/{specialty_id}",
    tags=["department-specialties"],
    response_model=RelationResponse,
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
    await sync_graph_relation(row)
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
    row = await session.get(
        DepartmentSpecialty,
        {"department_id": department_id, "specialty_id": specialty_id},
    )
    if row is None:
        raise HTTPException(404, "Relationship not found")
    await session.execute(
        delete(DepartmentSpecialty).where(
            DepartmentSpecialty.department_id == department_id,
            DepartmentSpecialty.specialty_id == specialty_id,
        )
    )
    await session.commit()
    try:
        await academic_graph.delete_department_specialty(department_id, specialty_id)
    except GraphUnavailable:
        logger.warning("Could not delete Neo4j academic relation", exc_info=True)


@router.get(
    "/lectures/{lecture_id}/materials",
    tags=["materials"],
    response_model=Page[MaterialResponse],
)
async def list_lecture_materials(
    lecture_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    return await list_materials_response(
        session,
        lecture_id=lecture_id,
        content_type=None,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/search/documents",
    tags=["search"],
    summary="Search lecture descriptions and materials",
    response_model=SearchDocumentPage,
)
async def search_documents(
    q: str = Query(..., min_length=1, max_length=500),
    document_type: Literal["description", "material"] | None = Query(None),
    lecture_id: UUID | None = Query(None),
    content_type: Literal[
        "text", "presentation", "pdf", "video_link", "code_sample", "exercise"
    ]
    | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """Search only the document projection stored in Elasticsearch."""
    try:
        return await search_store.search(
            q,
            document_type=document_type,
            lecture_id=lecture_id,
            content_type=content_type,
            offset=offset,
            limit=limit,
        )
    except SearchUnavailable as exc:
        logger.warning("Elasticsearch document search failed", exc_info=True)
        raise HTTPException(
            503,
            {
                "code": "SEARCH_UNAVAILABLE",
                "message": "Document search is unavailable",
                "details": {},
            },
        ) from exc


@router.get(
    "/graph/stats",
    tags=["graph"],
    response_model=AcademicGraphStatsResponse,
)
async def graph_stats():
    """Return counts from the Neo4j academic structure projection."""
    try:
        return await academic_graph.stats()
    except GraphUnavailable as exc:
        raise HTTPException(
            503,
            {
                "code": "GRAPH_UNAVAILABLE",
                "message": "Academic graph is unavailable",
                "details": {},
            },
        ) from exc


@router.get(
    "/graph/universities/{university_id}",
    tags=["graph"],
    response_model=UniversityGraphResponse,
)
async def university_graph(university_id: UUID):
    """Return University -> Institute -> Department -> Specialty paths."""
    try:
        paths = await academic_graph.university_structure(university_id)
    except GraphUnavailable as exc:
        raise HTTPException(
            503,
            {
                "code": "GRAPH_UNAVAILABLE",
                "message": "Academic graph is unavailable",
                "details": {},
            },
        ) from exc
    if not paths:
        raise HTTPException(
            404,
            {
                "code": "UNIVERSITY_NOT_FOUND",
                "message": "University does not exist in the academic graph",
                "details": {"university_id": str(university_id)},
            },
        )
    return {"university_id": university_id, "paths": paths}
