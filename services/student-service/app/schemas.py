from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class GroupCreate(StrictModel):
    specialty_id: UUID
    department_id: UUID
    name: str = Field(min_length=1, max_length=50)
    enrollment_year: int = Field(gt=0)
    curator: str | None = Field(default=None, max_length=300)


class StudentCreate(StrictModel):
    group_id: UUID
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    patronymic: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=30)
    student_card_number: str | None = Field(default=None, max_length=50)
    enrollment_date: date
    status: str = "active"
