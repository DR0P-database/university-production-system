from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from fractions import Fraction
from typing import Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

PAGE_SIZE = 100
URLS = {
    "academic": os.getenv("ACADEMIC_SERVICE_URL", "http://academic-service:8000"),
    "students": os.getenv("STUDENT_SERVICE_URL", "http://student-service:8000"),
    "schedule": os.getenv("SCHEDULE_SERVICE_URL", "http://schedule-service:8000"),
    "attendance": os.getenv("ATTENDANCE_SERVICE_URL", "http://attendance-service:8000"),
}


class Student(BaseModel):
    id: UUID
    group_id: UUID
    first_name: str
    last_name: str
    patronymic: str | None = None
    email: str | None = None
    phone: str | None = None
    student_card_number: str | None = None
    enrollment_date: date
    status: str
    created_at: datetime
    updated_at: datetime


class Group(BaseModel):
    id: UUID
    name: str
    specialty_id: UUID
    department_id: UUID
    enrollment_year: int
    curator: str | None = None
    created_at: datetime
    updated_at: datetime


class ReportItem(BaseModel):
    student: Student
    group: Group
    attendance_percent: float
    attended_count: int
    lecture_count: int


class AttendanceReport(BaseModel):
    term: str
    search_mode: Literal["phrase", "words"]
    date_from: date
    date_to: date
    timezone: str
    items: list[ReportItem] = Field(max_length=10)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(timeout=15) as client:
        app.state.client = client
        yield


app = FastAPI(
    title="Laboratory 1 Reports",
    version="1.0.0",
    openapi_tags=[
        {
            "name": "Лабораторная 1",
            "description": "Посещаемость лекций: десять студентов с минимальным процентом посещений по заданному термину и периоду.",
        }
    ],
    lifespan=lifespan,
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


async def find_lecture_ids(request: Request, term: str, mode: str) -> list[str]:
    ids: set[str] = set()
    cursor = None
    while True:
        params = {"q": term, "search_mode": mode, "limit": PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        page = await get_json(
            request, "academic", "/api/v1/academic/search/lectures", params
        )
        page_ids = page.get("items")
        if not isinstance(page_ids, list):
            raise HTTPException(503, "Invalid search results")
        ids.update(page_ids)
        next_cursor = page.get("next_cursor")
        if next_cursor is None:
            return sorted(ids)
        if not page_ids or next_cursor == cursor:
            raise HTTPException(503, "Invalid search cursor")
        cursor = next_cursor


@app.get(
    "/api/v1/reports/lowest-attendance",
    response_model=AttendanceReport,
    tags=["Лабораторная 1"],
    summary="10 студентов с наименьшей посещаемостью лекций",
    description=(
        "Находит лекции по термину или фразе в аннотациях и материалах. "
        "Для завершённых занятий за указанный период рассчитывает посещаемость "
        "и возвращает до десяти студентов с минимальным процентом. "
        "В ответе — полные карточки студента и группы, количество занятий, "
        "посещений и процент. Отсутствие отметки считается пропуском. "
        "Можно ограничить выборку кафедрой, специальностью, группой и предметом (course_id)."
    ),
)
async def lowest_attendance(
    request: Request,
    term: str = Query(..., min_length=1, max_length=500),
    date_from: date = Query(...),
    date_to: date = Query(...),
    search_mode: Literal["phrase", "words"] = "words",
    department_id: UUID | None = None,
    specialty_id: UUID | None = None,
    group_id: UUID | None = None,
    course_id: UUID | None = None,
):
    if not term.strip() or date_from > date_to:
        raise HTTPException(
            422, "Term must not be blank and date_from must not exceed date_to"
        )
    timezone = os.getenv("REPORT_TIMEZONE", "Europe/Moscow")
    now = datetime.now(ZoneInfo(timezone))
    today = now.date()
    report = AttendanceReport(
        term=term,
        search_mode=search_mode,
        date_from=date_from,
        date_to=date_to,
        timezone=timezone,
        items=[],
    )
    end = min(date_to, today)
    if end < date_from:
        return report

    ids = await find_lecture_ids(request, term, search_mode)
    lecture_ids: list[str] = []
    for batch in batches(ids):
        params = [("ids", value) for value in batch] + [("lecture_type", "lecture")]
        if course_id:
            params.append(("course_id", str(course_id)))
        rows = await all_pages(request, "academic", "/api/v1/academic/lectures", params)
        lecture_ids.extend(str(row["id"]) for row in rows)
    if not lecture_ids:
        return report

    schedules: list[dict] = []
    for batch in batches(lecture_ids):
        params = [("lecture_ids", value) for value in batch] + [
            ("status", "completed"),
            ("date_from", str(date_from)),
            ("date_to", str(end)),
        ]
        if group_id:
            params.append(("group_id", str(group_id)))
        schedules.extend(
            await all_pages(request, "schedule", "/api/v1/schedule", params)
        )
    schedules = [
        row
        for row in schedules
        if date.fromisoformat(row["scheduled_date"]) < today
        or (
            date.fromisoformat(row["scheduled_date"]) == today
            and datetime.fromisoformat(
                f"{row['scheduled_date']}T{row['end_time']}"
            ).time()
            <= now.time().replace(tzinfo=None)
        )
    ]
    if not schedules:
        return report

    group_ids = sorted({str(row["group_id"]) for row in schedules})
    groups: dict[str, dict] = {}
    for batch in batches(group_ids):
        params = [("group_ids", value) for value in batch]
        if department_id:
            params.append(("department_id", str(department_id)))
        if specialty_id:
            params.append(("specialty_id", str(specialty_id)))
        rows = await all_pages(request, "students", "/api/v1/students/groups", params)
        groups.update({str(row["id"]): row for row in rows})
    schedules = [row for row in schedules if str(row["group_id"]) in groups]
    if not schedules:
        return report

    students: list[dict] = []
    for batch in batches(sorted(groups)):
        students.extend(
            await all_pages(
                request,
                "students",
                "/api/v1/students/students",
                [("group_ids", value) for value in batch],
            )
        )
    schedule_by_group: dict[str, list[dict]] = defaultdict(list)
    for row in schedules:
        schedule_by_group[str(row["group_id"])].append(row)
    if not students:
        return report

    week_from = date_from - timedelta(days=date_from.weekday())
    week_to = end - timedelta(days=end.weekday())
    present: set[tuple[str, str, str]] = set()
    schedule_weeks = {
        str(row["id"]): str(
            date.fromisoformat(row["scheduled_date"])
            - timedelta(days=date.fromisoformat(row["scheduled_date"]).weekday())
        )
        for row in schedules
    }
    for batch in batches([str(row["id"]) for row in schedules]):
        params = [("schedule_ids", value) for value in batch] + [
            ("week_from", str(week_from)),
            ("week_to", str(week_to)),
        ]
        rows = await all_pages(request, "attendance", "/api/v1/attendance", params)
        if any(
            str(row["week_start_date"]) != schedule_weeks.get(str(row["schedule_id"]))
            for row in rows
        ):
            raise HTTPException(503, "Attendance week does not match the schedule")
        present.update(
            (
                str(row["schedule_id"]),
                str(row["student_id"]),
                str(row["week_start_date"]),
            )
            for row in rows
            if row["is_present"]
        )

    ranked: list[tuple[Fraction, str, ReportItem]] = []
    for student in students:
        relevant = [
            row
            for row in schedule_by_group.get(str(student["group_id"]), [])
            if date.fromisoformat(row["scheduled_date"])
            >= date.fromisoformat(student["enrollment_date"])
        ]
        if not relevant:
            continue
        attended = 0
        for lesson in relevant:
            day = date.fromisoformat(lesson["scheduled_date"])
            week = day - timedelta(days=day.weekday())
            attended += (str(lesson["id"]), str(student["id"]), str(week)) in present
        ratio = Fraction(attended, len(relevant))
        item = ReportItem(
            student=student,
            group=groups[str(student["group_id"])],
            attendance_percent=round(float(ratio * 100), 2),
            attended_count=attended,
            lecture_count=len(relevant),
        )
        ranked.append((ratio, str(student["id"]), item))
    report.items = [
        item for _, _, item in sorted(ranked, key=lambda row: (row[0], row[1]))[:10]
    ]
    return report


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok"}
