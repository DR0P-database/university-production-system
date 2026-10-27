from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from neo4j import AsyncDriver, AsyncGraphDatabase
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Department,
    DepartmentSpecialty,
    Institute,
    Specialty,
    University,
)


class GraphUnavailable(RuntimeError):
    """Raised when the academic Neo4j projection cannot be reached."""


ENTITY_CONFIG: dict[type[Any], tuple[str, str | None, str | None, tuple[str, ...]]] = {
    University: (
        "University",
        None,
        None,
        ("name", "short_name", "address", "website", "founded_year"),
    ),
    Institute: (
        "Institute",
        "University",
        "HAS_INSTITUTE",
        ("name", "short_name", "dean"),
    ),
    Department: (
        "Department",
        "Institute",
        "HAS_DEPARTMENT",
        ("name", "short_name", "head", "room"),
    ),
    Specialty: (
        "Specialty",
        None,
        None,
        ("name", "code", "degree_level", "duration_years"),
    ),
}

PARENT_FIELDS: dict[type[Any], str] = {
    Institute: "university_id",
    Department: "institute_id",
}

CONSTRAINT_LABELS = ("University", "Institute", "Department", "Specialty")


class AcademicGraphStore:
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
            for constraint in (
                "student_projection_id",
                "lecture_projection_id",
                "academic_course_id",
                "academic_lecture_id",
            ):
                await self._execute_write(
                    f"DROP CONSTRAINT {constraint} IF EXISTS"
                )
            for label in CONSTRAINT_LABELS:
                await self._execute_write(
                    f"CREATE CONSTRAINT academic_{label.lower()}_id IF NOT EXISTS "
                    f"FOR (node:{label}) REQUIRE node.id IS UNIQUE"
                )
            self._schema_ready = True
        except (DriverError, Neo4jError, OSError, ValueError) as exc:
            raise GraphUnavailable("Neo4j academic projection is unavailable") from exc

    @staticmethod
    def _properties(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
        return {
            "id": str(row.id),
            **{field: getattr(row, field) for field in fields},
        }

    async def upsert_entity(self, row: Any) -> None:
        if not self.enabled():
            return
        model = type(row)
        if model not in ENTITY_CONFIG:
            return
        label, parent_label, relationship, fields = ENTITY_CONFIG[model]
        properties = self._properties(row, fields)
        query = f"MERGE (node:{label} {{id: $properties.id}}) SET node += $properties"
        parameters: dict[str, Any] = {"properties": properties}
        if parent_label and relationship:
            parent_id = str(getattr(row, PARENT_FIELDS[model]))
            query += (
                f" WITH node OPTIONAL MATCH (old:{parent_label})-[old_rel:{relationship}]->(node)"
                " DELETE old_rel WITH node"
                f" MERGE (parent:{parent_label} {{id: $parent_id}})"
                f" MERGE (parent)-[:{relationship}]->(node)"
            )
            parameters["parent_id"] = parent_id
        await self._write(query, **parameters)

    async def delete_entity(self, model: type[Any], item_id: UUID) -> None:
        if not self.enabled():
            return
        if model not in ENTITY_CONFIG:
            return
        label = ENTITY_CONFIG[model][0]
        query = f"MATCH (node:{label} {{id: $item_id}}) DETACH DELETE node"
        await self._write(query, item_id=str(item_id))

    async def upsert_department_specialty(
        self, department_id: UUID, specialty_id: UUID, is_primary: bool
    ) -> None:
        if not self.enabled():
            return
        await self._write(
            "MERGE (department:Department {id: $department_id}) "
            "MERGE (specialty:Specialty {id: $specialty_id}) "
            "MERGE (department)-[relation:OFFERS_SPECIALTY]->(specialty) "
            "SET relation.is_primary = $is_primary",
            department_id=str(department_id),
            specialty_id=str(specialty_id),
            is_primary=is_primary,
        )

    async def delete_department_specialty(
        self, department_id: UUID, specialty_id: UUID
    ) -> None:
        if not self.enabled():
            return
        await self._write(
            "MATCH (:Department {id: $department_id})"
            "-[relation:OFFERS_SPECIALTY]->"
            "(:Specialty {id: $specialty_id}) DELETE relation",
            department_id=str(department_id),
            specialty_id=str(specialty_id),
        )

    async def rebuild(self, db_session: AsyncSession) -> None:
        """Synchronize the academic-owned part of the shared Neo4j graph."""
        if not self.enabled():
            return
        entities = {
            model: list(await db_session.scalars(select(model)))
            for model in ENTITY_CONFIG
        }
        relations = list(await db_session.scalars(select(DepartmentSpecialty)))
        try:
            await self.ensure_schema()
            await self._write(
                "MATCH (node) WHERE node:Attendance OR node:Course OR node:Lecture "
                "DETACH DELETE node"
            )
            await self._write(
                "MATCH (:Department)-[relation:OFFERS_SPECIALTY]->(:Specialty) "
                "DELETE relation"
            )
            for _model, rows in entities.items():
                for row in rows:
                    await self.upsert_entity(row)
            for relation in relations:
                await self.upsert_department_specialty(
                    relation.department_id,
                    relation.specialty_id,
                    relation.is_primary,
                )
            for model, rows in entities.items():
                label = ENTITY_CONFIG[model][0]
                await self._write(
                    f"MATCH (node:{label}) WHERE NOT node.id IN $ids "
                    "DETACH DELETE node",
                    ids=[str(row.id) for row in rows],
                )
        except (DriverError, Neo4jError, OSError, ValueError) as exc:
            raise GraphUnavailable("Neo4j academic projection is unavailable") from exc

    async def stats(self) -> dict[str, int]:
        if not self.enabled():
            raise GraphUnavailable("Neo4j academic projection is disabled")
        labels = {
            "universities": "University",
            "institutes": "Institute",
            "departments": "Department",
            "specialties": "Specialty",
            "groups": "StudentGroup",
            "students": "Student",
            "schedules": "Schedule",
        }
        queries = {
            name: f"MATCH (node:{label}) RETURN count(node) AS total"
            for name, label in labels.items()
        }
        queries["relationships"] = (
            "MATCH ()-[relation]->() RETURN count(relation) AS total"
        )
        try:
            result: dict[str, int] = {}
            async with self.driver().session() as graph_session:
                for name, query in queries.items():
                    cursor = await graph_session.run(query)
                    record = await cursor.single()
                    result[name] = int(record["total"]) if record else 0
            return result
        except (DriverError, Neo4jError, OSError, ValueError) as exc:
            raise GraphUnavailable("Neo4j academic projection is unavailable") from exc

    async def university_structure(self, university_id: UUID) -> list[dict[str, Any]]:
        if not self.enabled():
            raise GraphUnavailable("Neo4j academic projection is disabled")
        query = """
        MATCH (university:University {id: $university_id})
        OPTIONAL MATCH (university)-[:HAS_INSTITUTE]->(institute:Institute)
                       -[:HAS_DEPARTMENT]->(department:Department)
                       -[:OFFERS_SPECIALTY]->(specialty:Specialty)
        RETURN university.id AS university_id,
               university.name AS university_name,
               institute.id AS institute_id,
               institute.name AS institute_name,
               department.id AS department_id,
               department.name AS department_name,
               specialty.id AS specialty_id,
               specialty.name AS specialty_name
        ORDER BY institute.name, department.name, specialty.name
        """
        try:
            async with self.driver().session() as graph_session:
                cursor = await graph_session.run(
                    query, university_id=str(university_id)
                )
                return [record.data() async for record in cursor]
        except (DriverError, Neo4jError, OSError, ValueError) as exc:
            raise GraphUnavailable("Neo4j academic projection is unavailable") from exc

    async def _write(self, query: str, **parameters: Any) -> None:
        try:
            await self.ensure_schema()
            await self._execute_write(query, **parameters)
        except (DriverError, Neo4jError, OSError, ValueError) as exc:
            raise GraphUnavailable("Neo4j academic projection is unavailable") from exc

    async def _execute_write(self, query: str, **parameters: Any) -> None:
        async def run(transaction: Any) -> None:
            result = await transaction.run(query, **parameters)
            await result.consume()

        async with self.driver().session() as graph_session:
            await graph_session.execute_write(run)

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None
            self._schema_ready = False


academic_graph = AcademicGraphStore()
