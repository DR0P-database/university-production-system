from datetime import date, time
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    lecture_id: UUID
    group_id: UUID
    scheduled_date: date
    week_start_date: date
    start_time: time
    end_time: time
    classroom: str | None = Field(default=None, max_length=50)
    teacher_name: str | None = Field(default=None, max_length=300)
    status: Literal["scheduled", "completed", "cancelled"] = "scheduled"

    @model_validator(mode="after")
    def validate_schedule(self) -> Self:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        if self.week_start_date.isoweekday() != 1:
            raise ValueError("week_start_date must be a Monday")
        return self
