from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db import Base


class Attendance(Base):
    __tablename__ = "attendance"

    # PostgreSQL requires the partition key in every unique constraint.
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    # External UUIDs: schedule_db.schedule and student_db.students.
    schedule_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    week_start_date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_present: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    marked_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "schedule_id",
            "student_id",
            "week_start_date",
            name="uq_attendance_schedule_student_week",
        ),
        CheckConstraint(
            "EXTRACT(ISODOW FROM week_start_date) = 1",
            name="week_starts_on_monday",
        ),
        Index("ix_attendance_schedule_id", "schedule_id"),
        Index("ix_attendance_student_id", "student_id"),
        Index("ix_attendance_week_start_date", "week_start_date"),
        {"postgresql_partition_by": "RANGE (week_start_date)"},
    )
