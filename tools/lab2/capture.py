"""Capture with idempotent demo course setup of laboratory 2 evidence through the public Gateway."""

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

OUT = Path(__file__).resolve().parents[2] / "docs/lab2"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://localhost:8000"
trace = []
token = ""


def get(path, params=(), auth=True):
    url = BASE + path + ("?" + urlencode(params, doseq=True) if params else "")
    request = Request(url, headers={"Authorization": "Bearer " + token} if auth else {})
    try:
        with urlopen(request, timeout=60) as response:
            status, body = response.status, json.load(response)
    except HTTPError as error:
        status, body = error.code, json.load(error)
    trace.append(
        {
            "method": "GET",
            "url": url,
            "authenticated": auth,
            "status": status,
            "response": body,
        }
    )
    return status, body


def pages(path, params):
    result = []
    while True:
        status, body = get(path, [*params, ("limit", 100), ("offset", len(result))])
        assert status == 200, body
        result.extend(body["items"])
        if len(result) == body["total"]:
            return result
        assert body["items"]


request = Request(
    BASE + "/api/v1/auth/token",
    data=json.dumps({"username": "api-user", "password": "api-password"}).encode(),
    headers={"Content-Type": "application/json"},
)
with urlopen(request) as response:
    credentials = json.load(response)
    token = credentials["access_token"]
trace.append(
    {
        "method": "POST",
        "url": BASE + "/api/v1/auth/token",
        "status": 200,
        "response": {
            "token_type": credentials["token_type"],
            "access_token": "<скрыт>",
        },
    }
)
courses = pages("/api/v1/academic/courses", [])
source = next(c for c in courses if c["semester"] == 1)
course = next(
    (c for c in courses if c["name"] == "LAB2-DEMO Технические средства обучения"), None
)


def create(path, data):
    request = Request(
        BASE + path,
        data=json.dumps(data).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
        },
    )
    with urlopen(request) as response:
        body = json.load(response)
        trace.append(
            {
                "method": "POST",
                "url": BASE + path,
                "body": data,
                "status": response.status,
                "response": body,
            }
        )
        return body


if course is None:
    course = create(
        "/api/v1/academic/courses",
        dict(
            specialty_id=source["specialty_id"],
            name="LAB2-DEMO Технические средства обучения",
            description="Контрольный курс для отчёта о вместимости аудитории ЛР2",
            semester=1,
            total_hours=6,
            lecture_hours=4,
            practice_hours=2,
        ),
    )
existing = pages("/api/v1/academic/lectures", [("course_id", course["id"])])
for number, title, kind, requirements in [
    (
        1,
        "Презентация архитектурных решений",
        "lecture",
        "Проектор, экран, компьютер преподавателя",
    ),
    (
        2,
        "Практическое моделирование",
        "practice",
        "Компьютеры для каждого слушателя, доступ в Интернет",
    ),
    (3, "Обсуждение решений", "lecture", None),
]:
    if not any(lecture["order_number"] == number for lecture in existing):
        create(
            "/api/v1/academic/lectures",
            dict(
                course_id=course["id"],
                title=title,
                lecture_type=kind,
                order_number=number,
                requirements=requirements,
            ),
        )
lectures = pages("/api/v1/academic/lectures", [("course_id", course["id"])])
groups = pages(
    "/api/v1/students/groups",
    [("specialty_id", course["specialty_id"]), ("enrollment_year", 2026)],
)
students = []
for group in groups:
    students.extend(
        pages(
            "/api/v1/students/students",
            [("group_id", group["id"]), ("status", "active")],
        )
    )
query = [
    ("course_id", course["id"]),
    ("semester", 1),
    ("study_year", 1),
    ("academic_year", 2026),
]
path = "/api/v1/reports/classroom-capacity"
assert get(path, query, False)[0] == 401
status, report = get(path, query)
assert status == 200, report
expected = sorted(
    [lecture for lecture in lectures if (lecture.get("requirements") or "").strip()],
    key=lambda lecture: (lecture["order_number"], lecture["id"]),
)
assert [i["lecture"] for i in report["items"]] == expected
assert report["listener_count"] == len({s["id"] for s in students})
assert all(i["required_seats"] == len(students) for i in report["items"])
assert len(get(path, query + [("equipment_term", "ПРОЕКТОР")])[1]["items"]) == 1
assert (
    get(path, query + [("equipment_term", "несуществующееоборудование")])[1]["items"]
    == []
)
assert get(path, [(k, 2 if k == "study_year" else v) for k, v in query])[0] == 422
assert (
    get(
        path,
        [
            (k, "00000000-0000-0000-0000-000000000000" if k == "course_id" else v)
            for k, v in query
        ],
    )[0]
    == 404
)
evidence = {
    "captured_at": datetime.now(UTC).isoformat(),
    "course": course,
    "groups": groups,
    "student_count": len(students),
    "lecture_count": len(lectures),
    "report": report,
    "requests": trace,
}
(OUT / "evidence.json").write_text(
    json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
)
print(
    json.dumps(
        {
            "students": len(students),
            "groups": len(groups),
            "lectures": len(lectures),
            "matching": len(report["items"]),
            "required_seats": report["required_seats"],
        },
        ensure_ascii=False,
    )
)
