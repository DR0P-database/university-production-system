from datetime import datetime
from uuid import UUID

import httpx
import pytest


@pytest.mark.asyncio
async def test_group_hours(load_app, monkeypatch):
    module = load_app("services/group-hours-report-service")
    gid = str(UUID(int=1))

    def handler(request):
        path = request.url.path
        if path.endswith("/groups/" + gid):
            return httpx.Response(
                200, json=dict(id=gid, specialty_id=gid, name="Group")
            )
        if path.endswith("/students"):
            rows = [
                dict(
                    id="s", first_name="A", last_name="B", enrollment_date="2020-01-01"
                )
            ]
        elif path.endswith("/courses"):
            rows = [dict(id="c", name="Course"), dict(id="empty", name="Empty")]
        elif path.endswith("/lectures"):
            rows = [
                dict(id="l", course_id="c", lecture_type="lecture", tags=["special"]),
                dict(
                    id="other",
                    course_id="c",
                    lecture_type="lecture",
                    tags=["special-other"],
                ),
            ]
        elif path.endswith("/schedule"):
            rows = [
                dict(
                    id=key,
                    lecture_id=lecture,
                    status=status,
                    scheduled_date=day,
                    end_time="12:00:00",
                )
                for key, lecture, status, day in [
                    ("past", "l", "completed", "2020-01-06"),
                    ("future", "l", "scheduled", "2099-01-01"),
                    ("cancelled", "l", "cancelled", "2020-01-06"),
                    ("untagged", "other", "completed", "2020-01-06"),
                    ("before", "l", "completed", "2019-01-01"),
                ]
            ]
        else:
            selected = set(request.url.params.get_list("schedule_ids"))
            assert selected <= {"past", "before"}
            rows = (
                [
                    dict(
                        schedule_id="past",
                        student_id="s",
                        week_start_date="2020-01-06",
                        is_present=True,
                    )
                ]
                * 2
                if "past" in selected
                else []
            )
        return httpx.Response(200, json=dict(items=rows, total=len(rows)))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=module.app), base_url="http://test"
    ) as client:
        module.app.state.client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )
        response = await client.get(
            "/api/v1/reports/group-lecture-hours",
            params=dict(group_id=gid, discipline_tag="special"),
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["group"]["name"] == "Group"
        assert [(x["planned_hours"], x["attended_hours"]) for x in result["items"]] == [
            (4, 2),
            (0, 0),
        ]
        assert result["items"][0]["planned_hours_to_date"] == 2
        assert result["timezone"] == "Europe/Moscow"
        for day, plan_to_date, attended in [
            ("2018-01-01", 0, 0),
            ("2020-01-05", 0, 0),
            ("2020-01-06", 2, 2),
            ("2099-01-01", 4, 2),
        ]:
            dated = await client.get(
                "/api/v1/reports/group-lecture-hours",
                params=dict(group_id=gid, discipline_tag="special", as_of_date=day),
            )
            assert dated.status_code == 200, dated.text
            assert dated.json()["as_of_date"] == day
            item = dated.json()["items"][0]
            assert (
                item["planned_hours"],
                item["planned_hours_to_date"],
                item["attended_hours"],
            ) == (4, plan_to_date, attended)

        class Morning(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2020, 1, 6, 11, tzinfo=tz)

        with monkeypatch.context() as patch:
            patch.setattr(module, "datetime", Morning)
            morning = await client.get(
                "/api/v1/reports/group-lecture-hours",
                params=dict(group_id=gid, discipline_tag="special"),
            )
            assert morning.json()["as_of_date"] == "2020-01-06"
            assert morning.json()["items"][0]["planned_hours_to_date"] == 2
            assert morning.json()["items"][0]["attended_hours"] == 0
        assert (
            await client.get(
                "/api/v1/reports/group-lecture-hours",
                params=dict(
                    group_id=gid, discipline_tag="special", as_of_date="not-a-date"
                ),
            )
        ).status_code == 422
        assert (
            await client.get(
                "/api/v1/reports/group-lecture-hours",
                params=dict(group_id=gid, discipline_tag=" "),
            )
        ).status_code == 422
        module.app.state.client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(404))
        )
        assert (
            await client.get(
                "/api/v1/reports/group-lecture-hours",
                params=dict(group_id=gid, discipline_tag="special"),
            )
        ).status_code == 404


def test_lab3_openapi_merge(load_app):
    report = load_app("services/group-hours-report-service").app.openapi()
    gateway = load_app("gateway")
    merged = gateway.merge_openapi_schemas(gateway.app.routes, {"reports_lab3": report})
    operation = merged["paths"]["/api/v1/reports/group-lecture-hours"]["get"]
    assert operation["tags"] == ["Лабораторная 3"]
    assert operation["security"] == [{"BearerAuth": []}]


@pytest.mark.asyncio
async def test_gateway_routes_hours_to_separate_service(load_app):
    from starlette.requests import Request

    gateway = load_app("gateway")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"items": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        gateway.app.state.client = upstream
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/v1/reports/group-lecture-hours",
                "query_string": b"discipline_tag=special",
                "headers": [],
                "app": gateway.app,
            }
        )

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        request = Request(request.scope, receive=receive)
        response = await gateway.proxy("reports", request, "group-lecture-hours")
        assert response.status_code == 200
        assert str(calls[0].url).startswith(
            gateway.GROUP_HOURS_REPORT_SERVICE_URL + "/api/v1/reports/group-lecture-hours?"
        )
        assert calls[0].url.params["discipline_tag"] == "special"
