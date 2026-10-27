from __future__ import annotations

import os
from datetime import date, datetime, time
from typing import Any
from uuid import UUID

from neo4j import AsyncDriver, AsyncGraphDatabase
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Student, StudentGroup


class GraphUnavailable(RuntimeError):
    """Raised when the shared Neo4j projection cannot be reached."""


def graph_value(value: Any) -> Any:
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def row_properties(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {
        "id": str(row.id),
        **{field: graph_value(getattr(row, field)) for field in fields},
        "created_at": graph_value(row.created_at),
        "updated_at": graph_value(row.updated_at),
    }


class StudentGraphStore:
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
            for name, label in (
                ("graph_student_group_id", "StudentGroup"),
                ("graph_student_id", "Student"),
            ):
                await self._execute_write(
                    f"CREATE CONSTRAINT {name} IF NOT EXISTS "
                    f"FOR (node:{label}) REQUIRE node.id IS UNIQUE"
                )
            self._schema_ready = True
        except (DriverError, Neo4jError, OSError, ValueError) as exc:
            raise GraphUnavailable("Neo4j student projection is unavailable") from exc

    async def upsert_group(self, group: StudentGroup) -> None:
        if not self.enabled():
            return
        properties = row_properties(
            group,
            (
                "specialty_id",
                "department_id",
                "name",
                "enrollment_year",
                "curator",
            ),
        )
        await self._write(
            "MERGE (group:StudentGroup {id: $properties.id}) "
            "SET group += $properties "
            "WITH group "
            "OPTIONAL MATCH (:Department)-[old_department:HAS_GROUP]->(group) "
            "DELETE old_department "
            "WITH group "
            "OPTIONAL MATCH (group)-[old_specialty:STUDIES_SPECIALTY]->(:Specialty) "
            "DELETE old_specialty "
            "WITH group "
            "MERGE (department:Department {id: $department_id}) "
            "MERGE (specialty:Specialty {id: $specialty_id}) "
            "MERGE (department)-[:HAS_GROUP]->(group) "
            "MERGE (group)-[:STUDIES_SPECIALTY]->(specialty)",
            properties=properties,
            department_id=str(group.department_id),
            specialty_id=str(group.specialty_id),
        )

    async def upsert_student(self, student: Student) -> None:
        if not self.enabled():
            return
        properties = row_properties(
            student,
            (
                "group_id",
                "first_name",
                "last_name",
                "patronymic",
                "email",
                "phone",
                "student_card_number",
                "enrollment_date",
                "status",
            ),
        )
        await self._write(
            "MERGE (student:Student {id: $properties.id}) "
            "SET student += $properties "
            "WITH student "
            "OPTIONAL MATCH (:StudentGroup)-[old:HAS_STUDENT]->(student) "
            "DELETE old "
            "WITH student "
            "MERGE (group:StudentGroup {id: $group_id}) "
            "MERGE (group)-[:HAS_STUDENT]->(student)",
            properties=properties,
            group_id=str(student.group_id),
        )

    async def delete_entity(self, label: str, item_id: UUID) -> None:
        if not self.enabled():
            return
        if label not in {"Student", "StudentGroup"}:
            raise ValueError("Unsupported student graph label")
        await self._write(
            f"MATCH (node:{label} {{id: $item_id}}) DETACH DELETE node",
            item_id=str(item_id),
        )

    async def rebuild(self, db_session: AsyncSession) -> None:
        if not self.enabled():
            return
        groups = list(await db_session.scalars(select(StudentGroup)))
        students = list(await db_session.scalars(select(Student)))
        await self.ensure_schema()
        for group in groups:
            await self.upsert_group(group)
        for student in students:
            await self.upsert_student(student)
        try:
            for label, rows in (("Student", students), ("StudentGroup", groups)):
                await self._write(
                    f"MATCH (node:{label}) WHERE NOT node.id IN $ids "
                    "DETACH DELETE node",
                    ids=[str(row.id) for row in rows],
                )
        except (DriverError, Neo4jError, OSError, ValueError) as exc:
            raise GraphUnavailable("Neo4j student projection is unavailable") from exc

    async def university_students(
        self, university_id: UUID, offset: int, limit: int
    ) -> dict[str, Any] | None:
        if not self.enabled():
            raise GraphUnavailable("Neo4j student projection is disabled")
        count_query = """
        MATCH (university:University {id: $university_id})
        OPTIONAL MATCH (university)-[:HAS_INSTITUTE]->(:Institute)
                     -[:HAS_DEPARTMENT]->(:Department)
                     -[:HAS_GROUP]->(:StudentGroup)
                     -[:HAS_STUDENT]->(student:Student)
        RETURN university.name AS university_name,
               count(DISTINCT student) AS total
        """
        items_query = """
        MATCH (university:University {id: $university_id})
              -[:HAS_INSTITUTE]->(institute:Institute)
              -[:HAS_DEPARTMENT]->(department:Department)
              -[:HAS_GROUP]->(group:StudentGroup)
              -[:HAS_STUDENT]->(student:Student)
        OPTIONAL MATCH (group)-[:STUDIES_SPECIALTY]->(specialty:Specialty)
        WITH DISTINCT student, group, specialty, department, institute, university
        RETURN properties(student) AS student,
               properties(group) AS group,
               properties(specialty) AS specialty,
               properties(department) AS department,
               properties(institute) AS institute,
               properties(university) AS university
        ORDER BY student.last_name, student.first_name, student.id
        SKIP $offset LIMIT $limit
        """
        try:
            async with self.driver().session() as session:
                count_cursor = await session.run(
                    count_query, university_id=str(university_id)
                )
                count_record = await count_cursor.single()
                if count_record is None or count_record["university_name"] is None:
                    return None
                cursor = await session.run(
                    items_query,
                    university_id=str(university_id),
                    offset=offset,
                    limit=limit,
                )
                return {
                    "items": [record.data() async for record in cursor],
                    "limit": limit,
                    "offset": offset,
                    "total": int(count_record["total"]),
                }
        except (DriverError, Neo4jError, OSError, ValueError) as exc:
            raise GraphUnavailable("Neo4j student projection is unavailable") from exc

    async def student_context(self, student_id: UUID) -> dict[str, Any] | None:
        if not self.enabled():
            raise GraphUnavailable("Neo4j student projection is disabled")
        query = """
        MATCH (student:Student {id: $student_id})
        MATCH (group:StudentGroup)-[:HAS_STUDENT]->(student)
        MATCH (department:Department)-[:HAS_GROUP]->(group)
        MATCH (institute:Institute)-[:HAS_DEPARTMENT]->(department)
        MATCH (university:University)-[:HAS_INSTITUTE]->(institute)
        OPTIONAL MATCH (group)-[:STUDIES_SPECIALTY]->(specialty:Specialty)
        RETURN properties(student) AS student,
               properties(group) AS group,
               properties(specialty) AS specialty,
               properties(department) AS department,
               properties(institute) AS institute,
               properties(university) AS university
        LIMIT 1
        """
        try:
            async with self.driver().session() as session:
                cursor = await session.run(query, student_id=str(student_id))
                record = await cursor.single()
                return record.data() if record else None
        except (DriverError, Neo4jError, OSError, ValueError) as exc:
            raise GraphUnavailable("Neo4j student projection is unavailable") from exc

    async def _write(self, query: str, **parameters: Any) -> None:
        try:
            await self.ensure_schema()
            await self._execute_write(query, **parameters)
        except (DriverError, Neo4jError, OSError, ValueError) as exc:
            raise GraphUnavailable("Neo4j student projection is unavailable") from exc

    async def _execute_write(self, query: str, **parameters: Any) -> None:
        async def run(transaction: Any) -> None:
            result = await transaction.run(query, **parameters)
            await result.consume()

        async with self.driver().session() as session:
            await session.execute_write(run)

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None
            self._schema_ready = False


student_graph = StudentGraphStore()
