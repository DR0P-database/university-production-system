from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AttendanceMark(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    week_start_date: date
    is_present: bool = False
    marked_at: datetime | None = None
    marked_by: UUID | None = None
    note: str | None = Field(default=None, max_length=500)

    @field_validator("week_start_date")
    @classmethod
    def validate_week_start(cls, value: date) -> date:
        if value.isoweekday() != 1:
            raise ValueError("week_start_date must be a Monday")
        return value


class AttendanceBatchMark(AttendanceMark):
    student_id: UUID
