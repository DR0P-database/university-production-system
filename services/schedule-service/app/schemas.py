from datetime import date, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    status: str = "scheduled"
