from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AttendanceMark(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    week_start_date: date
    is_present: bool = False
    marked_at: datetime | None = None
    marked_by: UUID | None = None
    note: str | None = Field(default=None, max_length=500)


class AttendanceBatchMark(AttendanceMark):
    student_id: UUID
