from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

PAGE_SIZE = 100
URLS = {
    "academic": os.getenv("ACADEMIC_SERVICE_URL", "http://academic-service:8000"),
    "students": os.getenv("STUDENT_SERVICE_URL", "http://student-service:8000"),
    "schedule": os.getenv("SCHEDULE_SERVICE_URL", "http://schedule-service:8000"),
    "attendance": os.getenv("ATTENDANCE_SERVICE_URL", "http://attendance-service:8000"),
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(timeout=15) as client:
        app.state.client = client
        yield


app = FastAPI(
    title="Practice 3 Group Hours Report",
    version="1.0.0",
    openapi_tags=[
        {
            "name": "Лабораторная 3",
            "description": "Запланированные и посещённые академические часы по каждому студенту группы и каждой учебной дисциплине.",
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
        if response.status_code == 404:
            raise HTTPException(404, "Resource not found")
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


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok"}


class HoursItem(BaseModel):
    student: dict[str, Any]
    course: dict[str, Any]
    planned_hours: int
    planned_hours_to_date: int
    attended_hours: int


class GroupHoursReport(BaseModel):
    group: dict[str, Any]
    discipline_tag: str
    as_of_date: date
    timezone: str
    academic_hours_per_lecture: int = 2
    items: list[HoursItem]


@app.get(
    "/api/v1/reports/group-lecture-hours",
    response_model=GroupHoursReport,
    tags=["Лабораторная 3"],
    summary="План и посещённые часы по студентам группы и предметам",
    description=(
        "Возвращает полную карточку группы и строки по каждой паре «студент — предмет». "
        "Курс (course) здесь означает учебный предмет, а не год обучения. "
        "planned_hours — полный план по расписанию; planned_hours_to_date — план "
        "до конца as_of_date включительно; attended_hours — посещённые часы "
        "к этой дате. Без даты используется сегодняшний день. "
        "Одна лекция равна двум академическим часам. Учитываются только лекции "
        "с заданным тегом, без отменённых занятий и занятий до зачисления студента. "
        "Посещение засчитывается только для завершённых и уже закончившихся "
        "занятий с is_present=true. Для сегодняшней или будущей даты посещения "
        "учитываются только до текущего момента. Часовой пояс — Europe/Moscow "
        "по умолчанию. Используются текущие карточки, расписание и отметки: "
        "состояние базы на прошлую дату не восстанавливается."
    ),
)
async def group_hours(
    request: Request,
    group_id: UUID = Query(
        ..., description="UUID группы из GET /api/v1/students/groups"
    ),
    as_of_date: date | None = Query(
        None,
        description="Дата отчёта включительно (ГГГГ-ММ-ДД). Без параметра — сегодня в часовом поясе отчёта.",
    ),
    discipline_tag: str = Query(
        ...,
        min_length=1,
        max_length=200,
        description="Точная метка специальной дисциплины в tags лекции; для SEED-данных: специальная-дисциплина",
    ),
):
    timezone = os.getenv("REPORT_TIMEZONE", "Europe/Moscow")
    now = datetime.now(ZoneInfo(timezone)).replace(tzinfo=None)
    report_date = as_of_date or now.date()
    cutoff = min(now, datetime.combine(report_date, time.max))
    tag = discipline_tag.strip()
    if not tag:
        raise HTTPException(422, "discipline_tag must not be blank")
    group = await get_json(
        request, "students", f"/api/v1/students/groups/{group_id}", {}
    )
    students = await all_pages(
        request, "students", "/api/v1/students/students", [("group_id", str(group_id))]
    )
    courses = await all_pages(
        request,
        "academic",
        "/api/v1/academic/courses",
        [("specialty_id", str(group["specialty_id"]))],
    )
    schedules = await all_pages(
        request, "schedule", "/api/v1/schedule", [("group_id", str(group_id))]
    )
    lectures = {}
    for batch in batches(sorted({str(row["lecture_id"]) for row in schedules})):
        rows = await all_pages(
            request,
            "academic",
            "/api/v1/academic/lectures",
            [("ids", value) for value in batch] + [("lecture_type", "lecture")],
        )
        lectures.update(
            {
                str(row["id"]): row
                for row in rows
                if row["lecture_type"] == "lecture" and tag in row.get("tags", [])
            }
        )
    lessons = {
        str(row["id"]): row
        for row in schedules
        if row["status"] != "cancelled" and str(row["lecture_id"]) in lectures
    }
    completed = {
        key: row
        for key, row in lessons.items()
        if row["status"] == "completed"
        and datetime.fromisoformat(f"{row['scheduled_date']}T{row['end_time']}")
        <= cutoff
    }
    weeks = {
        key: str(
            date.fromisoformat(row["scheduled_date"])
            - timedelta(days=date.fromisoformat(row["scheduled_date"]).weekday())
        )
        for key, row in completed.items()
    }
    present = set()
    for batch in batches(sorted(completed)):
        rows = await all_pages(
            request,
            "attendance",
            "/api/v1/attendance",
            [("schedule_ids", value) for value in batch]
            + [
                ("week_from", min(weeks[value] for value in batch)),
                ("week_to", max(weeks[value] for value in batch)),
            ],
        )
        for row in rows:
            schedule_id = str(row["schedule_id"])
            if (
                schedule_id not in completed
                or str(row["week_start_date"]) != weeks[schedule_id]
            ):
                raise HTTPException(503, "Attendance does not match the schedule")
            if row["is_present"]:
                present.add((schedule_id, str(row["student_id"])))
    items = []
    for student in sorted(
        students, key=lambda row: (row["last_name"], row["first_name"], str(row["id"]))
    ):
        for course in sorted(courses, key=lambda row: (row["name"], str(row["id"]))):
            relevant = {
                key
                for key, row in lessons.items()
                if str(lectures[str(row["lecture_id"])]["course_id"])
                == str(course["id"])
                and row["scheduled_date"] >= student["enrollment_date"]
            }
            items.append(
                HoursItem(
                    student=student,
                    course=course,
                    planned_hours=2 * len(relevant),
                    planned_hours_to_date=2
                    * sum(
                        lessons[key]["scheduled_date"] <= report_date.isoformat()
                        for key in relevant
                    ),
                    attended_hours=2
                    * sum((key, str(student["id"])) in present for key in relevant),
                )
            )
    return GroupHoursReport(
        group=group,
        discipline_tag=tag,
        as_of_date=report_date,
        timezone=timezone,
        items=items,
    )
