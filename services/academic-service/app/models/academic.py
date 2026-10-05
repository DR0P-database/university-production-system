from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class University(TimestampMixin, Base):
    __tablename__ = "universities"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(255))
    founded_year: Mapped[int | None] = mapped_column(SmallInteger)

    institutes: Mapped[list[Institute]] = relationship(back_populates="university")

    __table_args__ = (
        CheckConstraint(
            "founded_year IS NULL OR founded_year > 0",
            name="founded_year_positive",
        ),
    )


class Institute(TimestampMixin, Base):
    __tablename__ = "institutes"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    university_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("universities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(100))
    dean: Mapped[str | None] = mapped_column(String(300))

    university: Mapped[University] = relationship(back_populates="institutes")
    departments: Mapped[list[Department]] = relationship(back_populates="institute")

    __table_args__ = (Index("ix_institutes_university_id", "university_id"),)


class Department(TimestampMixin, Base):
    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    institute_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("institutes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(100))
    head: Mapped[str | None] = mapped_column(String(300))
    room: Mapped[str | None] = mapped_column(String(50))

    institute: Mapped[Institute] = relationship(back_populates="departments")
    specialties: Mapped[list[DepartmentSpecialty]] = relationship(
        back_populates="department", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_departments_institute_id", "institute_id"),)


class Specialty(TimestampMixin, Base):
    __tablename__ = "specialties"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    degree_level: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_years: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    departments: Mapped[list[DepartmentSpecialty]] = relationship(
        back_populates="specialty", cascade="all, delete-orphan"
    )
    lecture_courses: Mapped[list[LectureCourse]] = relationship(
        back_populates="specialty"
    )

    __table_args__ = (
        CheckConstraint(
            "degree_level IN ('bachelor', 'master', 'specialist')",
            name="degree_level_allowed",
        ),
        CheckConstraint("duration_years > 0", name="duration_years_positive"),
    )


class DepartmentSpecialty(Base):
    __tablename__ = "department_specialties"

    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    specialty_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("specialties.id", ondelete="CASCADE"),
        primary_key=True,
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    department: Mapped[Department] = relationship(back_populates="specialties")
    specialty: Mapped[Specialty] = relationship(back_populates="departments")

    __table_args__ = (
        Index("ix_department_specialties_specialty_id", "specialty_id"),
        Index(
            "uq_specialty_primary_department",
            "specialty_id",
            unique=True,
            postgresql_where=text("is_primary = true"),
        ),
    )


class LectureCourse(TimestampMixin, Base):
    __tablename__ = "lecture_courses"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    specialty_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("specialties.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    semester: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    total_hours: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    lecture_hours: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    practice_hours: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    lab_hours: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )

    specialty: Mapped[Specialty] = relationship(back_populates="lecture_courses")
    lectures: Mapped[list[Lecture]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("semester BETWEEN 1 AND 12", name="semester_valid"),
        CheckConstraint("total_hours >= 0", name="total_hours_nonnegative"),
        CheckConstraint("lecture_hours >= 0", name="lecture_hours_nonnegative"),
        CheckConstraint("practice_hours >= 0", name="practice_hours_nonnegative"),
        CheckConstraint("lab_hours >= 0", name="lab_hours_nonnegative"),
        CheckConstraint(
            "lecture_hours + practice_hours + lab_hours <= total_hours",
            name="hours_sum_valid",
        ),
        Index("ix_lecture_courses_specialty_id", "specialty_id"),
    )


class Lecture(TimestampMixin, Base):
    __tablename__ = "lectures"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("lecture_courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    annotation: Mapped[str | None] = mapped_column(Text)
    lecture_type: Mapped[str] = mapped_column(String(20), nullable=False)
    order_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("90")
    )
    requirements: Mapped[str | None] = mapped_column(Text)

    course: Mapped[LectureCourse] = relationship(back_populates="lectures")
    materials: Mapped[list[LectureMaterial]] = relationship(
        back_populates="lecture", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "lecture_type IN ('lecture', 'practice', 'lab')",
            name="lecture_type_allowed",
        ),
        CheckConstraint("order_number > 0", name="order_number_positive"),
        CheckConstraint("duration_minutes > 0", name="duration_positive"),
        UniqueConstraint("course_id", "order_number", name="uq_lecture_course_order"),
    )


class LectureMaterial(TimestampMixin, Base):
    __tablename__ = "lecture_materials"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    lecture_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("lectures.id", ondelete="CASCADE"),
        nullable=False,
    )
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    content_text: Mapped[str | None] = mapped_column(Text)
    file_url: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    lecture: Mapped[Lecture] = relationship(back_populates="materials")

    __table_args__ = (
        CheckConstraint(
            "content_type IN ('text', 'presentation', 'pdf', 'video_link', 'code_sample', 'exercise')",
            name="content_type_allowed",
        ),
        CheckConstraint(
            "content_text IS NOT NULL OR file_url IS NOT NULL OR metadata <> '{}'::jsonb",
            name="material_has_content",
        ),
        Index("ix_lecture_materials_lecture_id", "lecture_id"),
    )
