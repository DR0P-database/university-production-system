"""Run against an empty dedicated PostgreSQL database via ATTENDANCE_TEST_DATABASE_URL."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

MIGRATIONS = Path(__file__).resolve().parents[1] / "services/attendance-service/migrations/versions"


def migration(name):
    spec = importlib.util.spec_from_file_location(name, MIGRATIONS / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_partition_migration_preserves_data_prunes_and_downgrades():
    url = os.getenv("ATTENDANCE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set ATTENDANCE_TEST_DATABASE_URL to an empty dedicated PostgreSQL database")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                assert await connection.scalar(text("SELECT to_regclass('public.attendance')")) is None

                def run(sync_connection, module, direction):
                    with Operations.context(MigrationContext.configure(sync_connection)):
                        getattr(module, direction)()

                initial = migration("390d366c9dc0_initial.py")
                partitioned = migration("20261031_partition_attendance.py")
                await connection.run_sync(run, initial, "upgrade")
                await connection.execute(text("""
                    INSERT INTO attendance (schedule_id, student_id, week_start_date)
                    VALUES (gen_random_uuid(), gen_random_uuid(), '2026-09-07'),
                           (gen_random_uuid(), gen_random_uuid(), '2026-09-14')
                """))
                before = (await connection.execute(text("SELECT * FROM attendance ORDER BY id"))).all()
                await connection.run_sync(run, partitioned, "upgrade")
                assert await connection.scalar(text("SELECT relkind FROM pg_class WHERE oid = 'attendance'::regclass")) == "p"
                assert (await connection.execute(text("SELECT * FROM attendance ORDER BY id"))).all() == before
                for _ in range(2):
                    await connection.execute(text("SELECT ensure_attendance_partition('2027-01-04')"))
                await connection.execute(text("""
                    INSERT INTO attendance (schedule_id, student_id, week_start_date)
                    VALUES (gen_random_uuid(), gen_random_uuid(), '2027-01-04')
                """))
                assert await connection.scalar(text("SELECT tableoid::regclass::text FROM attendance WHERE week_start_date='2027-01-04'")) == "attendance_w_20270104"
                plan = await connection.scalar(text("EXPLAIN (FORMAT JSON) SELECT * FROM attendance WHERE week_start_date='2026-09-07'"))
                plan_text = json.dumps(plan)
                assert "attendance_w_20260907" in plan_text
                assert "attendance_w_20260914" not in plan_text
                assert "attendance_w_20270104" not in plan_text
                await connection.run_sync(run, partitioned, "downgrade")
                assert await connection.scalar(text("SELECT count(*) FROM attendance")) == 3
                assert await connection.scalar(text("SELECT relkind FROM pg_class WHERE oid = 'attendance'::regclass")) == "r"
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
