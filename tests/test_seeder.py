from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SEEDER_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "data-seeder" / "seeder.py"
)
SPEC = importlib.util.spec_from_file_location("data_seeder", SEEDER_PATH)
assert SPEC is not None and SPEC.loader is not None
seeder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = seeder
SPEC.loader.exec_module(seeder)


def test_default_dataset_dimensions(monkeypatch):
    for name in (
        "SEED_STUDENT_COUNT",
        "SEED_UNIVERSITY_COUNT",
        "SEED_GROUP_SIZE",
        "SEED_WEEK_COUNT",
        "SEED_START_DATE",
        "SEED_CONCURRENCY",
    ):
        monkeypatch.delenv(name, raising=False)

    config = seeder.Config.from_env()

    assert config.students_per_university(0) == 500
    assert config.students_per_university(1) == 500
    assert config.expected_group_count == 34
    assert config.expected_schedule_count == 408
    assert config.expected_attendance_count == 4000
    assert config.expected_academic_graph_node_count == 1464
    assert config.expected_academic_graph_relationship_count == 1496


def test_students_are_distributed_without_losing_remainder(monkeypatch):
    monkeypatch.setenv("SEED_STUDENT_COUNT", "1001")
    monkeypatch.setenv("SEED_UNIVERSITY_COUNT", "2")

    config = seeder.Config.from_env()

    assert config.students_per_university(0) == 501
    assert config.students_per_university(1) == 500
    assert sum(config.students_per_university(index) for index in range(2)) == 1001


def test_graph_verification_includes_existing_non_seed_structure():
    stats = seeder.expected_academic_graph_stats(
        universities=[{}, {}, {}],
        institutes=[{}, {}, {}, {}],
        departments=[{} for _ in range(8)],
        specialties=[{} for _ in range(8)],
        groups=[{} for _ in range(34)],
        students=[{} for _ in range(1000)],
        schedules=[{} for _ in range(408)],
        department_specialty_count=8,
    )

    assert stats == {
        "universities": 3,
        "institutes": 4,
        "departments": 8,
        "specialties": 8,
        "groups": 34,
        "students": 1000,
        "schedules": 408,
        "relationships": 1496,
    }


def test_generated_lecture_materials_are_deterministic_and_demo_ready():
    lecture = {
        "id": "00000000-0000-0000-0000-000000000101",
        "title": "[SEED] Информационные системы, занятие 2",
        "lecture_type": "lecture",
        "order_number": 2,
        "duration_minutes": 90,
    }

    first = seeder.lecture_material_payloads(lecture)
    second = seeder.lecture_material_payloads(lecture)

    assert first == second
    assert [material["content_type"] for material in first] == ["text", "exercise"]
    assert len(first[0]["content_text"]) > 2000
    assert len(first[1]["content_text"]) > 1500
    assert "нормализация" in first[0]["content_text"]
    assert first[0]["metadata_json"]["schema_version"] == 2
    assert first[0]["metadata_json"]["format"] == "markdown"
    assert len(first[0]["metadata_json"]["keywords"]) == 4


async def test_existing_seed_material_is_updated_instead_of_duplicated():
    payload = {
        "lecture_id": "00000000-0000-0000-0000-000000000101",
        "content_type": "text",
        "title": "Новый конспект",
        "content_text": "Новый содержательный текст",
        "file_url": None,
        "metadata_json": {"source": "data-seeder", "material_number": 1},
    }
    existing = {
        **payload,
        "id": "00000000-0000-0000-0000-000000000201",
        "title": "Старый материал",
        "content_text": "Короткий текст",
    }

    class FakeApi:
        def __init__(self):
            self.calls = []

        async def request(self, method, service, path, *, json=None):
            self.calls.append((method, service, path, json))
            return {**payload, "id": existing["id"]}

    api = FakeApi()
    cache = {1: existing}

    result = await seeder.sync_material(api, cache, 1, payload)

    assert result["content_text"] == payload["content_text"]
    assert len(api.calls) == 1
    assert api.calls[0][:3] == (
        "PATCH",
        "academic",
        f"/api/v1/academic/materials/{existing['id']}",
    )


async def test_seed_lecture_tags_update_existing_without_losing_fields(load_app):
    lecture = dict(
        id="lecture",
        course_id="course",
        title="Existing title",
        annotation="Existing annotation",
        lecture_type="lecture",
        order_number=1,
        duration_minutes=90,
        requirements="Projector",
        tags=["custom"],
    )

    class FakeApi:
        def __init__(self):
            self.calls = []

        async def request(self, method, service, path, *, json):
            self.calls.append((method, service, path, json))
            return {**lecture, **json}

    api = FakeApi()
    updated = await seeder.sync_lecture_tags(api, lecture)
    assert updated["tags"] == ["custom", seeder.SPECIAL_DISCIPLINE_TAG]
    assert updated["title"] == lecture["title"]
    assert updated["requirements"] == "Projector"
    assert api.calls[0][:3] == (
        "PATCH",
        "academic",
        "/api/v1/academic/lectures/lecture",
    )
    academic = load_app("services/academic-service")
    operations = academic.app.openapi()["paths"]["/api/v1/academic/lectures/{item_id}"]
    assert api.calls[0][0].lower() in operations
    assert api.calls[0][3] == {"tags": ["custom", seeder.SPECIAL_DISCIPLINE_TAG]}
    assert await seeder.sync_lecture_tags(api, updated) == updated
    assert len(api.calls) == 1
    assert seeder.lecture_tags(2) == [seeder.SPECIAL_DISCIPLINE_TAG]
    assert seeder.SPECIAL_DISCIPLINE_TAG not in seeder.lecture_tags(3)
    assert seeder.SPECIAL_DISCIPLINE_TAG not in seeder.lecture_tags(4)
