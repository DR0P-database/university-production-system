"""Сервисы ЛР №2 и ЛР №3. Compose запускает по одному отчёту в контейнере."""
import os
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Annotated

import psycopg
from fastapi import FastAPI, Header, Query
from psycopg.rows import dict_row
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from .auth import verify_service_token, verify_user_token
from .config import (GroupHoursParams, ReportError, RoomParams, SCOPE_READ,
                     install_error_handlers, service_settings)
from .report import CardStore, GraphRepo, PgRepo


ROOMS = """
MATCH (c:Practice03:Course)-[:HAS_LESSON]->(l:Practice03:Lecture)
      <-[:FOR_LECTURE]-(sc:Practice03:Schedule)<-[:HAS_SCHEDULE]-(g:Practice03:Group)
WHERE l.id IN $lectures AND g.enrollment_year = $enrollment_year AND sc.status <> 'cancelled'
OPTIONAL MATCH (st:Practice03:Student)-[:MEMBER_OF]->(g)
WHERE st.status = 'active' AND st.enrollment_date <= sc.scheduled_date
  AND EXISTS { MATCH (st)-[:ENROLLED_IN]->(c) }
RETURN l.id AS lecture_id, sc.scheduled_date AS scheduled_date,
       sc.starts_at AS starts_at, sc.ends_at AS ends_at, sc.classroom AS classroom,
       sc.teacher_name AS teacher_name,
       collect(DISTINCT g.code) AS group_codes,
       count(DISTINCT st) AS listener_count
ORDER BY scheduled_date, starts_at, classroom, lecture_id, teacher_name
LIMIT $row_limit
"""

PLAN = """
MATCH (g:Practice03:Group {id: $group_id})-[:HAS_SCHEDULE]->(sc:Practice03:Schedule)
      -[:FOR_LECTURE]->(l:Practice03:Lecture)<-[:HAS_LESSON]-(c:Practice03:Course)
WHERE sc.status <> 'cancelled'
RETURN c.id AS course_id, sc.id AS schedule_id, sc.status AS status,
       sc.scheduled_date AS scheduled_date,
       coalesce(l.lesson_type = 'lecture' AND $tag IN l.tags AND EXISTS {
           MATCH (:Practice03:Department {id: $department_id})-[:TEACHES]->(c)
       }, false) AS counts_for_hours
ORDER BY course_id, schedule_id
LIMIT $row_limit
"""

DISCIPLINE_TAG = 'специальная-дисциплина'


def classroom_capacity(params, pg, graph, mongo):
    with pg._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT * FROM practice03.courses
            WHERE code = %s AND semester = %s AND academic_year_start = %s
            ORDER BY id
        """, (params.course_code, params.semester, params.academic_year))
        courses = {course['id']: course for course in cur.fetchall()}
        if not courses:
            raise ReportError(404, 'Предмет на указанный учебный год и семестр не найден')

        course_path = 'institutes.departments.specialties.courses'
        documents = list(mongo.aggregate([
            {'$unwind': '$institutes'},
            {'$unwind': '$institutes.departments'},
            {'$unwind': '$institutes.departments.specialties'},
            {'$unwind': '$' + course_path},
            {'$match': {course_path + '.id': {'$in': list(courses)}}},
            {'$replaceWith': '$' + course_path},
        ]))
        if {doc['id'] for doc in documents} != courses.keys():
            raise ReportError(409, 'В MongoDB отсутствуют документы выбранных предметов')

        cur.execute("""
            SELECT * FROM practice03.lectures
            WHERE course_id = ANY(%s) AND requires_equipment
        """, (list(courses),))
        lectures = {lecture['id']: lecture for lecture in cur.fetchall()}

    requirements = {
        lesson['id']: lesson['technical_requirements']
        for doc in documents for lesson in doc['lectures']
        if lesson['technical_requirements']
    }
    if requirements != {lid: lecture['equipment_requirements'] for lid, lecture in lectures.items()}:
        raise ReportError(409, 'Требования к оборудованию в MongoDB и PostgreSQL расходятся')

    enrollment_year = params.academic_year - params.study_year + 1
    with graph._driver.session(default_access_mode='READ') as session:
        schedule = graph._run(session, ROOMS, 100_000, lectures=list(lectures),
                              enrollment_year=enrollment_year)
    return {
        'academic_year': params.academic_year, 'semester': params.semester,
        'study_year': params.study_year,
        'results': [
            {
                'course': courses[lectures[row['lecture_id']]['course_id']],
                'lecture': lectures[row['lecture_id']],
                'groups': sorted(row['group_codes']), 'scheduled_date': row['scheduled_date'],
                'starts_at': row['starts_at'], 'ends_at': row['ends_at'],
                'classroom': row['classroom'], 'teacher_name': row['teacher_name'],
                'listener_count': row['listener_count'],
                'technical_requirements': requirements[row['lecture_id']],
            }
            for row in schedule
        ],
    }


def group_hours(params, pg, graph, cards):
    with pg._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute('SELECT * FROM practice03.study_groups WHERE code = %s', (params.group_code,))
        group = cur.fetchone()
        if group is None:
            raise ReportError(404, 'Группа не найдена')

        with graph._driver.session(default_access_mode='READ') as session:
            plan = graph._run(session, PLAN, 100_000, group_id=group['id'],
                              department_id=group['department_id'], tag=DISCIPLINE_TAG)
        by_course = defaultdict(list)
        completed = {}
        for row in plan:
            lessons = by_course[row['course_id']]
            if row['counts_for_hours']:
                day = date.fromisoformat(row['scheduled_date'])
                lessons.append((row['schedule_id'], day))
                if row['status'] == 'completed':
                    completed[row['schedule_id']] = day - timedelta(days=day.weekday())

        cur.execute('SELECT * FROM practice03.courses WHERE id = ANY(%s) ORDER BY id',
                    (list(by_course),))
        courses = cur.fetchall()
        if len(courses) != len(by_course):
            raise ReportError(409, 'В Neo4j есть курсы, отсутствующие в PostgreSQL')
        cur.execute('SELECT * FROM practice03.students WHERE group_id = %s ORDER BY id',
                    (group['id'],))
        students = cur.fetchall()
        marks = {}
        if completed and students:
            weeks = sorted(set(completed.values()))
            cur.execute("""
                SELECT week_start_date, schedule_id, student_id, is_present
                FROM practice03.attendance
                WHERE week_start_date BETWEEN %s AND %s AND week_start_date = ANY(%s)
                  AND schedule_id = ANY(%s) AND student_id = ANY(%s)
            """, (weeks[0], weeks[-1], weeks, list(completed), [s['id'] for s in students]))
            for row in cur.fetchall():
                schedule_id = row['schedule_id']
                if row['week_start_date'] != completed[schedule_id]:
                    raise ReportError(409, 'Неделя посещения расходится с расписанием Neo4j')
                marks[schedule_id, row['student_id']] = row['is_present']

    cards_by_book = {student['record_book']: student for student in students} if courses else {}
    profiles = cards.fetch_validated_cards(list(cards_by_book), cards_by_book)
    results = []
    for student in students:
        for course in courses:
            eligible = [sid for sid, day in by_course[course['id']] if day >= student['enrollment_date']]
            completed_marks = [marks.get((sid, student['id'])) for sid in eligible if sid in completed]
            if None in completed_marks:
                raise ReportError(409, 'В журнале есть занятия без отметок; точный отчёт невозможен')
            results.append({
                'student': profiles[student['record_book']], 'course': course,
                'planned_hours': 2 * len(eligible), 'attended_hours': 2 * sum(completed_marks),
            })
    return {'group': group, 'results': results}


def create_app(kind):
    settings = service_settings()
    graph = GraphRepo(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    pg = PgRepo(settings.pg_dsn, settings.sql_dir)
    mongo = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000) if kind == 'rooms' else None
    cards = CardStore(settings.redis_host, settings.redis_port) if kind == 'hours' else None
    user_key = settings.user_public_key_file.read_text()
    service_key = settings.service_issuer_public_key_file.read_text()

    @asynccontextmanager
    async def lifespan(app):
        yield
        graph.close()
        if mongo is not None:
            mongo.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    install_error_handlers(app)

    def run(report, params, authorization, user_token, *stores):
        token = authorization.removeprefix('Bearer ') if authorization.startswith('Bearer ') else ''
        verify_service_token(token, service_key, kind + '-service', SCOPE_READ, ['gateway'])
        if SCOPE_READ not in verify_user_token(user_token, user_key)['scope'].split():
            raise ReportError(403, 'Нет права на получение отчёта')
        try:
            return report(params, pg, graph, *stores)
        except (psycopg.Error, PyMongoError) as exc:
            raise ReportError(503, 'Хранилище отчёта недоступно') from exc

    if kind == 'rooms':
        @app.get('/reports/classroom-capacity')
        def rooms(params: Annotated[RoomParams, Query()], authorization: Annotated[str, Header()] = '',
                  x_user_token: Annotated[str, Header()] = ''):
            return run(classroom_capacity, params, authorization, x_user_token, mongo.practice03.universities)
    else:
        @app.get('/reports/group-lecture-hours')
        def hours(params: Annotated[GroupHoursParams, Query()], authorization: Annotated[str, Header()] = '',
                  x_user_token: Annotated[str, Header()] = ''):
            return run(group_hours, params, authorization, x_user_token, cards)

    return app


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(create_app(os.environ['REPORT_KIND']), host='0.0.0.0', port=8001)
