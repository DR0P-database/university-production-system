from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content_store import content_store
from app.models import Lecture, LectureCourse, LectureMaterial
from app.search_store import search_store

logger = logging.getLogger(__name__)


async def sync_lecture_projection(
    session: AsyncSession, lecture_id: UUID, *, strict: bool = False
) -> None:
    try:
        result = await session.execute(
            select(Lecture, LectureCourse.name)
            .join(LectureCourse, Lecture.course_id == LectureCourse.id)
            .where(Lecture.id == lecture_id)
        )
        row = result.one_or_none()
        if row is None:
            await search_store.delete(lecture_id)
            return

        lecture, course_name = row
        materials = list(
            await session.scalars(
                select(LectureMaterial)
                .where(LectureMaterial.lecture_id == lecture_id)
                .order_by(LectureMaterial.created_at, LectureMaterial.id)
            )
        )
        contents = await content_store.get_many([material.id for material in materials])
        content_text = "\n\n".join(
            str(contents[str(material.id)]["content_text"])
            for material in materials
            if contents.get(str(material.id), {}).get("content_text")
        )
        await search_store.put(
            lecture_id,
            {
                "title": lecture.title,
                "annotation": lecture.annotation,
                "content_text": content_text,
                "lecture_type": lecture.lecture_type,
                "course": course_name,
            },
        )
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
