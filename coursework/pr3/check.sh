#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../1_lab"

docker compose exec -T report python - <<'PY'
from urllib.request import urlopen
import json

from neo4j import GraphDatabase
from pymongo import MongoClient
import psycopg
from redis import Redis

from app.config import service_settings

settings = service_settings()
with psycopg.connect(settings.pg_dsn, connect_timeout=5) as pg:
    pg.read_only = True
    groups, students, courses, lectures, schedule, attendance, materials, partitions = pg.execute("""
        SELECT (SELECT count(*) FROM practice03.study_groups),
               (SELECT count(*) FROM practice03.students),
               (SELECT count(*) FROM practice03.courses),
               (SELECT count(*) FROM practice03.lectures),
               (SELECT count(*) FROM practice03.schedule),
               (SELECT count(*) FROM practice03.attendance),
               (SELECT count(*) FROM practice03.lecture_materials),
               (SELECT count(*) FROM pg_partition_tree('practice03.attendance') WHERE isleaf)
    """).fetchone()
    print(f"PostgreSQL · групп {groups}, студентов {students}, курсов {courses}, тем {lectures}, "
          f"занятий {schedule}, отметок {attendance}, материалов {materials}, недельных партиций {partitions}")

with Redis(host=settings.redis_host, port=settings.redis_port, db=3) as redis:
    cards = redis.dbsize()
assert cards == students
print(f"Redis · {cards} карточек по номеру зачётки")

with MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000) as mongo:
    catalog = list(mongo.practice03.universities.find())
    catalog_courses = {
        course["id"]
        for university in catalog for institute in university["institutes"]
        for department in institute["departments"] for specialty in department["specialties"]
        for course in specialty["courses"]
    }
assert len(catalog_courses) == courses
print(f"MongoDB · университетов {len(catalog)}, курсов во вложенном каталоге {len(catalog_courses)}")

with GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)) as driver:
    with driver.session(default_access_mode='READ') as session:
        links = session.run("""
          MATCH (st:Practice03:Student)-[:MEMBER_OF]->(g:Practice03:Group)
                -[:HAS_SCHEDULE]->(:Practice03:Schedule)-[:FOR_LECTURE]->(l:Practice03:Lecture)
                <-[:HAS_LESSON]-(:Practice03:Course)
          RETURN count(DISTINCT st) AS students, count(DISTINCT g) AS groups,
                 count(DISTINCT l) AS lectures
        """).single()
        graph_attendance = session.run("MATCH (a) WHERE 'Attendance' IN labels(a) RETURN count(a) AS count").single()["count"]
assert (links["students"], links["groups"], graph_attendance) == (students, groups, 0)
print(f"Neo4j · связи {links['students']} студентов и {links['groups']} групп, "
      f"тем в расписании {links['lectures']}, записей посещения {graph_attendance}")

with urlopen(f"{settings.es_url}/{settings.es_index}/_count", timeout=5) as response:
    indexed = json.load(response)["count"]
assert indexed == materials
print(f"Elasticsearch · {indexed} проиндексированных материалов")
PY
