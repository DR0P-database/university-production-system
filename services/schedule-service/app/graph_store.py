from __future__ import annotations

import os
from datetime import date, datetime, time
from typing import Any
from uuid import UUID

from neo4j import AsyncDriver, AsyncGraphDatabase
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Schedule


class GraphUnavailable(RuntimeError):
    """Raised when the shared Neo4j projection cannot be reached."""


def graph_value(value: Any) -> Any:
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def schedule_properties(schedule: Schedule) -> dict[str, Any]:
    fields = (
        "lecture_id",
        "group_id",
        "scheduled_date",
        "week_start_date",
        "start_time",
        "end_time",
        "classroom",
        "teacher_name",
        "status",
        "created_at",
        "updated_at",
    )
    return {
        "id": str(schedule.id),
        **{field: graph_value(getattr(schedule, field)) for field in fields},
    }


class ScheduleGraphStore:
    def __init__(self) -> None:
        self._driver: AsyncDriver | None = None
        self._schema_ready = False

    def enabled(self) -> bool:
        return os.getenv("NEO4J_ENABLED", "false").lower() in {"1", "true", "yes"}

    def driver(self) -> AsyncDriver:
        if self._driver is None:
            self._driver = AsyncGraphDatabase.driver(
                os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
                auth=(
                    os.getenv("NEO4J_USER", "neo4j"),
                    os.getenv("NEO4J_PASSWORD", ""),
                ),
                connection_timeout=2,
            )
        return self._driver

    async def ensure_schema(self) -> None:
        if self._schema_ready or not self.enabled():
            return
        try:
            async with self.driver().session() as session:
                result = await session.run(
                    "CREATE CONSTRAINT graph_schedule_id IF NOT EXISTS "
                    "FOR (node:Schedule) REQUIRE node.id IS UNIQUE"
                )
                await result.consume()
            self._schema_ready = True
        except (DriverError, Neo4jError, OSError, ValueError) as exc:
            raise GraphUnavailable("Neo4j schedule projection is unavailable") from exc

    async def upsert(self, schedule: Schedule) -> None:
        if not self.enabled():
            return
        await self._write(
            "MERGE (schedule:Schedule {id: $properties.id}) "
            "SET schedule += $properties "
            "WITH schedule "
            "OPTIONAL MATCH (:StudentGroup)-[old:HAS_SCHEDULE]->(schedule) "
            "DELETE old "
            "WITH schedule "
            "MERGE (group:StudentGroup {id: $group_id}) "
            "MERGE (group)-[:HAS_SCHEDULE]->(schedule)",
            properties=schedule_properties(schedule),
            group_id=str(schedule.group_id),
        )

    async def delete(self, schedule_id: UUID) -> None:
        if not self.enabled():
            return
        await self._write(
            "MATCH (schedule:Schedule {id: $schedule_id}) DETACH DELETE schedule",
            schedule_id=str(schedule_id),
        )

    async def rebuild(self, db_session: AsyncSession) -> None:
        if not self.enabled():
            return
        schedules = list(await db_session.scalars(select(Schedule)))
        await self.ensure_schema()
        for schedule in schedules:
            await self.upsert(schedule)
        try:
            async with self.driver().session() as session:
                result = await session.run(
                    "MATCH (schedule:Schedule) WHERE NOT schedule.id IN $ids "
                    "DETACH DELETE schedule",
                    ids=[str(schedule.id) for schedule in schedules],
                )
                await result.consume()
        except (DriverError, Neo4jError, OSError, ValueError) as exc:
            raise GraphUnavailable("Neo4j schedule projection is unavailable") from exc

    async def student_schedule(
        self,
        student_id: UUID,
        *,
        status: str | None,
        date_from: date | None,
        date_to: date | None,
        offset: int,
        limit: int,
    ) -> dict[str, Any] | None:
        if not self.enabled():
            raise GraphUnavailable("Neo4j schedule projection is disabled")
        match = """
        MATCH (student:Student {id: $student_id})
        MATCH (group:StudentGroup)-[:HAS_STUDENT]->(student)
        OPTIONAL MATCH (group)-[:HAS_SCHEDULE]->(schedule:Schedule)
        WITH student, group, schedule
        WHERE schedule IS NULL OR (
            ($status IS NULL OR schedule.status = $status) AND
            ($date_from IS NULL OR schedule.scheduled_date >= $date_from) AND
            ($date_to IS NULL OR schedule.scheduled_date <= $date_to)
        )
        """
        count_query = match + "RETURN count(schedule) AS total"
        items_query = (
            match
            + """
        WITH schedule WHERE schedule IS NOT NULL
        RETURN properties(schedule) AS schedule
        ORDER BY schedule.scheduled_date, schedule.start_time, schedule.id
        SKIP $offset LIMIT $limit
        """
        )
        parameters = {
            "student_id": str(student_id),
            "status": status,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "offset": offset,
            "limit": limit,
        }
        try:
            async with self.driver().session() as session:
                exists_cursor = await session.run(
                    "MATCH (student:Student {id: $student_id}) RETURN student.id AS id",
                    student_id=str(student_id),
                )
                if await exists_cursor.single() is None:
                    return None
                count_cursor = await session.run(count_query, **parameters)
                count_record = await count_cursor.single()
                cursor = await session.run(items_query, **parameters)
                return {
                    "items": [record["schedule"] async for record in cursor],
                    "limit": limit,
                    "offset": offset,
                    "total": int(count_record["total"]) if count_record else 0,
                }
        except (DriverError, Neo4jError, OSError, ValueError) as exc:
            raise GraphUnavailable("Neo4j schedule projection is unavailable") from exc

    async def _write(self, query: str, **parameters: Any) -> None:
        try:
            await self.ensure_schema()
            async with self.driver().session() as session:
                result = await session.run(query, **parameters)
                await result.consume()
        except (DriverError, Neo4jError, OSError, ValueError) as exc:
            raise GraphUnavailable("Neo4j schedule projection is unavailable") from exc

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None
            self._schema_ready = False


schedule_graph = ScheduleGraphStore()
