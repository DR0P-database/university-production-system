from __future__ import annotations

import uuid
from datetime import date, datetime, time

from sqlalchemy import CheckConstraint, Date, DateTime, Index, String, Time, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db import Base


class Schedule(Base):
    __tablename__ = "schedule"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    # External UUIDs: academic_db.lectures and student_db.student_groups.
    lecture_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    week_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    classroom: Mapped[str | None] = mapped_column(String(50))
    teacher_name: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'scheduled'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        CheckConstraint("end_time > start_time", name="time_range_valid"),
        CheckConstraint(
            "status IN ('scheduled', 'completed', 'cancelled')",
            name="status_allowed",
        ),
        CheckConstraint(
            "EXTRACT(ISODOW FROM week_start_date) = 1",
            name="week_starts_on_monday",
        ),
        Index("ix_schedule_lecture_id", "lecture_id"),
        Index("ix_schedule_scheduled_date", "scheduled_date"),
        Index("ix_schedule_week_start_date", "week_start_date"),
        Index("ix_schedule_group_date", "group_id", "scheduled_date"),
    )
