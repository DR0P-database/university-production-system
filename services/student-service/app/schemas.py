from datetime import date, datetime
from typing import Literal
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
    status: Literal["active", "academic_leave", "expelled", "graduated"] = "active"


class GroupResponse(GroupCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime


class StudentResponse(StudentCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime


class UniversityGraphNode(StrictModel):
    id: UUID
    name: str
    short_name: str | None = None
    address: str | None = None
    website: str | None = None
    founded_year: int | None = None


class InstituteGraphNode(StrictModel):
    id: UUID
    name: str
    short_name: str | None = None
    dean: str | None = None


class DepartmentGraphNode(StrictModel):
    id: UUID
    name: str
    short_name: str | None = None
    head: str | None = None
    room: str | None = None


class SpecialtyGraphNode(StrictModel):
    id: UUID
    name: str
    code: str
    degree_level: Literal["bachelor", "master", "specialist"]
    duration_years: int


class StudentGraphResponse(StrictModel):
    student: StudentResponse
    group: GroupResponse
    specialty: SpecialtyGraphNode
    department: DepartmentGraphNode
    institute: InstituteGraphNode
    university: UniversityGraphNode


class GraphPage[Item](StrictModel):
    items: list[Item]
    limit: int
    offset: int
    total: int
