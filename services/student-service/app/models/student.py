from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, SmallInteger, String, text
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


class StudentGroup(TimestampMixin, Base):
    __tablename__ = "student_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    # External UUIDs: academic_db.specialties and academic_db.departments.
    specialty_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    department_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    enrollment_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    curator: Mapped[str | None] = mapped_column(String(300))

    students: Mapped[list[Student]] = relationship(back_populates="group")

    __table_args__ = (
        CheckConstraint("enrollment_year > 0", name="enrollment_year_positive"),
        Index("ix_student_groups_specialty_id", "specialty_id"),
        Index("ix_student_groups_department_id", "department_id"),
    )


class Student(TimestampMixin, Base):
    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("student_groups.id", ondelete="RESTRICT"),
        nullable=False,
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    patronymic: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    phone: Mapped[str | None] = mapped_column(String(30))
    student_card_number: Mapped[str | None] = mapped_column(String(50), unique=True)
    enrollment_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'active'")
    )

    group: Mapped[StudentGroup] = relationship(back_populates="students")

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'academic_leave', 'expelled', 'graduated')",
            name="status_allowed",
        ),
        Index("ix_students_group_id", "group_id"),
    )
