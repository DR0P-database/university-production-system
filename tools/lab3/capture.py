"""Read-only verification of practice 3 through Gateway; stdlib only."""

import argparse
import json
from datetime import date, datetime, time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--group-id", help="Default: first SEED group by name")
    parser.add_argument("--tag", default="специальная-дисциплина")
    parser.add_argument(
        "--as-of-date",
        type=date.fromisoformat,
        help="Report date: YYYY-MM-DD (default: today)",
    )
    args = parser.parse_args()
    trace = []
    token = ""

    def get(path, params=(), auth=True):
        url = (
            args.base_url.rstrip("/")
            + path
            + ("?" + urlencode(params) if params else "")
        )
        req = Request(url, headers={"Authorization": "Bearer " + token} if auth else {})
        try:
            with urlopen(req, timeout=90) as response:
                status, body = response.status, json.load(response)
        except HTTPError as error:
            status, body = error.code, json.load(error)
        trace.append(
            dict(
                method="GET", url=url, authenticated=auth, status=status, response=body
            )
        )
        return status, body

    def one(path):
        status, body = get(path)
        assert status == 200, body
        return body

    def pages(path, params=()):
        rows = []
        while True:
            status, body = get(path, [*params, ("limit", 100), ("offset", len(rows))])
            assert status == 200, body
            rows.extend(body["items"])
            if len(rows) == body["total"]:
                return rows
            assert body["items"], "Incomplete pagination"

    req = Request(
        args.base_url.rstrip("/") + "/api/v1/auth/token",
        data=json.dumps({"username": "api-user", "password": "api-password"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=30) as response:
        token = json.load(response)["access_token"]
    groups = pages("/api/v1/students/groups")
    candidates = sorted(
        (g for g in groups if g["name"].startswith("SEED-")),
        key=lambda g: (g["name"], g["id"]),
    )
    assert args.group_id or candidates, "No SEED groups. Run seed-data first."
    group_id = args.group_id or candidates[0]["id"]
    group = one("/api/v1/students/groups/" + group_id)
    students = pages("/api/v1/students/students", [("group_id", group_id)])
    courses = pages(
        "/api/v1/academic/courses", [("specialty_id", group["specialty_id"])]
    )
    schedules = pages("/api/v1/schedule", [("group_id", group_id)])
    lectures = {}
    for course in courses:
        for lecture in pages(
            "/api/v1/academic/lectures", [("course_id", course["id"])]
        ):
            lectures[lecture["id"]] = lecture
    now = datetime.now(ZoneInfo("Europe/Moscow")).replace(tzinfo=None)
    report_date = args.as_of_date or now.date()
    cutoff = min(now, datetime.combine(report_date, time.max))
    expected = {}
    breakdown = []
    # Independently read marks one lesson at a time; no report-service code imported.
    attendance = {}
    for lesson in schedules:
        lecture = lectures.get(lesson["lecture_id"])
        included = bool(
            lecture
            and lecture["lecture_type"] == "lecture"
            and args.tag in lecture.get("tags", [])
            and lesson["status"] != "cancelled"
        )
        breakdown.append(dict(schedule=lesson, lecture=lecture, included=included))
        if (
            included
            and lesson["status"] == "completed"
            and datetime.fromisoformat(
                lesson["scheduled_date"] + "T" + lesson["end_time"]
            )
            <= cutoff
        ):
            attendance[lesson["id"]] = {
                r["student_id"]
                for r in pages(
                    "/api/v1/attendance",
                    [
                        ("schedule_id", lesson["id"]),
                        ("week_start_date", lesson["week_start_date"]),
                    ],
                )
                if r["is_present"]
            }
    assert any(row["included"] for row in breakdown), (
        "No tagged lectures in this group schedule. Rebuild and run seed-data."
    )
    for student in students:
        for course in courses:
            selected = [
                row["schedule"]
                for row in breakdown
                if row["included"]
                and row["lecture"]["course_id"] == course["id"]
                and row["schedule"]["scheduled_date"] >= student["enrollment_date"]
            ]
            expected[(student["id"], course["id"])] = (
                2 * len(selected),
                2
                * sum(
                    lesson["scheduled_date"] <= report_date.isoformat()
                    for lesson in selected
                ),
                2
                * sum(
                    student["id"] in attendance.get(lesson["id"], set())
                    for lesson in selected
                ),
            )
    params = [
        ("group_id", group_id),
        ("discipline_tag", args.tag),
        ("as_of_date", report_date.isoformat()),
    ]
    assert get("/api/v1/reports/group-lecture-hours", params, auth=False)[0] == 401
    status, report = get("/api/v1/reports/group-lecture-hours", params)
    assert status == 200, report
    actual = {
        (row["student"]["id"], row["course"]["id"]): (
            row["planned_hours"],
            row["planned_hours_to_date"],
            row["attended_hours"],
        )
        for row in report["items"]
    }
    assert len(actual) == len(report["items"]) and actual == expected, (
        "Hours differ from independent calculation"
    )
    assert report["as_of_date"] == report_date.isoformat()
    assert report["group"] == group
    assert all(
        row["student"] == next(s for s in students if s["id"] == row["student"]["id"])
        and row["course"] == next(c for c in courses if c["id"] == row["course"]["id"])
        for row in report["items"]
    )
    status, empty = get(
        "/api/v1/reports/group-lecture-hours",
        [
            ("group_id", group_id),
            ("discipline_tag", "__несуществующий_тег__"),
            ("as_of_date", report_date.isoformat()),
        ],
    )
    assert status == 200 and len(empty["items"]) == len(expected)
    assert all(
        row["planned_hours"]
        == row["planned_hours_to_date"]
        == row["attended_hours"]
        == 0
        for row in empty["items"]
    )
    assert (
        get(
            "/api/v1/reports/group-lecture-hours",
            [("group_id", group_id), ("discipline_tag", " ")],
        )[0]
        == 422
    )
    out = Path(__file__).resolve().parents[2] / "docs/lab3"
    out.mkdir(parents=True, exist_ok=True)
    filename = (
        f"evidence-{args.as_of_date}.json" if args.as_of_date else "evidence.json"
    )
    (out / filename).write_text(
        json.dumps(
            dict(
                captured_at=now.isoformat(),
                timezone="Europe/Moscow",
                as_of_date=report_date.isoformat(),
                group=group,
                discipline_tag=args.tag,
                breakdown=breakdown,
                independent=[
                    dict(
                        student_id=s,
                        course_id=c,
                        planned_hours=p,
                        planned_hours_to_date=d,
                        attended_hours=a,
                    )
                    for (s, c), (p, d, a) in expected.items()
                ],
                report=report,
                trace=trace,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(
        f"OK: {group['name']} ({group_id}), {len(students)} students, {len(courses)} courses, {len(expected)} rows match"
    )
    for row in report["items"][:6]:
        print(
            f"{row['student']['last_name']} {row['student']['first_name']} | {row['course']['name']} | plan={row['planned_hours']} plan_to_date={row['planned_hours_to_date']} attended={row['attended_hours']}"
        )
    print(f"Saved docs/lab3/{filename} (token excluded)")


if __name__ == "__main__":
    main()
