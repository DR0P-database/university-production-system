from __future__ import annotations

import asyncio
import math
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx

JsonObject = dict[str, Any]
FIRST_NAMES = (
    "Александр",
    "Анна",
    "Максим",
    "Мария",
    "Иван",
    "София",
    "Дмитрий",
    "Екатерина",
    "Михаил",
    "Полина",
    "Артём",
    "Дарья",
    "Никита",
    "Виктория",
    "Егор",
    "Алина",
    "Кирилл",
    "Ксения",
    "Илья",
    "Валерия",
)

LAST_NAMES = (
    "Иванов",
    "Смирнов",
    "Кузнецов",
    "Попов",
    "Васильев",
    "Петров",
    "Соколов",
    "Михайлов",
    "Новиков",
    "Фёдоров",
    "Морозов",
    "Волков",
    "Алексеев",
    "Лебедев",
    "Семёнов",
    "Егоров",
    "Павлов",
    "Козлов",
    "Степанов",
    "Николаев",
)

PATRONYMICS = (
    "Александрович",
    "Алексеевич",
    "Андреевич",
    "Викторович",
    "Дмитриевич",
    "Иванович",
    "Максимович",
    "Михайлович",
    "Николаевич",
    "Сергеевич",
)


@dataclass(frozen=True)
class Config:
    student_count: int
    university_count: int
    group_size: int
    week_count: int
    start_date: date
    concurrency: int

    @classmethod
    def from_env(cls) -> Config:
        config = cls(
            student_count=int(os.getenv("SEED_STUDENT_COUNT", "1000")),
            university_count=int(os.getenv("SEED_UNIVERSITY_COUNT", "2")),
            group_size=int(os.getenv("SEED_GROUP_SIZE", "30")),
            week_count=int(os.getenv("SEED_WEEK_COUNT", "4")),
            start_date=date.fromisoformat(os.getenv("SEED_START_DATE", "2026-09-07")),
            concurrency=int(os.getenv("SEED_CONCURRENCY", "12")),
        )
        if config.student_count < config.university_count:
            raise ValueError("student_count must be at least university_count")
        if config.group_size < 1 or config.group_size > 100:
            raise ValueError("group_size must be between 1 and 100")
        if config.week_count < 1:
            raise ValueError("week_count must be positive")
        if config.start_date.isoweekday() != 1:
            raise ValueError("SEED_START_DATE must be a Monday")
        return config

    def students_per_university(self, university_index: int) -> int:
        base, remainder = divmod(self.student_count, self.university_count)
        return base + (1 if university_index < remainder else 0)

    @property
    def expected_group_count(self) -> int:
        return sum(
            math.ceil(self.students_per_university(index) / self.group_size)
            for index in range(self.university_count)
        )

    @property
    def expected_schedule_count(self) -> int:
        return self.expected_group_count * self.week_count * 3

    @property
    def expected_attendance_count(self) -> int:
        return self.student_count * self.week_count


class ServiceApi:
    def __init__(self, config: Config):
        self.config = config
        self.base_urls = {
            "academic": os.getenv(
                "ACADEMIC_SERVICE_URL", "http://academic-service:8000"
            ),
            "student": os.getenv("STUDENT_SERVICE_URL", "http://student-service:8000"),
            "schedule": os.getenv(
                "SCHEDULE_SERVICE_URL", "http://schedule-service:8000"
            ),
            "attendance": os.getenv(
                "ATTENDANCE_SERVICE_URL", "http://attendance-service:8000"
            ),
        }
        self.client = httpx.AsyncClient(timeout=30.0)
        self.semaphore = asyncio.Semaphore(config.concurrency)

    async def close(self) -> None:
        await self.client.aclose()

    async def request(
        self,
        method: str,
        service: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        url = f"{self.base_urls[service]}{path}"
        async with self.semaphore:
            response = await self.client.request(
                method,
                url,
                params=params,
                json=json,
                headers={"X-Request-ID": "seed-data"},
            )
        if response.is_error:
            raise RuntimeError(
                f"{method} {url} failed with {response.status_code}: {response.text}"
            )
        if response.status_code == 204:
            return None
        return response.json()

    async def list_all(
        self, service: str, path: str, **filters: Any
    ) -> list[JsonObject]:
        items: list[JsonObject] = []
        offset = 0
        while True:
            page = await self.request(
                "GET",
                service,
                path,
                params={"limit": 100, "offset": offset, **filters},
            )
            page_items = page["items"]
            items.extend(page_items)
            offset += len(page_items)
            if offset >= page["total"] or not page_items:
                return items

    async def healthcheck(self) -> None:
        for service, base_url in self.base_urls.items():
            for attempt in range(60):
                try:
                    response = await self.client.get(f"{base_url}/health", timeout=2.0)
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if attempt == 59:
                    raise RuntimeError(f"{service} service did not become healthy")
                await asyncio.sleep(1)


def by(items: list[JsonObject], field: str) -> dict[Any, JsonObject]:
    return {item[field]: item for item in items}


async def ensure(
    api: ServiceApi,
    service: str,
    path: str,
    cache: dict[Any, JsonObject],
    key: Any,
    payload: JsonObject,
) -> JsonObject:
    existing = cache.get(key)
    if existing is not None:
        return existing
    created = await api.request("POST", service, path, json=payload)
    cache[key] = created
    return created


async def run_limited[T](
    operations: list[Callable[[], Awaitable[T]]], concurrency: int
) -> list[T]:
    results: list[T] = []
    for start in range(0, len(operations), concurrency):
        batch = operations[start : start + concurrency]
        results.extend(await asyncio.gather(*(operation() for operation in batch)))
    return results


class DataSeeder:
    def __init__(self, api: ServiceApi, config: Config):
        self.api = api
        self.config = config
        self.specialties: list[JsonObject] = []
        self.lecture_ids_by_specialty: dict[str, list[str]] = {}
        self.groups: list[JsonObject] = []
        self.students_by_group: dict[str, list[JsonObject]] = {}
        self.schedules: dict[tuple[str, int, int], JsonObject] = {}

    async def seed(self) -> None:
        await self.api.healthcheck()
        print("[1/5] Seeding academic data")
        await self.seed_academic()
        print("[2/5] Seeding groups")
        await self.seed_groups()
        print("[3/5] Seeding 1000 students")
        await self.seed_students()
        print("[4/5] Seeding schedule")
        await self.seed_schedule()
        print("[5/5] Seeding attendance")
        await self.seed_attendance()
        await DataVerifier(self.api, self.config).verify()

    async def seed_academic(self) -> None:
        universities = by(
            await self.api.list_all("academic", "/api/v1/academic/universities"),
            "short_name",
        )
        for university_index in range(self.config.university_count):
            university_number = university_index + 1
            university_key = f"SEED-U{university_number}"
            university = await ensure(
                self.api,
                "academic",
                "/api/v1/academic/universities",
                universities,
                university_key,
                {
                    "name": f"[SEED] Университет {university_number}",
                    "short_name": university_key,
                    "address": f"Учебная улица, {university_number}",
                    "website": f"https://seed-u{university_number}.example.edu",
                    "founded_year": 1950 + university_number,
                },
            )
            await self.seed_university_structure(university_index, university)

    async def seed_university_structure(
        self, university_index: int, university: JsonObject
    ) -> None:
        university_number = university_index + 1
        institutes = by(
            await self.api.list_all(
                "academic",
                "/api/v1/academic/institutes",
                university_id=university["id"],
            ),
            "short_name",
        )
        for institute_index in range(2):
            institute_number = institute_index + 1
            institute_key = f"SEED-U{university_number}-I{institute_number}"
            institute = await ensure(
                self.api,
                "academic",
                "/api/v1/academic/institutes",
                institutes,
                institute_key,
                {
                    "university_id": university["id"],
                    "name": f"[SEED] Институт {university_number}.{institute_number}",
                    "short_name": institute_key,
                    "dean": f"Декан {university_number}.{institute_number}",
                },
            )
            await self.seed_institute_structure(
                university_index, institute_index, institute
            )

    async def seed_institute_structure(
        self, university_index: int, institute_index: int, institute: JsonObject
    ) -> None:
        university_number = university_index + 1
        institute_number = institute_index + 1
        departments = by(
            await self.api.list_all(
                "academic",
                "/api/v1/academic/departments",
                institute_id=institute["id"],
            ),
            "short_name",
        )
        for department_index in range(2):
            department_number = department_index + 1
            department_key = (
                f"SEED-U{university_number}-I{institute_number}-D{department_number}"
            )
            department = await ensure(
                self.api,
                "academic",
                "/api/v1/academic/departments",
                departments,
                department_key,
                {
                    "institute_id": institute["id"],
                    "name": (
                        f"[SEED] Кафедра {university_number}."
                        f"{institute_number}.{department_number}"
                    ),
                    "short_name": department_key,
                    "head": f"Заведующий {department_key}",
                    "room": f"{institute_number}{department_number}0",
                },
            )
            specialty_index = institute_index * 2 + department_index
            await self.seed_specialty(university_index, specialty_index, department)

    async def seed_specialty(
        self, university_index: int, specialty_index: int, department: JsonObject
    ) -> None:
        university_number = university_index + 1
        specialty_number = specialty_index + 1
        code = f"SEED-U{university_number}-S{specialty_number}"
        existing_specialties = by(
            await self.api.list_all(
                "academic", "/api/v1/academic/specialties", code=code
            ),
            "code",
        )
        specialty = await ensure(
            self.api,
            "academic",
            "/api/v1/academic/specialties",
            existing_specialties,
            code,
            {
                "name": f"[SEED] Специальность {university_number}.{specialty_number}",
                "code": code,
                "degree_level": "bachelor",
                "duration_years": 4,
            },
        )
        relations = by(
            await self.api.list_all(
                "academic",
                f"/api/v1/academic/departments/{department['id']}/specialties",
            ),
            "specialty_id",
        )
        await ensure(
            self.api,
            "academic",
            f"/api/v1/academic/departments/{department['id']}/specialties",
            relations,
            specialty["id"],
            {"specialty_id": specialty["id"], "is_primary": True},
        )
        specialty["department_id"] = department["id"]
        specialty["university_index"] = university_index
        self.specialties.append(specialty)
        await self.seed_courses_and_lectures(specialty)

    async def seed_courses_and_lectures(self, specialty: JsonObject) -> None:
        courses = by(
            await self.api.list_all(
                "academic",
                "/api/v1/academic/courses",
                specialty_id=specialty["id"],
            ),
            "name",
        )
        lecture_ids: list[str] = []
        for course_index in range(2):
            course_number = course_index + 1
            course_name = f"[SEED] {specialty['code']} курс {course_number}"
            course = await ensure(
                self.api,
                "academic",
                "/api/v1/academic/courses",
                courses,
                course_name,
                {
                    "specialty_id": specialty["id"],
                    "name": course_name,
                    "description": "Автоматически сгенерированный учебный курс",
                    "semester": course_number,
                    "total_hours": 72,
                    "lecture_hours": 36,
                    "practice_hours": 18,
                    "lab_hours": 18,
                },
            )
            lectures = by(
                await self.api.list_all(
                    "academic",
                    "/api/v1/academic/lectures",
                    course_id=course["id"],
                ),
                "order_number",
            )
            for lecture_index in range(6):
                order_number = lecture_index + 1
                lecture = await ensure(
                    self.api,
                    "academic",
                    "/api/v1/academic/lectures",
                    lectures,
                    order_number,
                    {
                        "course_id": course["id"],
                        "title": f"[SEED] {course_name}, занятие {order_number}",
                        "annotation": "Автоматически сгенерированная лекция",
                        "lecture_type": (
                            "lecture" if lecture_index < 3 else "practice"
                        ),
                        "order_number": order_number,
                        "duration_minutes": 90,
                        "requirements": None,
                    },
                )
                lecture_ids.append(lecture["id"])
                await self.seed_materials(lecture)
        self.lecture_ids_by_specialty[specialty["id"]] = lecture_ids

    async def seed_materials(self, lecture: JsonObject) -> None:
        materials = by(
            await self.api.list_all(
                "academic",
                "/api/v1/academic/materials",
                lecture_id=lecture["id"],
            ),
            "title",
        )
        for material_index in range(2):
            material_number = material_index + 1
            title = f"[SEED] Материал {lecture['id']} / {material_number}"
            await ensure(
                self.api,
                "academic",
                "/api/v1/academic/materials",
                materials,
                title,
                {
                    "lecture_id": lecture["id"],
                    "content_type": "text" if material_index == 0 else "exercise",
                    "title": title,
                    "content_text": (
                        "Автоматически сгенерированный учебный материал "
                        f"для лекции {lecture['id']}"
                    ),
                    "file_url": None,
                    "metadata_json": {
                        "source": "data-seeder",
                        "material_number": material_number,
                    },
                },
            )

    async def seed_groups(self) -> None:
        existing_groups = by(
            await self.api.list_all("student", "/api/v1/students/groups"), "name"
        )
        specialties_by_university: dict[int, list[JsonObject]] = {}
        for specialty in self.specialties:
            specialties_by_university.setdefault(
                specialty["university_index"], []
            ).append(specialty)

        for university_index in range(self.config.university_count):
            student_count = self.config.students_per_university(university_index)
            group_count = math.ceil(student_count / self.config.group_size)
            university_specialties = specialties_by_university[university_index]
            for group_index in range(group_count):
                specialty = university_specialties[
                    group_index % len(university_specialties)
                ]
                name = f"SEED-U{university_index + 1}-G{group_index + 1:02d}"
                group = await ensure(
                    self.api,
                    "student",
                    "/api/v1/students/groups",
                    existing_groups,
                    name,
                    {
                        "specialty_id": specialty["id"],
                        "department_id": specialty["department_id"],
                        "name": name,
                        "enrollment_year": 2026,
                        "curator": f"Куратор {name}",
                    },
                )
                group["university_index"] = university_index
                group["group_index"] = group_index
                self.groups.append(group)

    async def seed_students(self) -> None:
        existing_students = by(
            await self.api.list_all("student", "/api/v1/students/students"), "email"
        )
        operations: list[Callable[[], Awaitable[JsonObject]]] = []
        student_number = 0

        for group in self.groups:
            university_index = group["university_index"]
            group_index = group["group_index"]
            university_student_count = self.config.students_per_university(
                university_index
            )
            first_student = group_index * self.config.group_size
            group_student_count = min(
                self.config.group_size, university_student_count - first_student
            )
            self.students_by_group[group["id"]] = []
            for _ in range(group_student_count):
                student_number += 1
                email = f"seed.student.{student_number:04d}@example.edu"
                payload = {
                    "group_id": group["id"],
                    "first_name": FIRST_NAMES[(student_number - 1) % len(FIRST_NAMES)],
                    "last_name": LAST_NAMES[
                        ((student_number - 1) // len(FIRST_NAMES)) % len(LAST_NAMES)
                    ],
                    "patronymic": PATRONYMICS[(student_number - 1) % len(PATRONYMICS)],
                    "email": email,
                    "phone": f"+7999{student_number:07d}",
                    "student_card_number": f"SEED-{student_number:06d}",
                    "enrollment_date": "2026-09-01",
                    "status": "active",
                }

                async def create_student(
                    *,
                    key: str = email,
                    data: JsonObject = payload,
                    target_group_id: str = group["id"],
                ) -> JsonObject:
                    student = await ensure(
                        self.api,
                        "student",
                        "/api/v1/students/students",
                        existing_students,
                        key,
                        data,
                    )
                    self.students_by_group[target_group_id].append(student)
                    return student

                operations.append(create_student)

        await run_limited(operations, self.config.concurrency)

    async def seed_schedule(self) -> None:
        operations: list[Callable[[], Awaitable[JsonObject]]] = []
        time_slots = (
            (time(9), time(10, 30)),
            (time(11), time(12, 30)),
            (time(14), time(15, 30)),
        )

        for group in self.groups:
            existing = await self.api.list_all(
                "schedule", "/api/v1/schedule", group_id=group["id"]
            )
            existing_by_key = {
                (item["scheduled_date"], item["start_time"]): item for item in existing
            }
            lecture_ids = self.lecture_ids_by_specialty[group["specialty_id"]]
            for week_index in range(self.config.week_count):
                week_start = self.config.start_date + timedelta(weeks=week_index)
                for session_index, day_offset in enumerate((0, 2, 4)):
                    scheduled_date = week_start + timedelta(days=day_offset)
                    starts_at, ends_at = time_slots[session_index]
                    key = (scheduled_date.isoformat(), starts_at.isoformat())
                    lecture_id = lecture_ids[
                        (group["group_index"] * 3 + week_index * 3 + session_index)
                        % len(lecture_ids)
                    ]
                    payload = {
                        "lecture_id": lecture_id,
                        "group_id": group["id"],
                        "scheduled_date": scheduled_date.isoformat(),
                        "week_start_date": week_start.isoformat(),
                        "start_time": starts_at.isoformat(),
                        "end_time": ends_at.isoformat(),
                        "classroom": f"SEED-{group['group_index'] + 101}",
                        "teacher_name": "Seed Teacher",
                        "status": "completed",
                    }

                    async def create_schedule(
                        *,
                        schedule_key: tuple[str, str] = key,
                        data: JsonObject = payload,
                        target_group_id: str = group["id"],
                        target_week: int = week_index,
                        target_session: int = session_index,
                        cache: dict[tuple[str, str], JsonObject] = existing_by_key,
                    ) -> JsonObject:
                        schedule = await ensure(
                            self.api,
                            "schedule",
                            "/api/v1/schedule",
                            cache,
                            schedule_key,
                            data,
                        )
                        self.schedules[
                            (target_group_id, target_week, target_session)
                        ] = schedule
                        return schedule

                    operations.append(create_schedule)

        await run_limited(operations, max(1, self.config.concurrency // 2))

    async def seed_attendance(self) -> None:
        operations: list[Callable[[], Awaitable[Any]]] = []
        for group in self.groups:
            students = sorted(
                self.students_by_group[group["id"]], key=lambda item: item["email"]
            )
            for week_index in range(self.config.week_count):
                schedule = self.schedules[(group["id"], week_index, 0)]
                week_start = self.config.start_date + timedelta(weeks=week_index)
                marks = []
                for student in students:
                    ordinal = int(student["email"].split(".")[2].split("@")[0])
                    present = (ordinal + week_index) % 7 != 0
                    marks.append(
                        {
                            "student_id": student["id"],
                            "week_start_date": week_start.isoformat(),
                            "is_present": present,
                            "marked_at": datetime.combine(
                                schedule_date(schedule), time(9, 5), tzinfo=UTC
                            ).isoformat(),
                            "note": "SEED: присутствовал"
                            if present
                            else "SEED: отсутствовал",
                        }
                    )

                async def mark_attendance(
                    *,
                    target_schedule_id: str = schedule["id"],
                    payload: list[JsonObject] = marks,
                ) -> Any:
                    return await self.api.request(
                        "PUT",
                        "attendance",
                        f"/api/v1/attendance/schedules/{target_schedule_id}",
                        json=payload,
                    )

                operations.append(mark_attendance)

        await run_limited(operations, max(1, self.config.concurrency // 4))


def schedule_date(schedule: JsonObject) -> date:
    value = schedule["scheduled_date"]
    return value if isinstance(value, date) else date.fromisoformat(value)


class DataVerifier:
    def __init__(self, api: ServiceApi, config: Config):
        self.api = api
        self.config = config

    async def verify(self) -> None:
        await self.api.healthcheck()
        universities = [
            item
            for item in await self.api.list_all(
                "academic", "/api/v1/academic/universities"
            )
            if (item.get("short_name") or "").startswith("SEED-U")
        ]
        institutes = [
            item
            for item in await self.api.list_all(
                "academic", "/api/v1/academic/institutes"
            )
            if (item.get("short_name") or "").startswith("SEED-U")
        ]
        departments = [
            item
            for item in await self.api.list_all(
                "academic", "/api/v1/academic/departments"
            )
            if (item.get("short_name") or "").startswith("SEED-U")
        ]
        specialties = [
            item
            for item in await self.api.list_all(
                "academic", "/api/v1/academic/specialties"
            )
            if item["code"].startswith("SEED-U")
        ]
        courses = [
            item
            for item in await self.api.list_all("academic", "/api/v1/academic/courses")
            if item["name"].startswith("[SEED]")
        ]
        lectures = [
            item
            for item in await self.api.list_all("academic", "/api/v1/academic/lectures")
            if item["title"].startswith("[SEED]")
        ]
        materials = [
            item
            for item in await self.api.list_all(
                "academic", "/api/v1/academic/materials"
            )
            if (item.get("title") or "").startswith("[SEED]")
        ]
        groups = [
            item
            for item in await self.api.list_all("student", "/api/v1/students/groups")
            if item["name"].startswith("SEED-U")
        ]
        students = [
            item
            for item in await self.api.list_all("student", "/api/v1/students/students")
            if (item.get("email") or "").startswith("seed.student.")
        ]

        expected = {
            "universities": self.config.university_count,
            "institutes": self.config.university_count * 2,
            "departments": self.config.university_count * 4,
            "specialties": self.config.university_count * 4,
            "courses": self.config.university_count * 8,
            "lectures": self.config.university_count * 48,
            "materials": self.config.university_count * 96,
            "groups": self.config.expected_group_count,
            "students": self.config.student_count,
        }
        actual = {
            "universities": len(universities),
            "institutes": len(institutes),
            "departments": len(departments),
            "specialties": len(specialties),
            "courses": len(courses),
            "lectures": len(lectures),
            "materials": len(materials),
            "groups": len(groups),
            "students": len(students),
        }
        if actual != expected:
            raise RuntimeError(
                f"Seed counts do not match: expected={expected}, actual={actual}"
            )

        groups_by_id = {item["id"]: item for item in groups}
        courses_by_id = {item["id"]: item for item in courses}
        lectures_by_id = {item["id"]: item for item in lectures}
        students_by_group: dict[str, list[JsonObject]] = {
            group_id: [] for group_id in groups_by_id
        }
        for student in students:
            if student["group_id"] not in students_by_group:
                raise RuntimeError(
                    f"Student belongs to a non-seed group: {student['id']}"
                )
            students_by_group[student["group_id"]].append(student)

        schedule_count = 0
        attendance_count = 0
        for group_id, group_students in students_by_group.items():
            if len(group_students) > self.config.group_size:
                raise RuntimeError(f"Group {group_id} exceeds configured size")
            schedules = [
                item
                for item in await self.api.list_all(
                    "schedule", "/api/v1/schedule", group_id=group_id
                )
                if item.get("teacher_name") == "Seed Teacher"
            ]
            for schedule in schedules:
                lecture = lectures_by_id.get(schedule["lecture_id"])
                course = courses_by_id.get(lecture["course_id"]) if lecture else None
                if (
                    course is None
                    or course["specialty_id"] != groups_by_id[group_id]["specialty_id"]
                ):
                    raise RuntimeError(
                        f"Schedule {schedule['id']} does not match group specialty"
                    )
            expected_schedules = self.config.week_count * 3
            if len(schedules) != expected_schedules:
                raise RuntimeError(
                    f"Group {group_id} has {len(schedules)} seed schedules, "
                    f"expected {expected_schedules}"
                )
            schedule_count += len(schedules)
            attendance_schedules = [
                item for item in schedules if item["start_time"].startswith("09:00")
            ]
            for schedule in attendance_schedules:
                journal = await self.api.list_all(
                    "attendance",
                    f"/api/v1/attendance/schedules/{schedule['id']}",
                )
                if len(journal) != len(group_students):
                    raise RuntimeError(
                        f"Schedule {schedule['id']} has {len(journal)} marks, "
                        f"expected {len(group_students)}"
                    )
                expected_student_ids = {student["id"] for student in group_students}
                actual_student_ids = {mark["student_id"] for mark in journal}
                if actual_student_ids != expected_student_ids:
                    raise RuntimeError(
                        f"Schedule {schedule['id']} contains marks from another group"
                    )
                attendance_count += len(journal)

        if schedule_count != self.config.expected_schedule_count:
            raise RuntimeError(
                f"Expected {self.config.expected_schedule_count} schedules, "
                f"found {schedule_count}"
            )
        if attendance_count != self.config.expected_attendance_count:
            raise RuntimeError(
                f"Expected {self.config.expected_attendance_count} attendance marks, "
                f"found {attendance_count}"
            )

        print("Verification passed:")
        print(f"  universities: {len(universities)}")
        print(f"  institutes:    {len(institutes)}")
        print(f"  departments:   {len(departments)}")
        print(f"  specialties:   {len(specialties)}")
        print(f"  courses:       {len(courses)}")
        print(f"  lectures:      {len(lectures)}")
        print(f"  materials:     {len(materials)}")
        print(f"  groups:        {len(groups)}")
        print(f"  students:      {len(students)}")
        print(f"  schedules:     {schedule_count}")
        print(f"  attendance:    {attendance_count}")


async def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "seed"
    if command not in {"seed", "verify"}:
        raise SystemExit("Usage: seeder.py [seed|verify]")
    config = Config.from_env()
    api = ServiceApi(config)
    try:
        if command == "seed":
            await DataSeeder(api, config).seed()
        else:
            await DataVerifier(api, config).verify()
    finally:
        await api.close()


if __name__ == "__main__":
    asyncio.run(main())
