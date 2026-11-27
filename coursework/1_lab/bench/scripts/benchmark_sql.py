#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""benchmark_sql.py — воспроизводимый бенчмарк baseline.sql vs optimized.sql (ЛР1).

Режимы:
  * CLI по умолчанию: поднимает ОТДЕЛЬНЫЙ ephemeral docker postgres:16-alpine
    (контейнер lab1-sql-benchmark-<unique>, случайный POSTGRES_PASSWORD — не печатается,
    случайный порт на 127.0.0.1), прогоняет бенчмарк, удаляет контейнер.
    Существующий local_postgres / university_system НЕ трогается вообще.
  * Портативный API (см. API_PORTABILITY.md): run_benchmarks(admin_dsn, output_dir, ...)
    работает через psycopg с любым выделенным PostgreSQL, без docker/shell внутри.
    Имена БД уникальны по run_id (lab1_benchmark_<run_id>_*), чистятся только БД,
    созданные этим конкретным запуском.
  * --preflight: быстрая проверка корректности (fixture + 100 студентов, 5 повторов),
    ненулевой код выхода при провале. Полный прогон — без preflight.

Методика: 1-2 прогревочных прогона, >=5 измеряемых повторов, чередование
baseline/optimized; на каждом прогоне — EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
(серверное Execution Time) и отдельное клиентское выполнение (psycopg,
REPEATABLE READ READ ONLY). Буферы берутся ТОЛЬКО из корневого узла Plan
(EXPLAIN агрегирует их по поддереву — сумма по узлам давала бы двойной счёт).
Партиции attendance: planned (EXPLAIN без ANALYZE) vs executed (Actual Loops > 0),
плюс Subplans Removed. Кейсы: полные 16 недель (2026-09-07..2026-12-27),
match_mode='literal', missing_policy='exclude' (успешный 200-отчёт: рейтинг только
по complete-студентам, ranking_complete=false при наличии unknown; strict-409
успешным запросом не считается); таймируется только SQL, без времени API/ES.
Таймируемые прогоны используют только валидные material IDs, некорректные
находки (junk) проверяются отдельным нетаймируемым прогоном. Все данные
синтетические (демо), сгенерированы с фиксированным seed; исходные 104 студента
отчёта ПР3 не используются.

Контракт SQL — четырёхисточниковый (baseline.sql и optimized.sql эквивалентны):
params + materials (ES) + graph_schedule/graph_members (Neo4j). Графовый payload
для каждого кейса строится build_graph_payload из той же fixture-PG — это
СИНТЕТИЧЕСКИЙ вход графового контракта (семантика Cypher адаптера), а НЕ
измерение живого Neo4j. Негативные прогоны (пустой/подменённый граф, junk-
материалы) проверяют, что расхождения выявляются, а не игнорируются.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import secrets
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import IsolationLevel
from psycopg.conninfo import make_conninfo

WORKDIR = Path(__file__).resolve().parent.parent
SQL_BASELINE = WORKDIR / "baseline.sql"
SQL_OPTIMIZED = WORKDIR / "optimized.sql"
SQL_SCHEMA = WORKDIR / "sql" / "schema_from_pr3.sql"      # дословный DDL отчёта ПР3
SQL_FIXTURE = WORKDIR / "sql" / "fixture.sql"             # контрольный набор Codex

DB_NAME_RE = re.compile(r"^lab1_benchmark_[a-z0-9_]+$")   # whitelist имён БД (API_PORTABILITY.md)
IMAGE = "postgres:16-alpine"
SEED_DEFAULT = 0.42
WARMUP_DEFAULT = 2
REPS_DEFAULT = 6   # >= 5
SIZES_DEFAULT = (100, 1000, 10000)
SIZES_MAX = 6
SIZE_MIN, SIZE_MAX = 25, 100000          # n_students кратен 25 (generate_dataset)
REPS_MIN, REPS_MAX = 5, 30
WARMUP_MIN, WARMUP_MAX = 1, 5
TERM_FULL_END = "2026-12-27"             # 16-я полная неделя: 2026-09-07 + 15*7 + 6

# ---------------------------------------------------------------- SQL тексты

def load_sql_texts() -> dict[str, str]:
    return {
        "baseline": SQL_BASELINE.read_text(encoding="utf-8"),
        "optimized": SQL_OPTIMIZED.read_text(encoding="utf-8"),
        "schema": SQL_SCHEMA.read_text(encoding="utf-8"),
        "fixture": SQL_FIXTURE.read_text(encoding="utf-8"),
    }


def sql_sha256(sqls: dict[str, str]) -> dict[str, str]:
    return {k: hashlib.sha256(v.encode("utf-8")).hexdigest() for k, v in sqls.items()}

# ------------------------------------------------- разбор многострочных файлов

def split_statements(sql: str) -> list[str]:
    """Разбивка SQL-файла на операторы: учитывает $$dollar-quotes$$, 'кавычки', комментарии."""
    stmts, buf = [], []
    i, n = 0, len(sql)
    line_c = block_c = squote = False
    dollar: str | None = None
    while i < n:
        ch = sql[i]
        two = sql[i:i + 2]
        if line_c:
            buf.append(ch)
            if ch == "\n":
                line_c = False
            i += 1
            continue
        if block_c:
            buf.append(ch)
            if two == "*/":
                buf.append(sql[i + 1])
                i += 2
                block_c = False
                continue
            i += 1
            continue
        if dollar is not None:
            if sql.startswith(dollar, i):
                buf.append(dollar)
                i += len(dollar)
                dollar = None
                continue
            buf.append(ch)
            i += 1
            continue
        if two == "--":
            buf.append(two)
            i += 2
            line_c = True
            continue
        if two == "/*":
            buf.append(two)
            i += 2
            block_c = True
            continue
        if ch == "'":
            buf.append(ch)
            i += 1
            j = i
            while j < n:
                buf.append(sql[j])
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        buf.append("'")
                        j += 2
                        continue
                    break
                j += 1
            i = j + 1
            continue
        if ch == "$":
            m = re.match(r"\$[A-Za-z_]*\$", sql[i:])
            if m:
                dollar = m.group(0)
                buf.append(dollar)
                i += len(dollar)
                continue
        if ch == ";":
            stmts.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return [s for s in stmts if s]

# ------------------------------------------------------------------- docker

def sh(args: list[str]) -> str:
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {' '.join(args[:3])}...: {r.stderr.strip()[:300]}")
    return r.stdout

def start_pg_container() -> tuple[str, str]:
    """Отдельный ephemeral postgres:16-alpine. Возвращает (имя контейнера, admin DSN)."""
    name = "lab1-sql-benchmark-" + secrets.token_hex(4)
    password = secrets.token_urlsafe(24)  # случайный пароль ТОЛЬКО для своего контейнера; не печатается
    subprocess.run(
        ["docker", "run", "-d", "--name", name,
         "-e", f"POSTGRES_PASSWORD={password}",
         "-p", "127.0.0.1::5432", IMAGE],
        check=True, capture_output=True, text=True)
    out = sh(["docker", "port", name, "5432/tcp"]).strip().splitlines()
    port = int(out[0].rsplit(":", 1)[1])
    dsn = f"host=127.0.0.1 port={port} user=postgres password={password} dbname=postgres connect_timeout=5"
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=5) as c:
                c.execute("SELECT 1").fetchone()
            return name, dsn
        except psycopg.Error:
            time.sleep(1)
    raise RuntimeError("postgres container not ready in 120s")

def remove_container(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)

def docker_context(container: str) -> dict:
    ver = sh(["docker", "version", "--format", "{{.Server.Version}}"]).strip()
    ncpu = sh(["docker", "exec", container, "nproc"]).strip()
    insp = json.loads(sh(["docker", "inspect", container]))[0]["HostConfig"]
    return {"image": IMAGE, "container": container, "docker_server_version": ver,
            "container_cpus": ncpu, "container_nano_cpus": insp.get("NanoCpus", 0),
            "container_memory_limit_bytes": insp.get("Memory", 0)}

def host_context() -> dict:
    mem = None
    try:
        mem = int(sh(["sysctl", "-n", "hw.memsize"]).strip())
    except Exception:
        pass
    return {"platform": platform.platform(), "machine": platform.machine(),
            "cpu_count": os.cpu_count(), "memory_bytes": mem,
            "python": sys.version.split()[0]}

# ------------------------------------------------------------- база/загрузка

def create_database(admin: psycopg.Connection, dbname: str) -> None:
    if not DB_NAME_RE.match(dbname):
        raise ValueError(f"dbname не проходит whitelist: {dbname}")
    admin.execute(f'CREATE DATABASE "{dbname}"')

def drop_database(admin: psycopg.Connection, dbname: str) -> None:
    if not DB_NAME_RE.match(dbname):
        raise ValueError(f"dbname не проходит whitelist: {dbname}")
    admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')

def load_sql_file(conn: psycopg.Connection, sql_text: str) -> None:
    """Загрузка SQL-файла (schema/fixture). Сначала пробуем одним PQexec-батчем,
    при отказе — пооператорно через split_statements (учитывает $$...$$)."""
    try:
        conn.execute(sql_text)
        return
    except psycopg.Error:
        pass
    for stmt in split_statements(sql_text):
        conn.execute(stmt)

# --------------------------------------------------- генерация демо-данных

def generate_dataset(conn: psycopg.Connection, n_students: int, seed: float) -> None:
    """Синтетический набор (НЕ данные отчёта ПР3): n_students кратен 25, групп по 25.
    Спец-случаи в каждой группе (позиция = (student_id-1)%25):
      0 — все отметки false (нулевая посещаемость, не должна теряться);
      1 — ни одной отметки (все unknown, incomplete);
      2 — зачислен 2026-10-05 (середина семестра);
      3 — зачислен 2026-11-02;
    прочие — обычный микс ~93% true / ~4% false / ~3% пропусков.
    Расписание: 16 недель, у каждой группы 4 лекционных слота (темы 1..4, ротация),
    1 шумовая лекция (темы 5..8), практика (тема 9) и лаба (тема 11).
    Узкий термин = темы 1..2, широкий = 1..4. 2 материала у каждой лекции (дедуп).
    Есть cancelled/scheduled занятия и отметки на cancelled (не должны учитываться).
    """
    assert n_students % 25 == 0 and n_students >= 100
    groups = n_students // 25
    conn.execute("SELECT setseed(%(s)s)", {"s": seed})
    conn.execute("""
      INSERT INTO practice03.universities(code,name,short_name)
      VALUES ('DEMO','Демонстрационный университет для бенчмарка ЛР1','ДемоУ')""")
    conn.execute("""
      INSERT INTO practice03.institutes(university_id,code,name)
      VALUES (1,'DEMO-I','Демонстрационный институт')""")
    conn.execute("""
      INSERT INTO practice03.departments(institute_id,code,name) VALUES
        (1,'DEMO-D1','Демо кафедра 1'),(1,'DEMO-D2','Демо кафедра 2'),
        (1,'DEMO-D3','Демо кафедра 3'),(1,'DEMO-D4','Демо кафедра 4')""")
    conn.execute("""
      INSERT INTO practice03.specialties(code,name,degree_level,duration_years) VALUES
        ('DEMO-S1','Демо направление 1','bachelor',4),('DEMO-S2','Демо направление 2','bachelor',4),
        ('DEMO-S3','Демо направление 3','master',2),('DEMO-S4','Демо направление 4','bachelor',4)""")
    conn.execute("""
      INSERT INTO practice03.department_specialties(department_id,specialty_id,is_primary)
      VALUES (1,1,true),(2,2,true),(3,3,true),(4,4,true)""")
    conn.execute("""
      INSERT INTO practice03.study_groups(specialty_id,department_id,code,training_profile,enrollment_year,curator_name)
      SELECT sp, sp, 'DEMO-G'||lpad(g::text,4,'0'), 'Демо профиль '||sp, 2026, 'Демо куратор '||g
      FROM generate_series(1,%(groups)s) g, LATERAL (SELECT ((g-1)%%4)+1 AS sp) x""", {"groups": groups})
    conn.execute("""
      INSERT INTO practice03.students(group_id,record_book,last_name,first_name,patronymic,email,phone,enrollment_date,status)
      SELECT ((s-1)/25)+1,
              'RB'||lpad(s::text,6,'0'),
              'Демо-Фамилия'||s, 'Демо-Имя'||s, 'Демо-Отчество'||s,
              'student'||s||'@demo.example', '+7-900-'||lpad(s::text,7,'0'),
              CASE WHEN (s-1)%%25=2 THEN DATE '2026-10-05'
                   WHEN (s-1)%%25=3 THEN DATE '2026-11-02'
                   ELSE DATE '2026-09-01' END,
              'active'
      FROM generate_series(1,%(students)s) s""", {"students": n_students})
    conn.execute("""
      INSERT INTO practice03.courses(specialty_id,department_id,code,title,description,academic_year_start,semester)
      SELECT ((c-1)%4)+1, ((c-1)%4)+1, 'DEMO-C'||c, 'Демо курс '||c,
             'Синтетический курс для бенчмарка ЛР1 (не данные отчёта ПР3)', 2026, 1
      FROM generate_series(1,8) c""")
    conn.execute("""
      INSERT INTO practice03.lectures(course_id,title,lesson_type,order_number,academic_hours,tags)
      SELECT c, 'Демо тема '||c||'.'||t,
             CASE WHEN t<=8 THEN 'lecture' WHEN t<=10 THEN 'practice' ELSE 'lab' END,
             t, 2, ARRAY['демо']
      FROM generate_series(1,8) c, generate_series(1,12) t""")
    conn.execute("""
      INSERT INTO practice03.lecture_materials(lecture_id,title,position,metadata)
      SELECT l, 'Демо материал '||l||'.'||p, p, jsonb_build_object('demo',true,'source','lab1-sql-benchmark')
      FROM generate_series(1,96) l, generate_series(1,2) p""")
    slots = []
    for k, (st, en) in enumerate([("09:00", "10:30"), ("10:30", "12:00"),
                                  ("12:00", "13:30"), ("13:30", "15:00")]):
        slots.append(f"""
      SELECT (c.course_a-1)*12 + ((c.w+{k})%%4)+1, c.group_id, c.ws+{k}, c.ws,
              TIME '{st}', TIME '{en}', 'DEMO-A'||lpad(c.group_id::text,4,'0'),
              'Демо преподаватель '||(((c.w+{k})%%4)+1),
              CASE WHEN (c.group_id*112 + c.w*7 + {k})%%97=13 THEN 'cancelled'
                   WHEN (c.group_id*112 + c.w*7 + {k})%%211=17 THEN 'scheduled'
                   ELSE 'completed' END
      FROM cells c""")
    conn.execute("""
      INSERT INTO practice03.schedule(lecture_id,group_id,scheduled_date,week_start_date,starts_at,ends_at,classroom,teacher_name,status)
      WITH cells AS (
        SELECT g AS group_id, w, DATE '2026-09-07' + w*7 AS ws,
               ((g-1)%%4)*2 + 1 AS course_a, ((g-1)%%4)*2 + 2 AS course_b
        FROM generate_series(1,%(groups)s) g CROSS JOIN generate_series(0,15) w)
      """ + "\n      UNION ALL\n".join(slots) + """
      UNION ALL
      SELECT (c.course_b-1)*12 + ((c.w+c.group_id)%%4)+5, c.group_id, c.ws+2, c.ws,
              TIME '15:00', TIME '16:30', 'DEMO-B'||lpad(c.group_id::text,4,'0'),
              'Демо преподаватель 5',
              CASE WHEN c.w=15 THEN 'scheduled' ELSE 'completed' END
      FROM cells c
      UNION ALL
      SELECT (c.course_a-1)*12 + 9, c.group_id, c.ws+3, c.ws,
              TIME '16:30', TIME '18:00', 'DEMO-P'||lpad(c.group_id::text,4,'0'),
              'Демо преподаватель 9', 'completed'
      FROM cells c
      UNION ALL
      SELECT (c.course_a-1)*12 + 11, c.group_id, c.ws+4, c.ws,
              TIME '18:00', TIME '19:30', 'DEМО-L'||lpad(c.group_id::text,4,'0'),
              'Демо преподаватель 11', 'completed'
      FROM cells c""", {"groups": groups})
    # обычный микс (все позиции, кроме спец. 0 и 1); late-enrollment отсекается сам
    conn.execute("""
      INSERT INTO practice03.attendance(week_start_date,schedule_id,student_id,is_present,recorded_at,marked_by)
      SELECT sc.week_start_date, sc.id, st.id, (random() < 0.93), now(), 'демо-маркер'
      FROM practice03.schedule sc
      JOIN practice03.students st ON st.group_id = sc.group_id
                                 AND st.enrollment_date <= sc.scheduled_date
      WHERE sc.status = 'completed' AND (st.id - 1) % 25 >= 2 AND random() >= 0.03""")
    # позиция 0: всегда отсутствовал (нулевая посещаемость)
    conn.execute("""
      INSERT INTO practice03.attendance(week_start_date,schedule_id,student_id,is_present,recorded_at,marked_by)
      SELECT sc.week_start_date, sc.id, st.id, false, now(), 'демо-маркер'
      FROM practice03.schedule sc
      JOIN practice03.students st ON st.group_id = sc.group_id
                                 AND st.enrollment_date <= sc.scheduled_date
      WHERE sc.status = 'completed' AND (st.id - 1) % 25 = 0""")
    # отметки на cancelled-занятиях: существуют, но НЕ должны попадать в расчёт
    conn.execute("""
      INSERT INTO practice03.attendance(week_start_date,schedule_id,student_id,is_present,recorded_at,marked_by)
      SELECT sc.week_start_date, sc.id, st.id, (random() < 0.5), now(), 'демо-маркер'
      FROM practice03.schedule sc
      JOIN practice03.students st ON st.group_id = sc.group_id
                                 AND st.enrollment_date <= sc.scheduled_date
      WHERE sc.status = 'cancelled' AND random() < 0.3""")

def table_stats(conn: psycopg.Connection) -> dict:
    with conn.cursor() as cur:
        cur.execute("""
          SELECT t, c FROM (VALUES
            ('students',(SELECT count(*) FROM practice03.students)),
            ('study_groups',(SELECT count(*) FROM practice03.study_groups)),
            ('courses',(SELECT count(*) FROM practice03.courses)),
            ('lectures',(SELECT count(*) FROM practice03.lectures)),
            ('lecture_materials',(SELECT count(*) FROM practice03.lecture_materials)),
            ('schedule',(SELECT count(*) FROM practice03.schedule)),
            ('attendance',(SELECT count(*) FROM practice03.attendance))) v(t,c)""")
        counts = {t: c for t, c in cur.fetchall()}
        # pg_total_relation_size(partitioned table) = 0: суммируем только листья
        cur.execute("""SELECT coalesce(sum(pg_total_relation_size(relid))::bigint,0)
                              FROM pg_partition_tree('practice03.attendance')
                              WHERE isleaf""")
        att_sz = int(cur.fetchone()[0])
        cur.execute("SELECT pg_total_relation_size('practice03.schedule')")
        sch_sz = cur.fetchone()[0]
    counts["attendance_total_bytes"] = att_sz
    counts["schedule_total_bytes"] = sch_sz
    return counts

# --------------------------------------------------------------- запросы

def bench_connection(admin_dsn: str, dbname: str) -> psycopg.Connection:
    c = psycopg.connect(make_conninfo(admin_dsn, dbname=dbname),
                        options="-c statement_timeout=180s")
    c.read_only = True
    c.isolation_level = IsolationLevel.REPEATABLE_READ
    return c

def run_report(conn: psycopg.Connection, sql: str, params_obj: dict, materials: list,
               graph: dict | None = None) -> dict:
    graph = graph or {"schedule": [], "members": []}
    with conn.cursor() as cur:
        cur.execute(sql, {"params": json.dumps(params_obj), "materials": json.dumps(materials),
                          "graph_schedule": json.dumps(graph["schedule"]),
                          "graph_members": json.dumps(graph["members"])})
        row = cur.fetchone()
    conn.rollback()
    return row[0]

def timed_report(conn: psycopg.Connection, sql: str, params_obj: dict, materials: list,
                 graph: dict | None = None) -> tuple[float, dict]:
    graph = graph or {"schedule": [], "members": []}
    # Сериализация параметров (json.dumps params/materials/graph_*) — ЗА пределами
    # таймера: client_time — строго psycopg execute+fetch, как заявлено в методике.
    # Сам graph payload строится build_graph_payload в build_cases — тоже вне таймера.
    args = {"params": json.dumps(params_obj), "materials": json.dumps(materials),
            "graph_schedule": json.dumps(graph["schedule"]),
            "graph_members": json.dumps(graph["members"])}
    t0 = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(sql, args)
        row = cur.fetchone()
    dt_ms = (time.perf_counter() - t0) * 1000.0
    conn.rollback()
    return dt_ms, row[0]

def explain_report(conn: psycopg.Connection, sql: str, params_obj: dict, materials: list,
                   analyze: bool = True, graph: dict | None = None) -> list:
    prefix = "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " if analyze \
        else "EXPLAIN (FORMAT JSON) "
    graph = graph or {"schedule": [], "members": []}
    with conn.cursor() as cur:
        cur.execute(prefix + sql,
                    {"params": json.dumps(params_obj), "materials": json.dumps(materials),
                     "graph_schedule": json.dumps(graph["schedule"]),
                     "graph_members": json.dumps(graph["members"])})
        doc = cur.fetchone()[0]
    conn.rollback()
    return doc

def build_graph_payload(conn: psycopg.Connection, materials: list,
                        date_from: str, date_to: str, group_id: int | None = None) -> dict:
    """СИНТЕТИЧЕСКИЙ вход графового контракта: строится из fixture-PG, воспроизводя
    ровно то, что возвращает адаптер Neo4j (Cypher в app/neo4jrepo.py: completed
    lecture найденных тем в периоде + состав участников групп). Это НЕ измерение
    живого Neo4j: таймируется только SQL, получивший графовый набор параметром.
    """
    lecture_ids = sorted({m["lecture_id"] for m in materials})
    with conn.cursor() as cur:
        cur.execute("""
          SELECT sc.id, sc.lecture_id, l.course_id, sc.group_id,
                 sc.scheduled_date, sc.status
          FROM practice03.schedule sc
          JOIN practice03.lectures l ON l.id = sc.lecture_id
          WHERE l.id = ANY(%(lecture_ids)s)
            AND l.lesson_type = 'lecture'
            AND sc.status = 'completed'
            AND sc.scheduled_date BETWEEN %(d1)s AND %(d2)s
            AND (%(group_id)s::int IS NULL OR sc.group_id = %(group_id)s::int)
          ORDER BY sc.id""", {"lecture_ids": lecture_ids, "d1": date_from,
                              "d2": date_to, "group_id": group_id})
        schedule = [{"schedule_id": r[0], "lecture_id": r[1], "course_id": r[2],
                     "group_id": r[3], "scheduled_date": r[4].isoformat(),
                     "status": r[5]} for r in cur.fetchall()]
        group_ids = sorted({row["group_id"] for row in schedule})
        members: list[dict] = []
        if group_ids:
            cur.execute("""
              SELECT st.id, st.group_id, st.record_book
              FROM practice03.students st
              WHERE st.group_id = ANY(%(group_ids)s)
              ORDER BY st.id""", {"group_ids": group_ids})
            members = [{"student_id": r[0], "group_id": r[1], "record_book": r[2]}
                       for r in cur.fetchall()]
    return {"schedule": schedule, "members": members, "group_ids": group_ids}

BUFFER_KEYS = ["Shared Hit Blocks", "Shared Read Blocks", "Shared Dirtied Blocks",
               "Shared Written Blocks", "Local Hit Blocks", "Local Read Blocks",
               "Temp Read Blocks", "Temp Written Blocks"]


def _walk_partitions(node: dict, planned: set, executed: set, removed: list) -> None:
    removed.append(node.get("Subplans Removed") or 0)
    rn = node.get("Relation Name")
    if rn and rn.startswith("attendance_w"):
        planned.add(rn)
        if (node.get("Actual Loops") or 0) > 0:
            executed.add(rn)
    for ch in node.get("Plans", []) or []:
        _walk_partitions(ch, planned, executed, removed)


def plan_summary(doc_analyzed: list, doc_planned: list | None = None) -> dict:
    """Буферы — только корневой Plan (EXPLAIN уже агрегирует по поддереву;
    суммирование по узлам давало бы двойной счёт). Партиции: planned из плана
    без ANALYZE (до отсечения), executed — Actual Loops > 0, плюс Subplans Removed."""
    top = doc_analyzed[0]
    root = top["Plan"]
    planned_a, executed, removed = set(), set(), []
    _walk_partitions(root, planned_a, executed, removed)
    planned = set(planned_a)
    if doc_planned is not None:
        p2, e2, _ = set(), set(), []
        _walk_partitions(doc_planned[0]["Plan"], p2, e2, [])
        planned |= p2
    return {
        "planning_time_ms": top.get("Planning Time"),
        "execution_time_ms": top.get("Execution Time"),
        "buffers": {k: root.get(k) or 0 for k in BUFFER_KEYS},
        "attendance_planned_partitions": sorted(planned),
        "attendance_executed_partitions": sorted(executed),
        "attendance_subplans_removed": sum(removed),
    }

def mmm(xs: list) -> dict:
    return {"min": round(min(xs), 3), "median": round(statistics.median(xs), 3),
            "max": round(max(xs), 3)}

def result_sha(rep: dict) -> str:
    return hashlib.sha256(
        json.dumps(rep, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()

# ---------------------------------------------------------------- кейсы

def build_cases(conn: psycopg.Connection) -> list[dict]:
    """Кейсы на одном наборе данных (валидные materials — только для тайминга):
       week    — одна неделя (2026-09-07..2026-09-13), узкий термин (темы 1..2);
       term16  — ПОЛНЫЕ 16 недель (2026-09-07..2026-12-27: понедельник первой
                 недели .. воскресенье 16-й, партиция 2026-12-21 включена);
       broad16 — 16 недель, широкий термин (темы 1..4) — case селективности термина.
       match_mode='literal' (как допускает API; на SQL не влияет — матчинг терминов
       выполняет Elasticsearch, здесь таймируется только SQL).
       missing_policy='exclude': таймируемый сценарий — УСПЕШНЫЙ отчёт (200):
       рейтинг строится только по complete-студентам (unknown_count=0),
       incomplete перечисляются отдельно (ranking_complete=false, т.к. в полном
       периоде есть unknown); strict-409 сценарий успешным не называется и не
       таймируется. Некорректные находки (junk) в таймируемые прогоны НЕ входят:
       unlinked/missing проверяются отдельным нетаймируемым прогоном."""
    def valid_hits(max_topic: int) -> list[dict]:
        with conn.cursor() as cur:
            cur.execute("""
              SELECT m.id, m.lecture_id, l.course_id
              FROM practice03.lecture_materials m
              JOIN practice03.lectures l ON l.id = m.lecture_id
              WHERE l.lesson_type = 'lecture' AND l.order_number <= %(k)s
              ORDER BY m.id""", {"k": max_topic})
            return [{"id": i, "lecture_id": l, "course_id": c} for i, l, c in cur.fetchall()]

    def junk_hits() -> list[dict]:
        # несуществующий id + материал практики (тема 9) с чужим course_id
        with conn.cursor() as cur:
            cur.execute("""SELECT m.id, m.lecture_id, l.course_id
                           FROM practice03.lecture_materials m
                           JOIN practice03.lectures l ON l.id = m.lecture_id
                           WHERE l.order_number = 9 LIMIT 1""")
            i, l, c = cur.fetchone()
        return [{"id": 999001, "lecture_id": l, "course_id": c},
                {"id": i, "lecture_id": l, "course_id": c + 1000}]

    base_params = {"term": "демо термин", "department_id": None, "group_id": None,
                   "match_mode": "literal", "missing_policy": "exclude", "limit": 10}
    narrow = valid_hits(2)
    broad = valid_hits(4)
    cases = [
        {"name": "week", "date_from": "2026-09-07", "date_to": "2026-09-13",
         "materials": narrow, "junk": junk_hits(),
         "params": {**base_params, "date_from": "2026-09-07", "date_to": "2026-09-13"}},
        {"name": "term16", "date_from": "2026-09-07", "date_to": TERM_FULL_END,
         "materials": narrow,
         "params": {**base_params, "date_from": "2026-09-07", "date_to": TERM_FULL_END}},
        {"name": "broad16", "date_from": "2026-09-07", "date_to": TERM_FULL_END,
         "materials": broad,
         "params": {**base_params, "date_from": "2026-09-07", "date_to": TERM_FULL_END}},
    ]
    # Синтетический вход графового контракта (Neo4j) — по lecture_ids находок кейса,
    # ровно как в реальном пути (адаптер запрашивает граф по всем найденным темам).
    for case in cases:
        case["graph"] = build_graph_payload(conn, case["materials"],
                                            case["date_from"], case["date_to"], None)
    return cases

# ------------------------------------------------------------- прогон кейса

def bench_case(conn: psycopg.Connection, sqls: dict, dataset: str, case: dict,
               out_plans: Path, reps: int, warmup: int) -> dict:
    params = dict(case["params"])
    pf = {**params, "include_trace": False}
    pt = {**params, "include_trace": True}
    graph = case["graph"]  # синтетический вход графового контракта (из fixture-PG)

    # --- корректность/эквивалентность (не таймируется; материалы только валидные) ---
    b_f = run_report(conn, sqls["baseline"], pf, case["materials"], graph)
    o_f = run_report(conn, sqls["optimized"], pf, case["materials"], graph)
    b_t = run_report(conn, sqls["baseline"], pt, case["materials"], graph)
    o_t = run_report(conn, sqls["optimized"], pt, case["materials"], graph)
    equality = {
        "include_trace_false": b_f == o_f,
        "include_trace_true": b_t == o_t,
        "results_stable_across_trace_flag": (b_f["results"] == b_t["results"]
                                             and b_f["eligible_student_count"] == b_t["eligible_student_count"]
                                             and b_f["incomplete_students"] == b_t["incomplete_students"]),
        "sha256_baseline": result_sha(b_f),
        "sha256_optimized": result_sha(o_f),
    }

    # --- junk-корректность: отдельный нетаймируемый прогон (только week-кейс) ---
    junk_res = None
    if case.get("junk"):
        mats_j = case["materials"] + case["junk"]
        # Графовый payload в реальном пути строится по lecture_ids ВСЕХ находок ES
        # (включая junk); junk-лекция — практика, в график не попадает.
        graph_j = build_graph_payload(conn, mats_j, params["date_from"],
                                      params["date_to"], params.get("group_id"))
        bj = run_report(conn, sqls["baseline"], {**pf}, mats_j, graph_j)
        oj = run_report(conn, sqls["optimized"], {**pf}, mats_j, graph_j)
        junk_ids = sorted(h["id"] for h in case["junk"])
        # Негативная корректность: подменённый граф (выкинули одно занятие) —
        # SQL обязан это выявить (graph_missing_schedules), а не молча посчитать.
        graph_bad = {"schedule": graph_j["schedule"][:-1], "members": graph_j["members"]}
        ob = run_report(conn, sqls["optimized"], {**pf}, mats_j, graph_bad)
        junk_res = {
            "junk_ids": junk_ids,
            "unlinked_materials_equals_junk": (bj["unlinked_materials"] == junk_ids),
            "matched_unchanged": (bj["matched_lecture_ids"] == b_f["matched_lecture_ids"]),
            "baseline_equals_optimized": bj == oj,
            "tampered_graph_detected": (len(ob["graph_missing_schedules"]) == 1
                                        and not ob["graph_extra_schedules"]
                                        and not ob["graph_wrong_schedules"]),
        }

    # --- прогрев ---
    for i in range(warmup):
        order = ["baseline", "optimized"] if i % 2 == 0 else ["optimized", "baseline"]
        for name in order:
            run_report(conn, sqls[name], pf, case["materials"], graph)

    # --- planned-партиции: план без выполнения (до pruning) ---
    planned_docs = {name: explain_report(conn, sqls[name], pf, case["materials"],
                                         analyze=False, graph=graph)
                    for name in ("baseline", "optimized")}

    # --- измерения: чередование, EXPLAIN + клиентское получение ---
    S = {name: {"exec_ms": [], "client_ms": [], "planning_ms": [],
                "Shared Hit Blocks": [], "Shared Read Blocks": [],
                "Temp Read Blocks": [], "Temp Written Blocks": []}
         for name in ("baseline", "optimized")}
    plans: dict[str, list] = {}
    parts: dict[str, dict] = {name: {"planned": set(), "executed": set(),
                                     "removed": 0} for name in ("baseline", "optimized")}
    for rep in range(reps):
        order = ["baseline", "optimized"] if rep % 2 == 0 else ["optimized", "baseline"]
        for name in order:
            doc = explain_report(conn, sqls[name], pf, case["materials"], graph=graph)
            ps = plan_summary(doc, planned_docs[name])
            S[name]["exec_ms"].append(ps["execution_time_ms"])
            S[name]["planning_ms"].append(ps["planning_time_ms"])
            for k in ("Shared Hit Blocks", "Shared Read Blocks", "Temp Read Blocks", "Temp Written Blocks"):
                S[name][k].append(ps["buffers"][k])
            parts[name]["planned"] |= set(ps["attendance_planned_partitions"])
            parts[name]["executed"] |= set(ps["attendance_executed_partitions"])
            parts[name]["removed"] = max(parts[name]["removed"],
                                         ps["attendance_subplans_removed"])
            if rep == 0:
                plans[name] = doc
            dt_ms, _ = timed_report(conn, sqls[name], pf, case["materials"], graph)
            S[name]["client_ms"].append(dt_ms)

    for name, doc in plans.items():
        (out_plans / f"{dataset}__{case['name']}__{name}.json").write_text(
            json.dumps({"dataset": dataset, "case": case["name"], "query": name,
                        "rep": 0, "params": pf, "explain": doc,
                        "planned_partitions": sorted(
                            plan_summary(planned_docs[name])["attendance_planned_partitions"])},
                       ensure_ascii=False, indent=1, default=_json_default),
            encoding="utf-8")

    def qstats(name: str) -> dict:
        return {
            "exec_time_ms": mmm(S[name]["exec_ms"]),
            "client_time_ms": mmm(S[name]["client_ms"]),
            "planning_time_ms": mmm(S[name]["planning_ms"]),
            # корень Plan: агрегат по всему поддереву, без двойного суммирования узлов
            "buffers_root_median": {k: round(statistics.median(S[name][k])) for k in
                                    ("Shared Hit Blocks", "Shared Read Blocks",
                                     "Temp Read Blocks", "Temp Written Blocks")},
            "attendance_planned_partitions": sorted(parts[name]["planned"]),
            "attendance_executed_partitions": sorted(parts[name]["executed"]),
            "attendance_planned_count": len(parts[name]["planned"]),
            "attendance_executed_count": len(parts[name]["executed"]),
            "attendance_subplans_removed": parts[name]["removed"],
        }

    b_med = statistics.median(S["baseline"]["exec_ms"])
    o_med = statistics.median(S["optimized"]["exec_ms"])
    return {
        "dataset": dataset, "case": case["name"],
        "params": {"date_from": params["date_from"], "date_to": params["date_to"],
                   "limit": params["limit"], "include_trace": False,
                   "match_mode": params["match_mode"],
                   "missing_policy": params.get("missing_policy", "exclude"),
                   "department_id": params["department_id"], "group_id": params["group_id"]},
        "materials": {"total": len(case["materials"]), "valid": len(case["materials"]),
                      "unlinked_junk_in_timed_run": 0,
                      "matched_lecture_ids": b_f["matched_lecture_ids"]},
        "equality": equality,
        "junk_correctness": junk_res,
        "baseline": qstats("baseline"),
        "optimized": qstats("optimized"),
        "speedup_exec_median": round(b_med / o_med, 3) if o_med else None,
        "speedup_client_median": round(
            statistics.median(S["baseline"]["client_ms"]) /
            statistics.median(S["optimized"]["client_ms"]), 3),
        "sanity": {
            "selected_schedule_count": b_f["selected_schedule_count"],
            "eligible_student_count": b_f["eligible_student_count"],
            "complete_student_count": b_f["complete_student_count"],
            "incomplete_students_count": len(b_f["incomplete_students"]),
            # успешный 200-отчёт c exclude: рейтинг только по complete-студентам
            "ranking_complete": len(b_f["incomplete_students"]) == 0,
            "top_student_ids": [r["student_pg"]["id"] for r in b_f["results"]],
        },
    }

# --------------------------------------------------- контрольный fixture

def fixture_check(conn: psycopg.Connection, sqls: dict) -> dict:
    """Контрольный набор из sql/fixture.sql. Ожидания (проверено Codex):
       matched_lecture_ids=[1], eligible=13, complete=12, top ids 1..10,
       student1=0%, 2..10=50%, student13: expected=2, present=1, unknown=1,
       selected_schedule_count=2 (две completed лекции группы 1 в периоде)."""
    base = {"term": "целостность", "date_from": "2026-09-07", "date_to": "2026-09-20",
            "department_id": None, "group_id": None, "match_mode": "literal",
            "missing_policy": "exclude", "limit": 10}
    mats = [{"id": 1, "lecture_id": 1, "course_id": 1}, {"id": 2, "lecture_id": 1, "course_id": 1}]

    graph = build_graph_payload(conn, mats, base["date_from"], base["date_to"], None)

    def extract(rep: dict) -> dict:
        return {
            "matched_lecture_ids": rep["matched_lecture_ids"],
            "unlinked_materials": rep["unlinked_materials"],
            "selected_schedule_count": rep["selected_schedule_count"],
            "eligible_student_count": rep["eligible_student_count"],
            "complete_student_count": rep["complete_student_count"],
            "top_student_ids": [r["student_pg"]["id"] for r in rep["results"]],
            "top_percentages": [float(r["attendance_percentage"]) for r in rep["results"]],
            "incomplete_students": rep["incomplete_students"],
            "graph_consistent": all(not rep[f] for f in (
                "graph_missing_schedules", "graph_extra_schedules", "graph_wrong_schedules",
                "graph_missing_members", "graph_extra_members", "graph_wrong_members")),
        }

    out: dict = {}
    for trace in (False, True):
        p = {**base, "include_trace": trace}
        b = extract(run_report(conn, sqls["baseline"], p, mats, graph))
        o = extract(run_report(conn, sqls["optimized"], p, mats, graph))
        out[f"include_trace_{str(trace).lower()}"] = {
            "baseline": b, "optimized": o, "baseline_equals_optimized": b == o}

    b = out["include_trace_false"]["baseline"]
    expected = {
        "matched_lecture_ids": [1], "unlinked_materials": [],
        "eligible_student_count": 13, "complete_student_count": 12,
        "top_student_ids": list(range(1, 11)),
        "top_percentages": [0.0] + [50.0] * 9,
        "student13": {"student_id": 13, "expected_count": 2, "present_count": 1, "unknown_count": 1},
        "selected_schedule_count": 2,
    }
    checks = {
        "matched_lecture_ids": b["matched_lecture_ids"] == expected["matched_lecture_ids"],
        "unlinked_materials": b["unlinked_materials"] == expected["unlinked_materials"],
        "selected_schedule_count_2": b["selected_schedule_count"] == 2,
        "eligible_13": b["eligible_student_count"] == 13,
        "complete_12": b["complete_student_count"] == 12,
        "top_ids_1_10": b["top_student_ids"] == expected["top_student_ids"],
        "percentages_0_then_50": b["top_percentages"] == expected["top_percentages"],
        "student13_unknown_1_of_2": any(
            s["student_id"] == 13 and s["expected_count"] == 2
            and s["present_count"] == 1 and s["unknown_count"] == 1
            for s in b["incomplete_students"]),
    }
    # второй прогон с «мусорной» находкой: unlinked_materials=[999], остальное то же
    mats_junk = mats + [{"id": 999, "lecture_id": 1, "course_id": 1}]
    bj = run_report(conn, sqls["baseline"], {**base, "include_trace": False}, mats_junk, graph)
    oj = run_report(conn, sqls["optimized"], {**base, "include_trace": False}, mats_junk, graph)
    checks["junk_unlinked_999"] = (bj["unlinked_materials"] == [999]
                                   and oj["unlinked_materials"] == [999]
                                   and bj["matched_lecture_ids"] == [1]
                                   and bj == oj)
    # негативная корректность графа: пустой, с лишним занятием и без участника —
    # SQL обязан вернуть расхождения, а не «молча» посчитать по PG.
    graph_empty = {"schedule": [], "members": []}
    be = run_report(conn, sqls["baseline"], {**base, "include_trace": False}, mats, graph_empty)
    oe = run_report(conn, sqls["optimized"], {**base, "include_trace": False}, mats, graph_empty)
    checks["empty_graph_missing_detected"] = (
        sorted(be["graph_missing_schedules"]) == sorted(g["schedule_id"] for g in graph["schedule"])
        and sorted(oe["graph_missing_schedules"]) == sorted(g["schedule_id"] for g in graph["schedule"])
        and be["selected_schedule_count"] == 0 and oe["selected_schedule_count"] == 0)
    graph_extra = {"schedule": graph["schedule"] + [{"schedule_id": 999999,
                                                     "lecture_id": 1, "course_id": 1,
                                                     "group_id": 1,
                                                     "scheduled_date": "2026-09-08",
                                                     "status": "completed"}],
                   "members": graph["members"]}
    bx = run_report(conn, sqls["baseline"], {**base, "include_trace": False}, mats, graph_extra)
    ox = run_report(conn, sqls["optimized"], {**base, "include_trace": False}, mats, graph_extra)
    checks["extra_graph_schedule_detected"] = (
        bx["graph_extra_schedules"] == [999999] and ox["graph_extra_schedules"] == [999999])
    graph_no_member = {"schedule": graph["schedule"],
                       "members": [m for m in graph["members"] if m["student_id"] != 1]}
    bm = run_report(conn, sqls["baseline"], {**base, "include_trace": False}, mats, graph_no_member)
    om = run_report(conn, sqls["optimized"], {**base, "include_trace": False}, mats, graph_no_member)
    checks["missing_graph_member_detected"] = (
        bm["graph_missing_members"] == [1] and om["graph_missing_members"] == [1])
    out["expected"] = expected
    out["checks"] = checks
    out["all_passed"] = all(checks.values()) and \
        out["include_trace_false"]["baseline_equals_optimized"] and \
        out["include_trace_true"]["baseline_equals_optimized"] and \
        out["include_trace_false"]["baseline"]["graph_consistent"] and \
        out["include_trace_true"]["baseline"]["graph_consistent"]
    return out

# ------------------------------------------------------------- run_benchmarks

def _validate_params(sizes, repeats: int, warmup: int) -> None:
    if not isinstance(repeats, int) or not (REPS_MIN <= repeats <= REPS_MAX):
        raise ValueError(f"repeats должен быть целым {REPS_MIN}..{REPS_MAX}")
    if not isinstance(warmup, int) or not (WARMUP_MIN <= warmup <= WARMUP_MAX):
        raise ValueError(f"warmup должен быть целым {WARMUP_MIN}..{WARMUP_MAX}")
    sizes = tuple(sizes)
    if not sizes or len(sizes) > SIZES_MAX:
        raise ValueError(f"нужно 1..{SIZES_MAX} размеров")
    for n in sizes:
        if not isinstance(n, int) or not (SIZE_MIN <= n <= SIZE_MAX) or n % 25 != 0:
            raise ValueError(f"размер {n}: целое, кратно 25, в {SIZE_MIN}..{SIZE_MAX}")


def run_benchmarks(admin_dsn: str, output_dir: str | Path, sizes=SIZES_DEFAULT,
                   repeats: int = REPS_DEFAULT, warmup: int = WARMUP_DEFAULT,
                   seed: float = SEED_DEFAULT, keep_databases: bool = False,
                   docker_ctx: dict | None = None, run_id: str | None = None) -> dict:
    """Портативное ядро (API_PORTABILITY.md): psycopg + admin_dsn выделенного
    PostgreSQL, без docker/shell. БД уникальны по run_id, cleanup только своих."""
    sizes = tuple(sizes)
    _validate_params(sizes, repeats, warmup)
    if run_id is None:
        run_id = secrets.token_hex(4)
    elif not re.match(r"^[a-z0-9]{1,16}$", run_id):
        raise ValueError("run_id: строчные латинские буквы/цифры, до 16 символов")
    out = Path(output_dir)
    plans_dir = out / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    sqls = load_sql_texts()
    admin = psycopg.connect(admin_dsn, autocommit=True,
                            options="-c statement_timeout=600s")
    created: list[str] = []
    results: dict = {
        "tool": "lab1-sql-benchmark",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "seed": seed,
        "note": "все данные синтетические (демо), не исходные 104 студента отчёта ПР3",
        "postgres_version": admin.execute("SELECT version()").fetchone()[0],
        "host": host_context(),
        "sql_sha256": sql_sha256(sqls),
        "methodology": {
            "isolation": "REPEATABLE READ READ ONLY, rollback после каждого выполнения",
            "warmup_rounds": warmup, "measured_reps": repeats, "alternating_order": True,
            "server_time": "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON): Execution Time",
            "client_time": "psycopg execute+fetch (wall clock); сериализация "
                           "параметров (json.dumps params/materials/graph_*) и "
                           "построение graph payload (build_graph_payload) — "
                           "вне таймера",
            "include_trace_during_timing": False,
            "buffers": "корневой узел Plan (агрегат поддерева), без суммирования узлов",
            "partitions": "planned = EXPLAIN без ANALYZE; executed = Actual Loops > 0; "
                          "плюс Subplans Removed (runtime pruning)",
            "cases": f"полные 16 недель 2026-09-07..{TERM_FULL_END}; "
                     "таймируемые прогоны только на валидных material IDs, "
                     "unlinked/missing junk — отдельный correctness-прогон",
            "timed_scenario": "успешный отчёт (200) c missing_policy=exclude: "
                              "рейтинг только по complete-студентам, incomplete "
                              "перечислены отдельно (ranking_complete=false при "
                              "наличии unknown); strict-409 успешным запросом "
                              "не считается и не таймируется",
            "scope": "таймируется ТОЛЬКО SQL (psycopg → PostgreSQL: Execution Time "
                     "и client execute+fetch); время API-слоя, Elasticsearch-поиска "
                     "и сериализации HTTP в замеры не входит",
            "graph_payload": "СИНТЕТИЧЕСКИЙ вход графового контракта: расписание и "
                             "состав участников строятся из той же fixture-PG "
                             "(build_graph_payload, семантика Cypher адаптера Neo4j). "
                             "Это НЕ измерение живого Neo4j; реальный HTTP-путь на "
                             "живых четырёх хранилищах измеряется отдельно",
            "planner_flags": "не менялись (enable_seqscan и пр. не трогались)",
            "statement_timeout": "180s",
        },
        "datasets": {},
        "cases": [],
        "fixture_correctness": None,
    }
    if docker_ctx:
        results["docker"] = docker_ctx

    try:
        # --- fixture ---
        fdb = f"lab1_benchmark_{run_id}_fixture"
        create_database(admin, fdb)
        created.append(fdb)
        fc = psycopg.connect(make_conninfo(admin_dsn, dbname=fdb), autocommit=True,
                             options="-c statement_timeout=600s")
        load_sql_file(fc, sqls["schema"])
        load_sql_file(fc, sqls["fixture"])
        fc.execute("ANALYZE")
        fc.close()
        conn = bench_connection(admin_dsn, fdb)
        results["fixture_correctness"] = fixture_check(conn, sqls)
        conn.close()
        print(f"[fixture] all_passed={results['fixture_correctness']['all_passed']}", flush=True)

        # --- наборы данных ---
        for n in sizes:
            db = f"lab1_benchmark_{run_id}_{n}"
            create_database(admin, db)
            created.append(db)
            t0 = time.time()
            gc = psycopg.connect(make_conninfo(admin_dsn, dbname=db), autocommit=True,
                                 options="-c statement_timeout=600s")
            load_sql_file(gc, sqls["schema"])
            generate_dataset(gc, n, seed)
            gc.execute("ANALYZE")
            stats = table_stats(gc)
            gc.close()
            results["datasets"][db] = stats
            print(f"[{db}] loaded+analyzed in {time.time()-t0:.1f}s: {stats}", flush=True)

            conn = bench_connection(admin_dsn, db)
            for case in build_cases(conn):
                t0 = time.time()
                cr = bench_case(conn, sqls, db, case, plans_dir, repeats, warmup)
                results["cases"].append(cr)
                print(f"[{db}][{case['name']}] eq(trace=false)={cr['equality']['include_trace_false']} "
                      f"eq(trace=true)={cr['equality']['include_trace_true']} "
                      f"exec median base={cr['baseline']['exec_time_ms']['median']}ms "
                      f"opt={cr['optimized']['exec_time_ms']['median']}ms "
                      f"speedup={cr['speedup_exec_median']}x ({time.time()-t0:.1f}s)", flush=True)
            conn.close()
    finally:
        # cleanup строго только БД, созданных этим запуском (created-by-this-run)
        if not keep_databases:
            for db in created:
                try:
                    drop_database(admin, db)
                except Exception as e:  # noqa: BLE001
                    print(f"[cleanup] не удалено {db}: {e}", flush=True)
        admin.close()

    (out / "benchmark.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1,
                   default=_json_default), encoding="utf-8")
    return results


def _json_default(o):
    from decimal import Decimal
    if isinstance(o, Decimal):
        return float(o)
    return str(o)

# ---------------------------------------------------------------------- main

def correctness_ok(results: dict) -> bool:
    fc = results.get("fixture_correctness")
    if not fc or not fc.get("all_passed"):
        return False
    for c in results["cases"]:
        if not (c["equality"]["include_trace_false"] and c["equality"]["include_trace_true"]):
            return False
        jc = c.get("junk_correctness")
        if jc is not None and not (jc["unlinked_materials_equals_junk"]
                                   and jc["matched_unchanged"]
                                   and jc["baseline_equals_optimized"]
                                   and jc.get("tampered_graph_detected", False)):
            return False
    return True


def print_summary(results: dict) -> None:
    print("\n=== ИТОГИ ===")
    print(f"{'dataset':<34}{'case':<9}{'base,ms':>9}{'opt,ms':>9}{'speedup':>9}"
          f"{'parts ex/pl':>12}{'eq':>5}")
    for c in results["cases"]:
        eq = c["equality"]["include_trace_false"] and c["equality"]["include_trace_true"]
        parts = (f"{c['optimized']['attendance_executed_count']}"
                 f"/{c['optimized']['attendance_planned_count']}")
        print(f"{c['dataset']:<34}{c['case']:<9}"
              f"{c['baseline']['exec_time_ms']['median']:>9}"
              f"{c['optimized']['exec_time_ms']['median']:>9}"
              f"{c['speedup_exec_median']:>8}x{parts:>12}{('OK' if eq else 'FAIL'):>5}")
    fc = results.get("fixture_correctness")
    if fc:
        print(f"fixture: all_passed={fc['all_passed']} checks={fc['checks']}")
    print(f"correctness_ok={correctness_ok(results)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="ЛР1 SQL benchmark: baseline vs optimized")
    ap.add_argument("--sizes", default=",".join(str(s) for s in SIZES_DEFAULT))
    ap.add_argument("--repeats", type=int, default=REPS_DEFAULT)
    ap.add_argument("--warmup", type=int, default=WARMUP_DEFAULT)
    ap.add_argument("--seed", type=float, default=SEED_DEFAULT)
    ap.add_argument("--dsn", default=None,
                    help="портативный режим: DSN выделенного PostgreSQL (docker не используется)")
    ap.add_argument("--preflight", action="store_true",
                    help="быстрая проверка корректности: fixture + 100 студентов, 5 повторов")
    ap.add_argument("--keep-container", action="store_true")
    ap.add_argument("--keep-databases", action="store_true")
    ap.add_argument("--output", default=str(WORKDIR / "output"))
    a = ap.parse_args()
    sizes = [int(x) for x in a.sizes.split(",") if x.strip()]
    if a.preflight:
        sizes, repeats = [100], 5
    else:
        repeats = a.repeats
        assert repeats >= REPS_MIN, f"нужно >= {REPS_MIN} повторов"
    assert a.warmup >= WARMUP_MIN

    if a.dsn:
        results = run_benchmarks(a.dsn, a.output, sizes, repeats, a.warmup, a.seed,
                                 a.keep_databases, docker_ctx=None)
    else:
        container, dsn = start_pg_container()
        print(f"[docker] container {container} started", flush=True)
        try:
            results = run_benchmarks(dsn, a.output, sizes, repeats, a.warmup, a.seed,
                                     a.keep_databases, docker_ctx=docker_context(container))
        finally:
            if a.keep_container:
                print(f"[docker] container {container} сохранён (--keep-container)")
            else:
                remove_container(container)
                print(f"[docker] container {container} остановлен и удалён", flush=True)
    print_summary(results)
    if a.preflight and not correctness_ok(results):
        print("PREFLIGHT FAILED", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
