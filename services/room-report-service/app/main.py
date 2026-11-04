from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

PAGE_SIZE = 100
URLS = {
    "schedule": os.getenv("SCHEDULE_SERVICE_URL", "http://schedule-service:8000"),
    "academic": os.getenv("ACADEMIC_SERVICE_URL", "http://academic-service:8000"),
    "students": os.getenv("STUDENT_SERVICE_URL", "http://student-service:8000"),
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(timeout=15) as client:
        app.state.client = client
        yield


app = FastAPI(
    title="Laboratory 2 Room Requirements", version="1.0.0", lifespan=lifespan
)


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID") or str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    detail = (
        exc.detail
        if isinstance(exc.detail, dict)
        else {"code": "HTTP_ERROR", "message": str(exc.detail), "details": {}}
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                **detail,
                "request_id": request.state.request_id,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": {},
                "request_id": request.state.request_id,
            }
        },
    )


def batches[T](values: Sequence[T]) -> Iterable[Sequence[T]]:
    for start in range(0, len(values), PAGE_SIZE):
        yield values[start : start + PAGE_SIZE]


async def get_json(request: Request, service: str, path: str, params: Any) -> dict:
    try:
        response = await request.app.state.client.get(
            f"{URLS[service]}{path}",
            params=params,
            headers={"X-Request-ID": request.state.request_id},
        )
        if response.status_code == 404:
            raise HTTPException(404, "Course not found")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Expected an object")
        return data
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            503,
            {
                "code": "DEPENDENCY_UNAVAILABLE",
                "message": f"{service} data unavailable",
                "details": {"service": service},
            },
        ) from exc


async def all_pages(
    request: Request, service: str, path: str, params: list[tuple[str, str]]
) -> list[dict]:
    items: list[dict] = []
    expected_total: int | None = None
    while True:
        page = await get_json(
            request,
            service,
            path,
            [*params, ("limit", "100"), ("offset", str(len(items)))],
        )
        page_items, total = page.get("items"), page.get("total")
        if not isinstance(page_items, list) or not isinstance(total, int):
            raise HTTPException(503, "Invalid dependency pagination")
        if expected_total is not None and total != expected_total:
            raise HTTPException(503, "Dependency data changed while building report")
        expected_total = total
        items.extend(page_items)
        if len(items) == total:
            return items
        if not page_items or len(items) > total:
            raise HTTPException(503, "Incomplete dependency pagination")


class RoomItem(BaseModel):
    lecture: dict[str, Any]
    listener_count: int
    required_seats: int
    technical_requirements: str


class RoomReport(BaseModel):
    course: dict[str, Any]
    semester: int
    study_year: int
    academic_year: int
    enrollment_year: int
    equipment_term: str | None
    audience_basis: str = (
        "active students of the course specialty and enrollment cohort"
    )
    groups: list[dict[str, Any]]
    listener_count: int
    required_seats: int
    items: list[RoomItem]


@app.get("/api/v1/reports/capacity", response_model=RoomReport, tags=["reports"])
async def capacity(
    request: Request,
    course_id: UUID,
    semester: int = Query(..., ge=1, le=12),
    study_year: int = Query(..., ge=1, le=6),
    academic_year: int = Query(..., ge=1900, le=9999),
    equipment_term: str | None = Query(None, min_length=1, max_length=500),
):
    if (semester + 1) // 2 != study_year:
        raise HTTPException(422, "Semester must belong to study_year (semesters 1..12)")
    if equipment_term is not None and not equipment_term.strip():
        raise HTTPException(422, "equipment_term must not be blank")
    course = await get_json(
        request, "academic", f"/api/v1/academic/courses/{course_id}", {}
    )
    if course["semester"] != semester:
        raise HTTPException(
            422, "Course semester does not match the requested semester"
        )
    enrollment_year = academic_year - study_year + 1
    groups = await all_pages(
        request,
        "students",
        "/api/v1/students/groups",
        [
            ("specialty_id", str(course["specialty_id"])),
            ("enrollment_year", str(enrollment_year)),
        ],
    )
    students = {}
    for batch in batches([str(g["id"]) for g in groups]):
        rows = await all_pages(
            request,
            "students",
            "/api/v1/students/students",
            [("group_ids", g) for g in batch] + [("status", "active")],
        )
        students.update({str(row["id"]): row for row in rows})
    lectures = await all_pages(
        request,
        "academic",
        "/api/v1/academic/lectures",
        [("course_id", str(course_id))],
    )
    items = []
    for lecture in sorted(lectures, key=lambda row: (row["order_number"], row["id"])):
        requirements = (lecture.get("requirements") or "").strip()
        if not requirements or (
            equipment_term
            and equipment_term.casefold().strip() not in requirements.casefold()
        ):
            continue
        items.append(
            RoomItem(
                lecture=lecture,
                listener_count=len(students),
                required_seats=len(students),
                technical_requirements=requirements,
            )
        )
    return RoomReport(
        course=course,
        semester=semester,
        study_year=study_year,
        academic_year=academic_year,
        enrollment_year=enrollment_year,
        equipment_term=equipment_term,
        groups=groups,
        listener_count=len(students),
        required_seats=len(students) if items else 0,
        items=items,
    )


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok"}


class ScheduledCourseItem(BaseModel):
    course: dict[str, Any]
    scheduled_lesson_count: int
    first_date: date
    last_date: date


class ScheduledCourses(BaseModel):
    year: int
    items: list[ScheduledCourseItem]


@app.get("/api/v1/reports/courses", response_model=ScheduledCourses, tags=["reports"])
async def scheduled_courses(
    request: Request,
    year: int = Query(
        ...,
        ge=1900,
        le=9999,
        description="Календарный год проведения занятий по расписанию",
    ),
    semester: int | None = Query(None, ge=1, le=12),
    study_year: int | None = Query(None, ge=1, le=6),
):
    if semester and study_year and (semester + 1) // 2 != study_year:
        raise HTTPException(422, "Semester does not belong to study_year")
    schedules = await all_pages(
        request,
        "schedule",
        "/api/v1/schedule",
        [
            ("date_from", f"{year}-01-01"),
            ("date_to", f"{year}-12-31"),
        ],
    )
    schedules = [row for row in schedules if row["status"] != "cancelled"]
    lectures = {}
    for batch in batches(sorted({str(row["lecture_id"]) for row in schedules})):
        rows = await all_pages(
            request,
            "academic",
            "/api/v1/academic/lectures",
            [("ids", value) for value in batch],
        )
        lectures.update({str(row["id"]): row for row in rows})
    courses = {}
    # One card per unique course, never one request per scheduled lesson.
    for course_id in sorted({str(row["course_id"]) for row in lectures.values()}):
        course = await get_json(
            request, "academic", f"/api/v1/academic/courses/{course_id}", {}
        )
        if semester and course["semester"] != semester:
            continue
        if study_year and (course["semester"] + 1) // 2 != study_year:
            continue
        courses[course_id] = course
    result = []
    for course_id, course in courses.items():
        dates = [
            row["scheduled_date"]
            for row in schedules
            if str(lectures.get(str(row["lecture_id"]), {}).get("course_id"))
            == course_id
        ]
        result.append(
            ScheduledCourseItem(
                course=course,
                scheduled_lesson_count=len(dates),
                first_date=min(dates),
                last_date=max(dates),
            )
        )
    return ScheduledCourses(
        year=year,
        items=sorted(result, key=lambda item: (item.course["name"], item.course["id"])),
    )
