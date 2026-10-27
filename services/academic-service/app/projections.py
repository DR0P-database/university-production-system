from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content_store import content_store
from app.models import Lecture, LectureMaterial
from app.search_store import search_store

logger = logging.getLogger(__name__)


async def sync_lecture_projection(
    session: AsyncSession, lecture_id: UUID, *, strict: bool = False
) -> None:
    try:
        lecture = await session.get(Lecture, lecture_id)
        if lecture is None:
            await search_store.delete(lecture_id)
            return

        materials = list(
            await session.scalars(
                select(LectureMaterial)
                .where(LectureMaterial.lecture_id == lecture_id)
                .order_by(LectureMaterial.created_at, LectureMaterial.id)
            )
        )
        contents = await content_store.get_many([material.id for material in materials])
        documents: list[tuple[str, dict[str, str]]] = []
        if lecture.annotation and lecture.annotation.strip():
            documents.append(
                (
                    f"description:{lecture.id}",
                    {
                        "document_type": "description",
                        "lecture_id": str(lecture.id),
                        "content": lecture.annotation,
                    },
                )
            )
        for material in materials:
            content_text = contents.get(str(material.id), {}).get("content_text")
            if not content_text or not str(content_text).strip():
                continue
            documents.append(
                (
                    f"material:{material.id}",
                    {
                        "document_type": "material",
                        "lecture_id": str(lecture.id),
                        "material_id": str(material.id),
                        "content_type": material.content_type,
                        "content": str(content_text),
                    },
                )
            )
        await search_store.replace_lecture_documents(lecture_id, documents)
    except Exception:
        logger.exception(
            "Could not synchronize lecture %s with Elasticsearch", lecture_id
        )
        if strict:
            raise


async def sync_course_projections(session: AsyncSession, course_id: UUID) -> None:
    lecture_ids = list(
        await session.scalars(select(Lecture.id).where(Lecture.course_id == course_id))
    )
    for lecture_id in lecture_ids:
        await sync_lecture_projection(session, lecture_id)


async def sync_all_lecture_projections(session: AsyncSession) -> None:
    lecture_ids = list(await session.scalars(select(Lecture.id)))
    for lecture_id in lecture_ids:
        await sync_lecture_projection(session, lecture_id, strict=True)
    await search_store.refresh()
