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


def test_students_are_distributed_without_losing_remainder(monkeypatch):
    monkeypatch.setenv("SEED_STUDENT_COUNT", "1001")
    monkeypatch.setenv("SEED_UNIVERSITY_COUNT", "2")

    config = seeder.Config.from_env()

    assert config.students_per_university(0) == 501
    assert config.students_per_university(1) == 500
    assert sum(config.students_per_university(index) for index in range(2)) == 1001
