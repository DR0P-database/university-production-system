"""Синтетические данные по точной схеме ПР3 и их загрузка в пять хранилищ."""
from __future__ import annotations
import hashlib
import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
FIRST_MONDAY = date(2026, 9, 7)
WEEKS_IN_DDL = 16
SYNTHETIC_NOTE = ("Синтетический демонстрационный набор ЛР1 (demo); "
                  "не является утраченными реальными данными ПР3")
_SLOTS = (
    (0, time(9, 0), time(10, 30)),
    (1, time(10, 45), time(12, 15)),
    (2, time(12, 30), time(14, 0)),
)
_SURNAMES = [
    "Абрамов", "Барсуков", "Волков", "Гусев", "Демьянов", "Ежов", "Зайцев",
    "Иванов", "Ковалёв", "Лебедев", "Морозов", "Никитин", "Орлов", "Павлов",
    "Романов", "Сазонов", "Тимофеев", "Ушаков", "Фролов", "Хохлов",
    "Царёв", "Чернов", "Шестаков", "Щербаков", "Юдин", "Ярцев",
    "Белов", "Гаврилов", "Дмитриев", "Егоров", "Зиновьев", "Ильин", "Кошелев",
    "Луконин", "Макаров", "Некрасов", "Одинцов", "Панфилов", "Родионов",
    "Самойлов", "Тарасов", "Уваров", "Филиппов", "Хлебников", "Чижов",
    "Шилов", "Южаков", "Яковлев",
]
_FIRST_NAMES = [
    "Анна", "Борис", "Вера", "Глеб", "Дарья", "Егор", "Жанна", "Захар",
    "Ирина", "Кирилл", "Лидия", "Максим", "Надежда", "Олег", "Полина",
    "Родион", "Светлана", "Тарас", "Ульяна", "Фёдор", "Христина", "Юрий",
    "Яна", "Артём", "Валентина", "Григорий", "Даниил", "Елизавета",
    "Иннокентий", "Ксения", "Лев", "Марина",
]
_PATRONYMICS = [
    "Александрович", "Алексеевна", "Андреевич", "Борисович", "Валерьевна",
    "Викторович", "Геннадьевич", "Дмитриевна", "Евгеньевич", "Ивановна",
    "Игоревич", "Константинович", "Леонидовна", "Михайлович", "Николаевна",
    "Олегович", "Петровна", "Романович", "Сергеевна", "Тимофеевич",
    "Юрьевна", "Ярославович",
]
_TEACHERS = [
    "Ветров Владимир Валерьевич", "Соколова Марина Игоревна",
    "Лапин Олег Тимофеевич", "Куликова Наталья Сергеевна",
    "Мещерин Аркадий Петрович", "Озерова Екатерина Юрьевна",
    "Титов Валентин Лукьевич", "Рябова Ольга Дмитриевна",
]
_COURSES: list[dict[str, Any]] = [
    {"code": "demo_arch", "title": "Архитектура информационных систем (демо)",
     "keyword": "архитектура", "scheduled": True, "elective": False,
     "topics": ["Введение в архитектуру ИС", "Слои и связи приложений",
                "Модули и границы систем", "Синхронные и асинхронные вызовы",
                "Кэширование и согласованность", "Отказоустойчивость и деградация",
                "Наблюдаемость систем", "Проектирование итоговой архитектуры"]},
    {"code": "demo_storage", "title": "Базы данных и хранилища (демо)",
     "keyword": "целостность", "scheduled": True, "elective": False,
     "topics": ["Реляционная модель и целостность", "Нормализация и денормализация",
                "Индексы и планы запросов", "Транзакции и уровни изоляции",
                "Партиционирование больших таблиц", "Полнотекстовый поиск",
                "Нереляционные хранилища", "Проектирование схемы данных"]},
    {"code": "demo_security", "title": "Информационная безопасность (демо)",
     "keyword": "безопасность", "scheduled": True, "elective": False,
     "topics": ["Цели и модели безопасности", "Аутентификация и авторизация",
                "Токены и контроль доступа", "Хэширование паролей",
                "Целостность данных и контрольные суммы", "Защита сервисных вызовов",
                "Аудит и журналирование", "Управление инцидентами"]},
    {"code": "demo_api", "title": "Проектирование API (демо)",
     "keyword": "контракт", "scheduled": True, "elective": False,
     "topics": ["Ресурсы и контракты", "REST и gRPC", "Версионирование API",
                "Обработка ошибок", "Пагинация и фильтрация", "Безопасность API",
                "Документация и OpenAPI", "Проектирование клиентских SDK"]},
    {"code": "demo_data", "title": "Технологии обработки данных (демо)",
     "keyword": "хранилище", "scheduled": True, "elective": False,
     "topics": ["Форматы данных", "Пакетная и потоковая обработка",
                "Очереди сообщений", "Хранилища ключей и значений",
                "Документные базы данных", "Графовые базы данных",
                "Поисковые движки", "Конвейеры данных"]},
    {"code": "demo_os", "title": "Операционные системы (демо)",
     "keyword": "процесс", "scheduled": True, "elective": True,
     "topics": ["Процессы и потоки", "Планировщик операционной системы",
                "Память и виртуализация", "Файловые системы", "Ввод-вывод",
                "Контейнеры и изоляция", "Сети в операционной системе",
                "Администрирование и мониторинг"]},
    {"code": "demo_math", "title": "Прикладная математика (демо)",
     "keyword": "модель", "scheduled": False, "elective": False,
     "topics": ["Дискретные структуры", "Матрицы и линейная алгебра",
                "Теория графов", "Комбинаторика", "Вероятностные модели",
                "Статистические оценки", "Численные методы", "Оптимизация"]},
    {"code": "demo_crypto", "title": "Криптографические протоколы (демо)",
     "keyword": "протокол", "scheduled": False, "elective": True,
     "topics": ["Симметричные шифры", "Режимы блочного шифрования",
                "Хэш-функции", "Электронная подпись", "Протоколы обмена ключами",
                "Инфраструктура открытых ключей", "Протокол TLS",
                "Постквантовая криптография"]},
]
_LESSON_TYPE_BY_ORDER = ["lecture", "practice", "lab",
                         "lecture", "practice", "lecture", "lab", "practice"]
_HOURS_BY_TYPE = {"lecture": 2, "practice": 2, "lab": 4}
_TAGS_BY_TYPE = {"lecture": ["теория"], "practice": ["практика"],
                 "lab": ["лаборатория", "оборудование"]}
@dataclass(frozen=True)
class DemoParams:
    seed: int = 20260907
    students_total: int = 104
    groups_count: int = 4
    weeks: int = 16
    scheduled_courses: int = 6
    materials_per_lecture: int = 2
    present_rate: float = 0.85
    first_monday: date = FIRST_MONDAY
    def __post_init__(self) -> None:
        if not (0 <= self.seed <= 2**63 - 1):
            raise ValueError("seed должен быть целым 0..2^63-1")
        if not (1 <= self.groups_count <= 20):
            raise ValueError("groups_count должен быть 1..20")
        if self.students_total <= 0 or self.students_total % self.groups_count:
            raise ValueError(
                "students_total должен делиться на groups_count без остатка")
        if not (1 <= self.weeks <= WEEKS_IN_DDL):
            raise ValueError(f"weeks должен быть 1..{WEEKS_IN_DDL} "
                             "(партиции DDL созданы на 16 недель от 2026-09-07)")
        if self.first_monday != FIRST_MONDAY:
            raise ValueError("first_monday зафиксирован DDL: 2026-09-07")
        if not (1 <= self.scheduled_courses <= 6):
            raise ValueError("scheduled_courses должен быть 1..6")
        if not (0.5 <= self.present_rate <= 1.0):
            raise ValueError("present_rate должен быть 0.5..1.0")
        if self.materials_per_lecture not in (1, 2, 3):
            raise ValueError("materials_per_lecture должен быть 1..3")
    def fingerprint(self) -> str:
        payload = {
            "version": 1, "seed": self.seed,
            "students_total": self.students_total, "groups_count": self.groups_count,
            "weeks": self.weeks, "scheduled_courses": self.scheduled_courses,
            "materials_per_lecture": self.materials_per_lecture,
            "present_rate": self.present_rate,
            "first_monday": self.first_monday.isoformat(),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False)
            .encode("utf-8")).hexdigest()
    def canonical(self) -> dict[str, Any]:
        return {
            "seed": self.seed, "students": self.students_total,
            "groups": self.groups_count, "weeks": self.weeks,
            "scheduled_courses": self.scheduled_courses,
            "materials_per_lecture": self.materials_per_lecture,
            "present_rate": self.present_rate,
            "fingerprint": self.fingerprint(),
        }
@dataclass
class DemoDataset:
    params: DemoParams
    universities: list[dict[str, Any]] = field(default_factory=list)
    institutes: list[dict[str, Any]] = field(default_factory=list)
    departments: list[dict[str, Any]] = field(default_factory=list)
    specialties: list[dict[str, Any]] = field(default_factory=list)
    department_specialties: list[dict[str, Any]] = field(default_factory=list)
    groups: list[dict[str, Any]] = field(default_factory=list)
    students: list[dict[str, Any]] = field(default_factory=list)
    courses: list[dict[str, Any]] = field(default_factory=list)
    lectures: list[dict[str, Any]] = field(default_factory=list)
    materials: list[dict[str, Any]] = field(default_factory=list)
    schedule: list[dict[str, Any]] = field(default_factory=list)
    attendance: list[dict[str, Any]] = field(default_factory=list)
    def synthetic_metadata(self) -> dict[str, Any]:
        return {
            "synthetic": True,
            "data_mode": "demo",
            "generator": "lab1-demo-generator",
            "seed": self.params.seed,
            "note": SYNTHETIC_NOTE,
        }
    def expected_counts(self) -> dict[str, int]:
        per_group = self.params.weeks * 3
        completed_weeks = min(10, self.params.weeks)
        completed = self.params.groups_count * (completed_weeks * 3 - 2) \
            if completed_weeks else 0
        cancelled = self.params.groups_count * 2
        scheduled = self.params.groups_count * (per_group - completed_weeks * 3)
        students_per_group = self.params.students_total // self.params.groups_count
        return {
            "universities": len(self.universities),
            "institutes": len(self.institutes),
            "departments": len(self.departments),
            "specialties": len(self.specialties),
            "department_specialties": len(self.department_specialties),
            "study_groups": len(self.groups),
            "students": len(self.students),
            "courses": len(self.courses),
            "lectures": len(self.lectures),
            "lecture_materials": len(self.materials),
            "schedule": len(self.schedule),
            "schedule_completed": completed,
            "schedule_cancelled": cancelled,
            "schedule_scheduled": scheduled,
            "attendance": len(self.attendance),
            "attendance_present": sum(1 for a in self.attendance if a["is_present"]),
            "attendance_absent": sum(1 for a in self.attendance if not a["is_present"]),
            "students_per_group": students_per_group,
        }
def _rng(*parts: Any) -> random.Random:
    return random.Random("lab1-demo|" + "|".join(str(p) for p in parts))
def build_demo_dataset(params: DemoParams) -> DemoDataset:
    if params.first_monday != FIRST_MONDAY or FIRST_MONDAY.isoweekday() != 1:
        raise ValueError("Период демо-набора зафиксирован: понедельник 2026-09-07")
    ds = DemoDataset(params=params)
    meta = ds.synthetic_metadata()
    ds.universities.append({
        "code": "DEMO", "name": "Демонстрационный университет (синтетический набор ЛР1)",
        "short_name": "ДемоУ", "address": "г. Москва, Демонстрационная ул., 1 (синтетический адрес)",
        "website": "https://demo.example"})
    ds.institutes.append({"university_local": 1, "code": "ИКБ-Д",
                          "name": "Институт кибербезопасности (демо)"})
    ds.institutes.append({"university_local": 1, "code": "ИТИ-Д",
                          "name": "Институт информационных технологий (демо)"})
    ds.departments.append({"institute_local": 1, "code": "КБ-Д1",
                           "name": "Кафедра информационной безопасности (демо)"})
    ds.departments.append({"institute_local": 1, "code": "КБ-Д2",
                           "name": "Кафедра криптографии (демо)"})
    ds.departments.append({"institute_local": 2, "code": "ИТ-Д1",
                           "name": "Кафедра информационных систем (демо)"})
    ds.specialties.append({"code": "09.03.02",
                           "name": "Информационные системы и технологии (демо)",
                           "degree_level": "bachelor", "duration_years": 4})
    ds.specialties.append({"code": "01.03.04", "name": "Прикладная математика (демо)",
                           "degree_level": "bachelor", "duration_years": 4})
    ds.department_specialties.append({"department_local": 1, "specialty_local": 1,
                                      "is_primary": True})
    ds.department_specialties.append({"department_local": 2, "specialty_local": 1,
                                      "is_primary": False})
    ds.department_specialties.append({"department_local": 3, "specialty_local": 2,
                                      "is_primary": True})
    students_per_group = params.students_total // params.groups_count
    for g in range(1, params.groups_count + 1):
        rng = _rng(params.seed, "group", g)
        curator = f"{rng.choice(_SURNAMES)} {rng.choice(_FIRST_NAMES)} {rng.choice(_PATRONYMICS)}"
        ds.groups.append({
            "group_local": g, "specialty_local": 1, "department_local": 1,
            "code": f"ДЕМО-1{g}-26", "training_profile": "Безопасность программных решений (демо)",
            "enrollment_year": 2023, "curator_name": curator})
    for i in range(1, params.students_total + 1):
        group_local = (i - 1) // students_per_group + 1
        rng = _rng(params.seed, "student", i)
        status = "academic_leave" if (i % 51 == 0 and i > 1) else "active"
        ds.students.append({
            "student_local": i, "group_local": group_local,
            "record_book": f"26Д{i:04d}",
            "last_name": rng.choice(_SURNAMES),
            "first_name": rng.choice(_FIRST_NAMES),
            "patronymic": rng.choice(_PATRONYMICS) if rng.random() < 0.92 else None,
            "email": f"stud{i:04d}@demo.example",
            "phone": f"+7 900 {100 + i % 900:03d} {10 + i % 80:02d} {10 + i % 60:02d}",
            "enrollment_date": date(2023, 9, 1), "status": status})
    for grp in ds.groups:
        grp["leader_student_local"] = next(
            s["student_local"] for s in ds.students
            if s["group_local"] == grp["group_local"])
    lecture_local = 0
    material_local = 0
    scheduled_idx = 0
    for course_local, course in enumerate(_COURSES, start=1):
        if course["scheduled"]:
            if scheduled_idx >= params.scheduled_courses:
                continue
            scheduled_idx += 1
        ds.courses.append({
            "course_local": course_local, "code": course["code"],
            "title": course["title"],
            "description": f"Синтетический демонстрационный курс; термин материалов: {course['keyword']}",
            "specialty_local": 1 if course["code"] != "demo_math" else 2,
            "department_local": {
                "demo_math": 3, "demo_crypto": 2}.get(course["code"], 1),
            "academic_year_start": 2026,
            "semester": 7 if course["code"] != "demo_math" else 3,
            "is_elective": bool(course["elective"]),
            "scheduled": bool(course["scheduled"]),
            "teacher_name": _TEACHERS[(course_local - 1) % len(_TEACHERS)],
            "keyword": course["keyword"]})
        for order, topic in enumerate(course["topics"], start=1):
            lecture_local += 1
            lesson_type = _LESSON_TYPE_BY_ORDER[order - 1]
            ds.lectures.append({
                "lecture_local": lecture_local, "course_local": course_local,
                "title": f"{topic}", "annotation": f"Синтетическая тема занятия (демо): {topic}",
                "lesson_type": lesson_type, "order_number": order,
                "academic_hours": _HOURS_BY_TYPE[lesson_type],
                "tags": list(_TAGS_BY_TYPE[lesson_type]),
                "requires_equipment": lesson_type == "lab"})
            for pos in range(1, params.materials_per_lecture + 1):
                material_local += 1
                kind = "конспект" if pos == 1 else "презентация"
                ds.materials.append({
                    "material_local": material_local,
                    "lecture_local": lecture_local,
                    "material_type": "text",
                    "title": f"{topic} — {kind} (демо)",
                    "position": pos,
                    "metadata": dict(meta, material_kind=kind),
                    "content_text": _material_text(topic, course, kind)})
    scheduled_courses = [c for c in ds.courses if c["scheduled"]]
    lessons_total = len(scheduled_courses) * 8
    if lessons_total % 3:
        pass
    weeks_needed = (lessons_total + 2) // 3
    if weeks_needed > params.weeks:
        raise ValueError("Недостаточно недель для выбранных курсов")
    schedule_local = 0
    for grp in ds.groups:
        g = grp["group_local"]
        for j in range(lessons_total):
            course = scheduled_courses[j % len(scheduled_courses)]
            k = j // len(scheduled_courses) + 1
            week, slot = j // 3, j % 3
            lecture = next(l for l in ds.lectures
                           if l["course_local"] == course["course_local"]
                           and l["order_number"] == k)
            weekday, starts_at, ends_at = _SLOTS[slot]
            scheduled_date = params.first_monday + timedelta(days=week * 7 + weekday)
            week_start = params.first_monday + timedelta(days=week * 7)
            if week < min(10, params.weeks):
                status = "completed"
            else:
                status = "scheduled"
            cancelled = j in (10 + g, 23 - g) and week < min(10, params.weeks)
            if cancelled:
                status = "cancelled"
            classroom = (f"А-{100 + slot}" if lecture["lesson_type"] == "lecture"
                         else f"Б-{g}0{slot + 1}")
            schedule_local += 1
            ds.schedule.append({
                "schedule_local": schedule_local,
                "lecture_local": lecture["lecture_local"],
                "group_local": g, "scheduled_date": scheduled_date,
                "week_start_date": week_start, "starts_at": starts_at,
                "ends_at": ends_at, "classroom": classroom,
                "teacher_name": course["teacher_name"], "status": status})
    students_by_group: dict[int, list[dict]] = {}
    for s in ds.students:
        students_by_group.setdefault(s["group_local"], []).append(s)
    for row in ds.schedule:
        if row["status"] != "completed":
            continue
        for s in students_by_group[row["group_local"]]:
            rng = _rng(params.seed, "attendance", s["student_local"],
                       row["schedule_local"])
            is_present = rng.random() < params.present_rate
            note = None
            if not is_present and rng.random() < 0.3:
                note = "пропуск по уважительной причине (демо)"
            ds.attendance.append({
                "schedule_local": row["schedule_local"],
                "student_local": s["student_local"],
                "week_start_date": row["week_start_date"],
                "is_present": is_present,
                "recorded_at": datetime.combine(
                    row["scheduled_date"], time(18, 0), tzinfo=timezone.utc),
                "marked_by": row["teacher_name"], "note": note})
    return ds
def _material_text(topic: str, course: dict[str, Any], kind: str) -> str:
    keyword = course["keyword"]
    return (
        f"{topic} — {kind} синтетического демонстрационного курса "
        f"«{course['title']}». Материал описывает базовые понятия темы, "
        f"приводит примеры и контрольные вопросы. Ключевые слова: {keyword}, "
        f"демонстрация, синтетический набор. Содержимое сгенерировано "
        f"детерминированно для стенда ЛР1 и не относится к реальным данным ПР3.")
def search_term_for_selftest(params: DemoParams) -> str:
    return "целостность"
def validate_against_ddl_invariants(ds: DemoDataset) -> None:
    params = ds.params
    last_week = params.first_monday + timedelta(days=7 * (params.weeks - 1))
    if not (FIRST_MONDAY <= last_week
            and last_week < FIRST_MONDAY + timedelta(days=7 * WEEKS_IN_DDL)):
        raise ValueError("Недели набора выходят за диапазон партиций DDL")
    seen: set[tuple[int, int, date, time]] = set()
    for row in ds.schedule:
        monday = row["scheduled_date"] - timedelta(
            days=row["scheduled_date"].isoweekday() - 1)
        if row["week_start_date"] != monday:
            raise ValueError("week_start_date не является понедельником недели")
        if not (FIRST_MONDAY <= row["week_start_date"]
                and row["week_start_date"] < FIRST_MONDAY + timedelta(days=7 * WEEKS_IN_DDL)):
            raise ValueError("week_start_date вне диапазона партиций")
        if row["ends_at"] <= row["starts_at"]:
            raise ValueError("ends_at должен быть больше starts_at")
        key = (row["lecture_local"], row["group_local"],
               row["scheduled_date"], row["starts_at"])
        if key in seen:
            raise ValueError("Повтор занятия (lecture, group, date, starts_at)")
        seen.add(key)
    for lecture in ds.lectures:
        if lecture["lesson_type"] not in ("lecture", "practice", "lab"):
            raise ValueError("Недопустимый lesson_type")
        if lecture["academic_hours"] <= 0:
            raise ValueError("academic_hours должен быть > 0")
    for material in ds.materials:
        forbidden = {"content_text", "content", "body", "file_data", "data_base64"}
        if forbidden & set(material["metadata"]):
            raise ValueError("metadata материала не должен содержать полные тексты")
    for course in ds.courses:
        if not (1 <= course["semester"] <= 12):
            raise ValueError("semester вне диапазона 1..12")

import json
import logging
from pathlib import Path
from typing import Any
import httpx
logger = logging.getLogger("lab1.generator.loading")
SCHEMA_SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "schema_from_pr3.sql"
_META_DDL = """
CREATE SCHEMA IF NOT EXISTS demo_generator;
CREATE TABLE IF NOT EXISTS demo_generator.current_dataset (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    fingerprint text NOT NULL,
    seed bigint NOT NULL,
    params jsonb NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);
"""
_ES_MAPPING = {
    "dynamic": "strict",
    "properties": {
        "content_text": {"type": "text", "analyzer": "russian"},
        "course_id": {"type": "long"},
        "id": {"type": "long"},
        "lecture_id": {"type": "long"},
        "material_type": {"type": "keyword"},
        "title": {"type": "text", "analyzer": "russian"},
    },
}
class DatasetConflict(Exception):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        self.details = details or {}
        super().__init__(message)
class ProjectionError(Exception):
    pass
def connect_pg(settings):
    import psycopg
    dsn = settings.pg_dsn() + " connect_timeout=10"
    return psycopg.connect(dsn)
def ensure_schema(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('practice03.attendance') IS NOT NULL")
        exists = cur.fetchone()[0]
    conn.rollback()
    if exists:
        return False
    ddl = SCHEMA_SQL_FILE.read_text(encoding="utf-8")
    autocommit = conn.autocommit
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(ddl)
    finally:
        conn.autocommit = autocommit
    logger.info("Схема practice03 создана дословным DDL из отчёта ПР3")
    return True
def inspect_current(conn) -> dict[str, Any]:
    state: dict[str, Any] = {"schema": False, "meta": None, "students": 0}
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('practice03.attendance') IS NOT NULL")
        state["schema"] = bool(cur.fetchone()[0])
        if not state["schema"]:
            return state
        cur.execute("SELECT to_regclass('demo_generator.current_dataset') IS NOT NULL")
        if cur.fetchone()[0]:
            cur.execute("SELECT fingerprint, seed, params, loaded_at "
                        "FROM demo_generator.current_dataset WHERE singleton")
            row = cur.fetchone()
            if row:
                state["meta"] = {"fingerprint": row[0], "seed": row[1],
                                 "params": row[2], "loaded_at": row[3].isoformat()}
        cur.execute("SELECT count(*) FROM practice03.students")
        state["students"] = cur.fetchone()[0]
    return state
def load_postgres(conn, dataset: DemoDataset) -> dict[str, Any]:
    params = dataset.params
    validate_against_ddl_invariants(dataset)
    counts = dataset.expected_counts()
    with conn.transaction():
        with conn.cursor() as cur:
            def insert_rows(table: str, columns: list[str],
                            rows: list[tuple]) -> list[int]:
                if not rows:
                    return []
                sql = (f"INSERT INTO practice03.{table} ({', '.join(columns)}) "
                       f"VALUES ({', '.join(['%s'] * len(columns))}) RETURNING id")
                ids: list[int] = []
                if len(rows) == 1:
                    cur.execute(sql, rows[0])
                    ids.append(cur.fetchone()[0])
                else:
                    cur.executemany(sql, rows, returning=True)
                    ids.extend(row[0] for row in cur.fetchall())
                    while cur.nextset() is not None:
                        ids.extend(row[0] for row in cur.fetchall())
                if len(ids) != len(rows):
                    raise RuntimeError(
                        f"{table}: получено {len(ids)} id вместо {len(rows)}")
                return ids
            from psycopg.types.json import Json
            u_ids = insert_rows("universities",
                                ["code", "name", "short_name", "address", "website"],
                                [(u["code"], u["name"], u["short_name"], u["address"],
                                  u["website"]) for u in dataset.universities])
            i_ids = insert_rows("institutes", ["university_id", "code", "name"],
                                [(u_ids[i["university_local"] - 1], i["code"], i["name"])
                                 for i in dataset.institutes])
            d_ids = insert_rows("departments", ["institute_id", "code", "name"],
                                [(i_ids[d["institute_local"] - 1], d["code"], d["name"])
                                 for d in dataset.departments])
            s_ids = insert_rows("specialties",
                                ["code", "name", "degree_level", "duration_years"],
                                [(s["code"], s["name"], s["degree_level"],
                                  s["duration_years"]) for s in dataset.specialties])
            cur.executemany(
                "INSERT INTO practice03.department_specialties "
                "(department_id, specialty_id, is_primary) VALUES (%s, %s, %s)",
                [(d_ids[ds["department_local"] - 1], s_ids[ds["specialty_local"] - 1],
                  ds["is_primary"]) for ds in dataset.department_specialties])
            g_ids = insert_rows(
                "study_groups",
                ["specialty_id", "department_id", "code", "training_profile",
                 "enrollment_year", "curator_name"],
                [(s_ids[g["specialty_local"] - 1], d_ids[g["department_local"] - 1],
                  g["code"], g["training_profile"], g["enrollment_year"],
                  g["curator_name"]) for g in dataset.groups])
            st_ids = insert_rows(
                "students",
                ["group_id", "record_book", "last_name", "first_name", "patronymic",
                 "email", "phone", "enrollment_date", "status"],
                [(g_ids[s["group_local"] - 1], s["record_book"], s["last_name"],
                  s["first_name"], s["patronymic"], s["email"], s["phone"],
                  s["enrollment_date"], s["status"]) for s in dataset.students])
            cur.executemany(
                "UPDATE practice03.study_groups SET group_leader_student_id = %s "
                "WHERE id = %s",
                [(st_ids[g["leader_student_local"] - 1],
                  g_ids[g["group_local"] - 1]) for g in dataset.groups])
            c_ids = insert_rows(
                "courses",
                ["specialty_id", "department_id", "code", "title", "description",
                 "academic_year_start", "semester", "is_elective"],
                [(s_ids[c["specialty_local"] - 1], d_ids[c["department_local"] - 1],
                  c["code"], c["title"], c["description"], c["academic_year_start"],
                  c["semester"], c["is_elective"]) for c in dataset.courses])
            l_ids = insert_rows(
                "lectures",
                ["course_id", "title", "annotation", "lesson_type", "order_number",
                 "academic_hours", "tags", "requires_equipment"],
                [(c_ids[l["course_local"] - 1], l["title"], l["annotation"],
                  l["lesson_type"], l["order_number"], l["academic_hours"], l["tags"],
                  l["requires_equipment"]) for l in dataset.lectures])
            insert_rows(
                "lecture_materials",
                ["lecture_id", "material_type", "title", "position", "metadata"],
                [(l_ids[m["lecture_local"] - 1], m["material_type"], m["title"],
                  m["position"], Json(m["metadata"])) for m in dataset.materials])
            sc_ids = insert_rows(
                "schedule",
                ["lecture_id", "group_id", "scheduled_date", "week_start_date",
                 "starts_at", "ends_at", "classroom", "teacher_name", "status"],
                [(l_ids[r["lecture_local"] - 1], g_ids[r["group_local"] - 1],
                  r["scheduled_date"], r["week_start_date"], r["starts_at"],
                  r["ends_at"], r["classroom"], r["teacher_name"], r["status"])
                 for r in dataset.schedule])
            cur.executemany(
                "INSERT INTO practice03.attendance "
                "(week_start_date, schedule_id, student_id, is_present, recorded_at, "
                " marked_by, note) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [(a["week_start_date"], sc_ids[a["schedule_local"] - 1],
                  st_ids[a["student_local"] - 1], a["is_present"], a["recorded_at"],
                  a["marked_by"], a["note"]) for a in dataset.attendance])
            cur.execute(_META_DDL)
            cur.execute(
                "INSERT INTO demo_generator.current_dataset "
                "(singleton, fingerprint, seed, params) VALUES (true, %s, %s, %s) "
                "ON CONFLICT (singleton) DO UPDATE SET fingerprint = EXCLUDED.fingerprint, "
                "seed = EXCLUDED.seed, params = EXCLUDED.params, loaded_at = now()",
                (params.fingerprint(), params.seed, Json(params.canonical())))
    return counts
def read_snapshot(conn) -> dict[str, Any]:
    snap: dict[str, Any] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT id, code, name, short_name, address, website "
                    "FROM practice03.universities ORDER BY id")
        snap["universities"] = cur.fetchall()
        cur.execute("SELECT id, university_id, code, name FROM practice03.institutes ORDER BY id")
        snap["institutes"] = cur.fetchall()
        cur.execute("SELECT id, institute_id, code, name FROM practice03.departments ORDER BY id")
        snap["departments"] = cur.fetchall()
        cur.execute("SELECT ds.department_id, s.id, s.code, s.name, ds.is_primary "
                    "FROM practice03.department_specialties ds "
                    "JOIN practice03.specialties s ON s.id = ds.specialty_id "
                    "ORDER BY ds.department_id, s.id")
        snap["dept_specialties"] = cur.fetchall()
        cur.execute("SELECT id, department_id, specialty_id, code, title, description, "
                    "academic_year_start, semester, is_elective "
                    "FROM practice03.courses ORDER BY id")
        snap["courses"] = cur.fetchall()
        cur.execute("SELECT id, course_id, title, lesson_type, order_number, "
                    "academic_hours, tags, requires_equipment, equipment_requirements, annotation "
                    "FROM practice03.lectures ORDER BY id")
        snap["lectures"] = cur.fetchall()
        cur.execute("SELECT id, specialty_id, department_id, code, enrollment_year FROM practice03.study_groups ORDER BY id")
        snap["groups"] = cur.fetchall()
        cur.execute("SELECT st.id, st.group_id, st.record_book, st.last_name, "
                    "st.first_name, st.patronymic, st.email, st.phone, "
                    "st.enrollment_date, st.status "
                    "FROM practice03.students st ORDER BY st.id")
        snap["students"] = cur.fetchall()
        cur.execute("SELECT id, lecture_id, group_id, scheduled_date, starts_at, "
                    "ends_at, classroom, teacher_name, status "
                    "FROM practice03.schedule ORDER BY id")
        snap["schedule"] = cur.fetchall()
        cur.execute("SELECT m.id, m.lecture_id, l.course_id, m.title, m.material_type, m.position "
                    "FROM practice03.lecture_materials m "
                    "JOIN practice03.lectures l ON l.id = m.lecture_id ORDER BY m.id")
        snap["materials"] = cur.fetchall()
        cur.execute("SELECT DISTINCT st.id, l.course_id FROM practice03.students st "
                    "JOIN practice03.schedule sc ON sc.group_id = st.group_id "
                    "AND sc.status <> 'cancelled' "
                    "JOIN practice03.lectures l ON l.id = sc.lecture_id "
                    "ORDER BY st.id, l.course_id")
        snap["enrollments"] = cur.fetchall()
    return snap
def project_elasticsearch(settings, snapshot: dict[str, Any],
                          dataset: DemoDataset) -> int:
    texts = {(m["title"], m["position"]): m["content_text"]
             for m in dataset.materials}
    lines: list[str] = []
    for mat_id, lecture_id, course_id, title, material_type, position in snapshot["materials"]:
        doc = {"id": mat_id, "lecture_id": lecture_id, "course_id": course_id,
               "title": title,
               "content_text": texts.get((title, position), title),
               "material_type": material_type}
        lines.append(json.dumps({"index": {"_index": settings.es_index, "_id": mat_id}},
                                ensure_ascii=False))
        lines.append(json.dumps(doc, ensure_ascii=False))
    body = ("\n".join(lines) + "\n").encode("utf-8")
    with httpx.Client(base_url=settings.es_url, timeout=settings.es_timeout) as client:
        if client.get(f"/{settings.es_index}").status_code == 404:
            client.put(f"/{settings.es_index}", json={
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "mappings": _ES_MAPPING})
        response = client.post("/_bulk?refresh=wait_for", content=body,
                               headers={"content-type": "application/x-ndjson"})
        if response.status_code >= 300 or response.json().get("errors"):
            raise ProjectionError("Elasticsearch bulk failed")
        return len(snapshot["materials"])
def project_redis(settings, snapshot: dict[str, Any]) -> int:
    import redis
    client = redis.Redis(host=settings.redis_host, port=settings.redis_port,
                         db=settings.redis_db, decode_responses=True,
                         socket_connect_timeout=10, socket_timeout=30)
    pipe = client.pipeline(transaction=False)
    for (sid, group_id, record_book, last_name, first_name, patronymic,
         email, phone, enrollment_date, status) in snapshot["students"]:
        pipe.hset(record_book, mapping={
            "id": sid, "group_id": group_id, "record_book": record_book,
            "last_name": last_name, "first_name": first_name,
            "patronymic": patronymic or "", "email": email or "",
            "phone": phone or "", "enrollment_date": enrollment_date.isoformat(),
            "status": status})
    pipe.execute()
    client.close()
    return len(snapshot["students"])
_NEO4J_NODES = {
    "Department": "UNWIND $rows AS row MERGE (d:Practice03:Department {id: row.id}) "
                  "SET d.code = row.code, d.name = row.name",
    "Specialty": "UNWIND $rows AS row MERGE (s:Practice03:Specialty {id: row.id}) "
                 "SET s.code = row.code, s.name = row.name",
    "Course": "UNWIND $rows AS row MERGE (c:Practice03:Course {id: row.id}) "
              "SET c.code = row.code, c.title = row.title",
    "Lecture": "UNWIND $rows AS row MERGE (l:Practice03:Lecture {id: row.id}) "
               "SET l.title = row.title, l.lesson_type = row.lesson_type, "
               "l.order_number = row.order_number, l.requires_equipment = row.requires_equipment, l.tags = row.tags",
    "Group": "UNWIND $rows AS row MERGE (g:Practice03:Group {id: row.id}) "
             "SET g.code = row.code, g.enrollment_year = row.enrollment_year",
    "Student": "UNWIND $rows AS row MERGE (st:Practice03:Student {id: row.id}) "
               "SET st.record_book = row.record_book, st.last_name = row.last_name, "
               "st.first_name = row.first_name, st.status = row.status, st.enrollment_date = row.enrollment_date",
    "Schedule": "UNWIND $rows AS row MERGE (sc:Practice03:Schedule {id: row.id}) "
                "SET sc.scheduled_date = row.scheduled_date, sc.starts_at = row.starts_at, "
                "sc.ends_at = row.ends_at, sc.classroom = row.classroom, "
                "sc.teacher_name = row.teacher_name, sc.status = row.status",
}
_NEO4J_RELATIONS = [
    ("Department", "TRAINS_FOR", "Specialty"),
    ("Department", "TEACHES", "Course"),
    ("Course", "IN_SPECIALTY", "Specialty"),
    ("Course", "HAS_LESSON", "Lecture"),
    ("Group", "STUDIES_SPECIALTY", "Specialty"),
    ("Student", "MEMBER_OF", "Group"),
    ("Group", "HAS_SCHEDULE", "Schedule"),
    ("Schedule", "FOR_LECTURE", "Lecture"),
    ("Student", "ENROLLED_IN", "Course"),
]
def project_neo4j(settings, snapshot: dict[str, Any]) -> dict[str, int]:
    from neo4j import GraphDatabase
    group_specialty = {row[0]: row[1] for row in snapshot["groups"]}
    nodes = {
        "Department": [{"id": d[0], "code": d[2], "name": d[3]}
                       for d in snapshot["departments"]],
        "Specialty": [{"id": s[0], "code": s[1], "name": s[2]}
                      for s in {row[1]: (row[1], row[2], row[3])
                                for row in snapshot["dept_specialties"]}.values()],
        "Course": [{"id": c[0], "code": c[3], "title": c[4]}
                   for c in snapshot["courses"]],
        "Lecture": [{"id": l[0], "title": l[2], "lesson_type": l[3],
                     "order_number": l[4], "requires_equipment": bool(l[7]), "tags": l[6]}
                    for l in snapshot["lectures"]],
        "Group": [{"id": g[0], "code": g[3], "enrollment_year": g[4]} for g in snapshot["groups"]],
        "Student": [{"id": s[0], "record_book": s[2], "last_name": s[3],
                     "first_name": s[4], "status": s[9], "enrollment_date": s[8].isoformat()} for s in snapshot["students"]],
        "Schedule": [{"id": r[0], "scheduled_date": r[3].isoformat(),
                      "starts_at": r[4].isoformat(), "ends_at": r[5].isoformat(),
                      "classroom": r[6], "teacher_name": r[7], "status": r[8]}
                     for r in snapshot["schedule"]],
    }
    course_specialty = {c[0]: c[2] for c in snapshot["courses"]}
    course_dept = {c[0]: c[1] for c in snapshot["courses"]}
    lecture_course = {l[0]: l[1] for l in snapshot["lectures"]}
    schedule_group = {r[0]: r[2] for r in snapshot["schedule"]}
    schedule_lecture = {r[0]: r[1] for r in snapshot["schedule"]}
    student_group = {s[0]: s[1] for s in snapshot["students"]}
    relations = {
        ("Department", "TRAINS_FOR", "Specialty"): [
            {"from": row[0], "to": row[1]} for row in snapshot["dept_specialties"]],
        ("Department", "TEACHES", "Course"): [
            {"from": course_dept[c[0]], "to": c[0]} for c in snapshot["courses"]],
        ("Course", "IN_SPECIALTY", "Specialty"): [
            {"from": c[0], "to": course_specialty[c[0]]} for c in snapshot["courses"]],
        ("Course", "HAS_LESSON", "Lecture"): [
            {"from": lecture_course[l[0]], "to": l[0]} for l in snapshot["lectures"]],
        ("Group", "STUDIES_SPECIALTY", "Specialty"): [
            {"from": g[0], "to": group_specialty[g[0]]} for g in snapshot["groups"]],
        ("Student", "MEMBER_OF", "Group"): [
            {"from": sid, "to": gid} for sid, gid in student_group.items()],
        ("Group", "HAS_SCHEDULE", "Schedule"): [
            {"from": schedule_group[r[0]], "to": r[0]} for r in snapshot["schedule"]],
        ("Schedule", "FOR_LECTURE", "Lecture"): [
            {"from": r[0], "to": schedule_lecture[r[0]]} for r in snapshot["schedule"]],
        ("Student", "ENROLLED_IN", "Course"): [
            {"from": sid, "to": cid} for sid, cid in snapshot["enrollments"]],
    }
    driver = GraphDatabase.driver(settings.neo4j_uri,
                                  auth=(settings.neo4j_user, settings.neo4j_password),
                                  connection_timeout=15)
    try:
        driver.verify_connectivity()
        with driver.session() as session:
            for label, cypher in _NEO4J_NODES.items():
                session.run(cypher, rows=nodes[label])
            for from_label, rel, to_label in _NEO4J_RELATIONS:
                rows = relations[(from_label, rel, to_label)]
                if not rows:
                    continue
                session.run(
                    f"UNWIND $rows AS row "
                    f"MATCH (a:Practice03:{from_label} {{id: row.from}}), "
                    f"(b:Practice03:{to_label} {{id: row.to}}) "
                    f"MERGE (a)-[:{rel}]->(b)", rows=rows)
        return {label: len(rows) for label, rows in nodes.items()} | {
            f"{a}-{rel}->{b}": len(rows) for (a, rel, b), rows in relations.items()}
    finally:
        driver.close()
def project_mongo(settings, snapshot: dict[str, Any]) -> int:
    from pymongo import MongoClient, ReplaceOne

    lessons = defaultdict(list)
    for lecture in snapshot["lectures"]:
        lessons[lecture[1]].append({
            "id": lecture[0], "title": lecture[2], "lesson_type": lecture[3],
            "order_number": lecture[4], "academic_hours": lecture[5], "tags": lecture[6],
            "requires_equipment": lecture[7], "technical_requirements": lecture[8],
            "annotation": lecture[9],
        })

    courses = defaultdict(list)
    for cid, department_id, specialty_id, code, title, description, year, semester, elective in snapshot["courses"]:
        courses[department_id, specialty_id].append({
            "id": cid, "code": code, "title": title, "description": description,
            "academic_year_start": year, "semester": semester, "is_elective": elective,
            "lectures": lessons[cid],
        })

    specialties = defaultdict(list)
    for department_id, sid, code, name, primary in snapshot["dept_specialties"]:
        specialties[department_id].append({
            "id": sid, "code": code, "name": name, "is_primary": primary,
            "courses": courses[department_id, sid],
        })

    departments = defaultdict(list)
    for did, institute_id, code, name in snapshot["departments"]:
        departments[institute_id].append({
            "id": did, "code": code, "name": name, "specialties": specialties[did],
        })

    institutes = defaultdict(list)
    for iid, university_id, code, name in snapshot["institutes"]:
        institutes[university_id].append({
            "id": iid, "code": code, "name": name, "departments": departments[iid],
        })

    operations = [
        ReplaceOne({"_id": uid}, {
            "_id": uid, "code": code, "name": name, "short_name": short_name,
            "address": address, "website": website, "institutes": institutes[uid],
        }, upsert=True)
        for uid, code, name, short_name, address, website in snapshot["universities"]
    ]
    with MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=10000) as client:
        client.practice03.universities.bulk_write(operations)
    return len(operations)

def run_demo_generation(settings, params: DemoParams) -> dict[str, Any]:
    settings.validate_runtime()
    dataset = build_demo_dataset(params)
    expected = dataset.expected_counts()
    result: dict[str, Any] = {
        "dataset": dataset.synthetic_metadata() | {"params": params.canonical()},
        "expected_counts": expected,
    }
    conn = connect_pg(settings)
    try:
        ensure_schema(conn)
        conn.rollback()
        state = inspect_current(conn)
        conn.rollback()
        meta = state["meta"]
        if meta is not None and meta["fingerprint"] != params.fingerprint():
            raise DatasetConflict(
                "В demo-БД уже загружен другой набор; смена seed/size на непустой "
                "БД запрещена (очистка/пересоздание не выполняются)",
                details={"current": {"fingerprint": meta["fingerprint"],
                                     "seed": meta["seed"]},
                         "requested": {"fingerprint": params.fingerprint(),
                                       "seed": params.seed}})
        if meta is None and state["students"] > 0:
            raise DatasetConflict(
                "demo-БД содержит неизвестные данные practice03 без метки "
                "генератора; загрузка поверх них запрещена")
        if meta is None:
            result["postgres_loaded"] = True
            load_postgres(conn, dataset)
            conn.commit()
        else:
            result["postgres_loaded"] = False
        conn.execute((SCHEMA_SQL_FILE.parent / "report_data.sql").read_text())
        conn.commit()
        snapshot = read_snapshot(conn)
        conn.rollback()
    finally:
        conn.close()
    result["projections"] = {
        "elasticsearch": {"documents": project_elasticsearch(settings, snapshot, dataset)},
        "redis": {"cards": project_redis(settings, snapshot)},
        "neo4j": project_neo4j(settings, snapshot),
        "mongodb": {"universities": project_mongo(settings, snapshot)},
    }
    if result["projections"]["elasticsearch"]["documents"] != expected["lecture_materials"] or result["projections"]["redis"]["cards"] != expected["students"]:
        raise ProjectionError("Количество документов проекций не совпало с PostgreSQL")
    result["ok"] = True
    return result
