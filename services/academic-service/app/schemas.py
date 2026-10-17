from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    degree_level: Literal["bachelor", "master", "specialist"]
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

    @model_validator(mode="after")
    def validate_hours(self) -> Self:
        if self.lecture_hours + self.practice_hours + self.lab_hours > self.total_hours:
            raise ValueError("component hours must not exceed total_hours")
        return self


class LectureCreate(StrictModel):
    course_id: UUID
    title: str = Field(min_length=1, max_length=500)
    annotation: str | None = None
    lecture_type: Literal["lecture", "practice", "lab"]
    order_number: int = Field(gt=0)
    duration_minutes: int = Field(default=90, gt=0)
    requirements: str | None = None


class MaterialCreate(StrictModel):
    lecture_id: UUID
    content_type: Literal[
        "text", "presentation", "pdf", "video_link", "code_sample", "exercise"
    ]
    title: str | None = Field(default=None, max_length=500)
    content_text: str | None = None
    file_url: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        if not (self.content_text or self.file_url or self.metadata_json):
            raise ValueError("material must contain text, a file URL, or metadata")
        return self


class MaterialUpdate(StrictModel):
    lecture_id: UUID | None = None
    content_type: (
        Literal["text", "presentation", "pdf", "video_link", "code_sample", "exercise"]
        | None
    ) = None
    title: str | None = Field(default=None, max_length=500)
    content_text: str | None = None
    file_url: str | None = None
    metadata_json: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_non_empty_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one material field must be provided")
        return self


class RelationCreate(StrictModel):
    specialty_id: UUID
    is_primary: bool = False


class RelationUpdate(StrictModel):
    is_primary: bool


class TimestampedResponse(StrictModel):
    id: UUID
    created_at: datetime
    updated_at: datetime


class UniversityResponse(TimestampedResponse, UniversityCreate):
    pass


class InstituteResponse(TimestampedResponse, InstituteCreate):
    pass


class DepartmentResponse(TimestampedResponse, DepartmentCreate):
    pass


class SpecialtyResponse(TimestampedResponse, SpecialtyCreate):
    pass


class CourseResponse(TimestampedResponse, CourseCreate):
    pass


class LectureResponse(TimestampedResponse, LectureCreate):
    pass


class MaterialResponse(TimestampedResponse, MaterialCreate):
    """Public material assembled from PostgreSQL and MongoDB."""


class RelationResponse(RelationCreate):
    department_id: UUID
    created_at: datetime


class Page[ResponseItem](StrictModel):
    items: list[ResponseItem]
    limit: int
    offset: int
    total: int


class AcademicGraphStatsResponse(StrictModel):
    universities: int
    institutes: int
    departments: int
    specialties: int
    groups: int
    students: int
    schedules: int
    relationships: int


class UniversityGraphPath(StrictModel):
    university_id: UUID
    university_name: str
    institute_id: UUID | None = None
    institute_name: str | None = None
    department_id: UUID | None = None
    department_name: str | None = None
    specialty_id: UUID | None = None
    specialty_name: str | None = None


class UniversityGraphResponse(StrictModel):
    university_id: UUID
    paths: list[UniversityGraphPath]
