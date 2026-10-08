from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class UniversityCreate(StrictModel):
    name: str = Field(min_length=1, max_length=500)
    short_name: str | None = Field(default=None, max_length=100)
    address: str | None = None
    website: str | None = Field(default=None, max_length=255)
    founded_year: int | None = Field(default=None, gt=0)


class InstituteCreate(StrictModel):
    university_id: UUID
    name: str = Field(min_length=1, max_length=500)
    short_name: str | None = Field(default=None, max_length=100)
    dean: str | None = Field(default=None, max_length=300)


class DepartmentCreate(StrictModel):
    institute_id: UUID
    name: str = Field(min_length=1, max_length=500)
    short_name: str | None = Field(default=None, max_length=100)
    head: str | None = Field(default=None, max_length=300)
    room: str | None = Field(default=None, max_length=50)


class SpecialtyCreate(StrictModel):
    name: str = Field(min_length=1, max_length=500)
    code: str = Field(min_length=1, max_length=20)
    degree_level: str
    duration_years: int = Field(gt=0)


class CourseCreate(StrictModel):
    specialty_id: UUID
    name: str = Field(min_length=1, max_length=500)
    description: str | None = None
    semester: int = Field(ge=1, le=12)
    total_hours: int = Field(ge=0)
    lecture_hours: int = Field(default=0, ge=0)
    practice_hours: int = Field(default=0, ge=0)
    lab_hours: int = Field(default=0, ge=0)


class LectureCreate(StrictModel):
    course_id: UUID
    title: str = Field(min_length=1, max_length=500)
    annotation: str | None = None
    lecture_type: str
    order_number: int = Field(gt=0)
    duration_minutes: int = Field(default=90, gt=0)
    requirements: str | None = None


class MaterialCreate(StrictModel):
    lecture_id: UUID
    content_type: str
    title: str | None = Field(default=None, max_length=500)
    content_text: str | None = None
    file_url: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class RelationCreate(StrictModel):
    specialty_id: UUID
    is_primary: bool = False


class RelationUpdate(StrictModel):
    is_primary: bool
