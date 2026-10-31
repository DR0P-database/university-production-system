"""Partition attendance by week, preserving existing data transactionally.

Revision ID: 20261031_partition_attendance
Revises: 390d366c9dc0
"""
from alembic import op

revision = "20261031_partition_attendance"
down_revision = "390d366c9dc0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL DDL is transactional: failure restores the original table.
    op.execute("LOCK TABLE public.attendance IN ACCESS EXCLUSIVE MODE")
    op.execute("ALTER TABLE public.attendance RENAME TO attendance_unpartitioned")
    op.execute("""
        CREATE TABLE public.attendance
        (LIKE public.attendance_unpartitioned INCLUDING ALL EXCLUDING INDEXES)
        PARTITION BY RANGE (week_start_date)
    """)
    op.execute("""
        CREATE FUNCTION public.ensure_attendance_partition(week date)
        RETURNS void LANGUAGE plpgsql AS $$
        DECLARE
            partition_name text;
        BEGIN
            IF week IS NULL OR EXTRACT(ISODOW FROM week) <> 1 THEN
                RAISE EXCEPTION 'week must be a Monday' USING ERRCODE = '22023';
            END IF;
            partition_name := 'attendance_w_' || to_char(week, 'YYYYMMDD');
            IF to_regclass('public.' || partition_name) IS NOT NULL THEN
                RETURN;
            END IF;
            -- Serialize partition creation across all API workers.
            PERFORM pg_advisory_xact_lock(731031, 1);
            IF to_regclass('public.' || partition_name) IS NULL THEN
                EXECUTE format(
                    'CREATE TABLE public.%I PARTITION OF public.attendance '
                    'FOR VALUES FROM (%L) TO (%L)',
                    partition_name, week, week + 7
                );
            END IF;
        END;
        $$
    """)
    op.execute("""
        DO $$
        DECLARE week date;
        BEGIN
            FOR week IN
                SELECT DISTINCT week_start_date FROM public.attendance_unpartitioned
                UNION
                SELECT date_trunc('week', CURRENT_DATE)::date
            LOOP
                PERFORM public.ensure_attendance_partition(week);
            END LOOP;
        END;
        $$
    """)
    op.execute("INSERT INTO public.attendance SELECT * FROM public.attendance_unpartitioned")
    op.execute("DROP TABLE public.attendance_unpartitioned")
    restore_indexes()


def downgrade() -> None:
    op.execute("LOCK TABLE public.attendance IN ACCESS EXCLUSIVE MODE")
    op.execute("ALTER TABLE public.attendance RENAME TO attendance_partitioned")
    op.execute("""
        CREATE TABLE public.attendance
        (LIKE public.attendance_partitioned INCLUDING ALL EXCLUDING INDEXES)
    """)
    op.execute("INSERT INTO public.attendance SELECT * FROM public.attendance_partitioned")
    op.execute("DROP TABLE public.attendance_partitioned")
    restore_indexes()
    op.execute("DROP FUNCTION public.ensure_attendance_partition(date)")


def restore_indexes() -> None:
    op.execute("ALTER TABLE public.attendance ADD CONSTRAINT pk_attendance PRIMARY KEY (id, week_start_date)")
    op.execute("""
        ALTER TABLE public.attendance
        ADD CONSTRAINT uq_attendance_schedule_student_week
        UNIQUE (schedule_id, student_id, week_start_date)
    """)
    for column in ("schedule_id", "student_id", "week_start_date"):
        op.create_index(f"ix_attendance_{column}", "attendance", [column], schema="public")
