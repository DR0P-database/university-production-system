from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from sqlalchemy import text

from app.db import engine


async def ensure_partitions(weeks: Iterable[date]) -> None:
    """Create all batch partitions before the data transaction takes table locks.

    A separate short transaction avoids lock upgrades against earlier inserts in
    the same batch. The database function serializes DDL across API workers.
    """
    unique_weeks = sorted(set(weeks))
    if not unique_weeks:
        return
    async with engine.begin() as connection:
        for week in unique_weeks:
            await connection.execute(
                text("SELECT public.ensure_attendance_partition(:week)"),
                {"week": week},
            )
