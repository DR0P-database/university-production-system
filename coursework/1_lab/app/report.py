"""Поиск ES → расписание Neo4j → SQL top-10 → карточки Redis."""
from .config import (SearchParams, ReportError, service_settings, install_error_handlers, install_no_store_middleware)
from .auth import verify_user_token, verify_service_token
import httpx
from typing import Any
import datetime as dt
import re
from pathlib import Path
import psycopg
from psycopg.types.json import Jsonb
from contextlib import asynccontextmanager
from typing import Annotated
from fastapi import FastAPI, Header, Query


def create_report(params, search, graph, repo, cards):
    materials = search.search(params.term)
    lecture_ids = sorted({m['lecture_id'] for m in materials})
    selection = graph.fetch_selection(lecture_ids, params.date_from.isoformat(), params.date_to.isoformat(), None)
    result = repo.report(params, materials, selection)
    mismatches = ('unlinked_materials', 'graph_missing_schedules', 'graph_extra_schedules',
                  'graph_wrong_schedules', 'graph_missing_members', 'graph_extra_members', 'graph_wrong_members')
    if any(result.get(key) for key in mismatches):
        raise ReportError(409, 'Проекции Elasticsearch/Neo4j расходятся с PostgreSQL')
    if result.get('incomplete_students'):
        raise ReportError(409, 'В журнале есть занятия без отметок; точный рейтинг невозможен')
    winners = result['results']
    pg_students = {row['student_pg']['record_book']: row['student_pg'] for row in winners}
    profiles = cards.fetch_validated_cards(list(pg_students), pg_students)
    return {
        'term': params.term,
        'period': {'from': params.date_from.isoformat(), 'to': params.date_to.isoformat()},
        'results': [{'student': profiles[row['student_pg']['record_book']],
                     'attendance_percentage': row['attendance_percentage'],
                     'present_count': row['present_count'], 'expected_count': row['expected_count']}
                    for row in winners],
    }


class MaterialSearch:
    def __init__(self, base_url, index="practice03_materials", timeout=20.0, client=None):
        self.base_url = base_url.rstrip("/")
        self.index = index
        self.timeout = timeout
        self._client = client or httpx.Client(timeout=timeout)
    def search(self, word):
        data = self._request("POST", f"/{self.index}/_search?allow_partial_search_results=false", {
            "query": {"multi_match": {"query": word, "type": "phrase", "fields": ["title", "content_text"]}},
            "_source": ["id", "lecture_id", "course_id"],
            "size": 10_000,
            "track_total_hits": True,
        })
        try:
            hits = data["hits"]["hits"]
            if data["hits"]["total"]["relation"] != "eq" or data["hits"]["total"]["value"] != len(hits):
                raise ReportError(503, "Полная выдача не помещается в лимит поиска — 10 000 материалов")
            materials = [hit["_source"] for hit in hits]
            if any(type(m.get(k)) is not int for m in materials for k in ("id", "lecture_id", "course_id")):
                raise ReportError(409, "Некорректные ID материалов в Elasticsearch")
            return materials
        except (KeyError, TypeError, AttributeError):
            raise ReportError(503, "Elasticsearch вернул некорректный ответ") from None
    def _request(self, method, path, body=None):
        try:
            response = self._client.request(method, self.base_url + path, json=body, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            if data.get("timed_out") or data.get("_shards", {}).get("failed"):
                raise ReportError(503, "Elasticsearch вернул неполный результат")
            return data
        except (httpx.HTTPError, ValueError, AttributeError, TypeError):
            raise ReportError(503, "Elasticsearch недоступен или вернул некорректный ответ") from None

MAX_GRAPH_SCHEDULE_ROWS = 100_000
MAX_GRAPH_MEMBER_ROWS = 1_000_000
_SCHEDULE_CYPHER = """
MATCH (g:Practice03:Group)-[:HAS_SCHEDULE]->(sc:Practice03:Schedule)
      -[:FOR_LECTURE]->(l:Practice03:Lecture)
WHERE l.id IN $lecture_ids
  AND l.lesson_type = 'lecture'
  AND sc.status = 'completed'
  AND sc.scheduled_date >= $date_from
  AND sc.scheduled_date <= $date_to
  AND ($group_id IS NULL OR g.id = $group_id)
MATCH (c:Practice03:Course)-[:HAS_LESSON]->(l)
RETURN sc.id AS schedule_id, sc.scheduled_date AS scheduled_date,
       sc.status AS status, l.id AS lecture_id,
       c.id AS course_id, g.id AS group_id
ORDER BY schedule_id
LIMIT $row_limit
"""
_MEMBERS_CYPHER = """
MATCH (st:Practice03:Student)-[:MEMBER_OF]->(g:Practice03:Group)
WHERE g.id IN $group_ids
RETURN st.id AS student_id, st.record_book AS record_book, g.id AS group_id
ORDER BY student_id
LIMIT $row_limit
"""
def _int_field(row: dict, key: str, index: int) -> int:
    value = row.get(key)
    if type(value) is not int:
        raise ReportError(
            409, f"Neo4j вернул некорректное поле {key!r} в строке {index}: "
                 "граф не соответствует числовой схеме ID из ПР3")
    return value
class GraphRepo:
    def __init__(self, uri: str, user: str, password: str,
                 timeout_seconds: float = 15.0, driver_factory=None):
        self._uri = uri
        self._timeout = float(timeout_seconds)
        if driver_factory is None:
            from neo4j import GraphDatabase
            def driver_factory(uri, auth, connection_timeout, max_connection_pool_size):
                return GraphDatabase.driver(
                    uri, auth=auth, connection_timeout=connection_timeout,
                    max_connection_pool_size=max_connection_pool_size,
                    user_agent="lab1-report/1.2")
        try:
            self._driver = driver_factory(
                uri, auth=(user, password),
                connection_timeout=max(self._timeout, 1.0),
                max_connection_pool_size=8)
        except Exception as exc:
            raise ReportError(503, "Neo4j недоступен: не удалось создать подключение") from exc
    def close(self) -> None:
        try:
            self._driver.close()
        except Exception:
            pass
    def _run(self, session, cypher: str, row_cap: int, **params) -> list[dict]:
        from neo4j import Query
        try:
            result = session.run(Query(text=cypher, timeout=self._timeout),
                                 row_limit=row_cap + 1, **params)
            rows: list[dict] = []
            for record in result:
                rows.append(dict(record))
                if len(rows) > row_cap:
                    self._discard(result)
                    raise ReportError(
                        503, "Neo4j вернул больше строк, чем допускает "
                             "предохранитель чтения")
            return rows
        except ReportError:
            raise
        except Exception as exc:
            raise ReportError(503, "Neo4j недоступен или вернул ошибку") from exc
    @staticmethod
    def _discard(result) -> None:
        try:
            result.consume()
        except Exception:
            pass
    def fetch_selection(self, lecture_ids: list[int], date_from: str, date_to: str,
                        group_id: int | None) -> dict[str, Any]:
        try:
            from neo4j import READ_ACCESS
            with self._driver.session(default_access_mode=READ_ACCESS) as session:
                raw_schedule = self._run(session, _SCHEDULE_CYPHER,
                                         MAX_GRAPH_SCHEDULE_ROWS,
                                         lecture_ids=list(lecture_ids),
                                         date_from=date_from, date_to=date_to,
                                         group_id=group_id)
                group_ids = sorted({row["group_id"] for row in raw_schedule
                                    if isinstance(row.get("group_id"), int)})
                raw_members = (self._run(session, _MEMBERS_CYPHER,
                                         MAX_GRAPH_MEMBER_ROWS,
                                         group_ids=group_ids)
                               if group_ids else [])
        except ReportError:
            raise
        except Exception as exc:
            raise ReportError(503, "Neo4j недоступен или вернул ошибку") from exc
        schedule: list[dict] = []
        seen_schedule: set[int] = set()
        for index, row in enumerate(raw_schedule):
            item = {
                "schedule_id": _int_field(row, "schedule_id", index),
                "lecture_id": _int_field(row, "lecture_id", index),
                "course_id": _int_field(row, "course_id", index),
                "group_id": _int_field(row, "group_id", index),
                "scheduled_date": row.get("scheduled_date"),
                "status": row.get("status"),
            }
            if not isinstance(item["scheduled_date"], str) \
                    or not isinstance(item["status"], str):
                raise ReportError(
                    409, "Neo4j вернул некорректные поля расписания "
                         "(дата/статус не являются строками)")
            if item["schedule_id"] in seen_schedule:
                raise ReportError(
                    409, "Neo4j вернул дубликат занятия — граф не согласован")
            seen_schedule.add(item["schedule_id"])
            schedule.append(item)
        members: list[dict] = []
        seen_member: set[tuple[int, int]] = set()
        for index, row in enumerate(raw_members):
            member = {
                "student_id": _int_field(row, "student_id", index),
                "group_id": _int_field(row, "group_id", index),
                "record_book": row.get("record_book"),
            }
            if not isinstance(member["record_book"], str):
                raise ReportError(
                    409, "Neo4j вернул некорректный номер зачётной книжки")
            key = (member["student_id"], member["group_id"])
            if key in seen_member:
                raise ReportError(
                    409, "Neo4j вернул дубликат членства в группе — граф не согласован")
            seen_member.add(key)
            members.append(member)
        return {"schedule": schedule, "members": members, "group_ids": group_ids}

CARD_FIELDS = ("id", "group_id", "record_book", "last_name", "first_name",
               "patronymic", "email", "phone", "enrollment_date", "status")
NULLABLE_FIELDS = ("patronymic", "email", "phone")
_DIGITS_RE = re.compile(r"\d+")
def normalize_card(raw: dict, record_book: str) -> dict[str, Any]:
    problems: list[str] = []
    if not isinstance(raw, dict):
        raise ReportError(409, f"Redis-карточка {record_book}: некорректный тип")
    missing = [f for f in CARD_FIELDS if f not in raw]
    extra = [f for f in raw if f not in CARD_FIELDS]
    if missing:
        problems.append(f"нет полей: {', '.join(missing)}")
    if extra:
        problems.append(f"лишние поля: {', '.join(sorted(extra))}")
    if problems:
        raise ReportError(409, f"Redis-карточка {record_book} не соответствует "
                               "контракту (устарела)", {"record_book": record_book,
                                                        "problems": problems})
    card: dict[str, Any] = {}
    for field in CARD_FIELDS:
        value = raw[field]
        if not isinstance(value, str):
            raise ReportError(409, f"Redis-карточка {record_book}: поле {field} "
                                   "не является строкой")
        if field in ("id", "group_id"):
            if not _DIGITS_RE.fullmatch(value):
                raise ReportError(409, f"Redis-карточка {record_book}: поле {field} "
                                       "не целое число")
            card[field] = int(value)
        elif field == "enrollment_date":
            try:
                parsed = dt.date.fromisoformat(value)
            except ValueError:
                raise ReportError(409, f"Redis-карточка {record_book}: "
                                       "enrollment_date не дата YYYY-MM-DD") from None
            if parsed.isoformat() != value:
                raise ReportError(409, f"Redis-карточка {record_book}: "
                                       "enrollment_date не дата YYYY-MM-DD")
            card[field] = value
        elif field in NULLABLE_FIELDS:
            card[field] = value
        else:
            if not value.strip():
                raise ReportError(409, f"Redis-карточка {record_book}: обязательное "
                                       f"поле {field} пусто")
            card[field] = value
    return card
def validate_card(card: dict[str, Any], pg_student: dict[str, Any]) -> None:
    problems: list[str] = []
    for field in CARD_FIELDS:
        pg_value = pg_student.get(field)
        if field == "enrollment_date" and pg_value is not None:
            pg_value = str(pg_value)[:10]
        value = card[field]
        if field in NULLABLE_FIELDS and value == "":
            if pg_value is None or pg_value == "":
                card[field] = pg_value
            else:
                problems.append(field)
        elif value != pg_value:
            problems.append(field)
    if problems:
        raise ReportError(
            409, "Redis-карточка расходится с PostgreSQL "
                 f"(поля: {', '.join(problems)}) — проекция устарела",
            {"record_book": card["record_book"], "student_id": card["id"],
             "mismatched_fields": problems})
def build_validated_card(raw: dict, record_book: str,
                         pg_student: dict[str, Any] | None) -> dict[str, Any]:
    card = normalize_card(raw, record_book)
    if pg_student is None:
        raise ReportError(503, "Внутренняя ошибка: победитель без "
                               "PostgreSQL-строки для сверки карточки")
    validate_card(card, pg_student)
    return card
class CardStore:
    def __init__(self, host: str, port: int, db: int = 3,
                 timeout_seconds: float = 10.0, client_factory=None):
        self._host = host
        self._port = port
        self.db = db
        self._timeout = float(timeout_seconds)
        self._client_factory = client_factory
    def _client(self):
        if self._client_factory is not None:
            return self._client_factory()
        import redis
        return redis.Redis(host=self._host, port=self._port, db=self.db,
                           decode_responses=True, socket_connect_timeout=self._timeout,
                           socket_timeout=self._timeout)
    def fetch_raw_cards(self, record_books: list[str]) -> dict[str, dict | None]:
        if not record_books:
            return {}
        try:
            client = self._client()
            try:
                pipe = client.pipeline(transaction=False)
                for record_book in record_books:
                    pipe.hgetall(record_book)
                raw = pipe.execute()
            finally:
                client.close()
        except Exception as exc:
            raise ReportError(503, "Redis недоступен") from exc
        if len(raw) != len(record_books):
            raise ReportError(503, "Redis вернул некорректный ответ pipeline")
        return {rb: (value if isinstance(value, dict) and value else None)
                for rb, value in zip(record_books, raw)}
    def fetch_validated_cards(self, record_books: list[str],
                              pg_students: dict[str, dict[str, Any]]) -> dict[str, dict]:
        raw_cards = self.fetch_raw_cards(record_books)
        cards: dict[str, dict] = {}
        for record_book in record_books:
            raw = raw_cards.get(record_book)
            if raw is None:
                raise ReportError(
                    409, f"Redis-карточка {record_book} отсутствует (проекция "
                         "неполна — результат был бы недостоверен)",
                    {"record_book": record_book})
            cards[record_book] = build_validated_card(
                raw, record_book, pg_students.get(record_book))
        return cards

class PgRepo:
    def __init__(self, dsn: str, sql_dir: Path, connect_timeout: int = 5,
                 statement_timeout_ms: int = 30_000):
        self.dsn = dsn
        self.sql_dir = sql_dir
        self.connect_timeout = connect_timeout
        self.statement_timeout_ms = statement_timeout_ms
        self._report_sql = (sql_dir / "report.sql").read_text()
    def _connect(self) -> psycopg.Connection:
        try:
            conn = psycopg.connect(self.dsn, connect_timeout=self.connect_timeout,
                                   options="-c statement_timeout="
                                           f"{self.statement_timeout_ms}")
            conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            conn.read_only = True
            return conn
        except psycopg.Error as exc:
            raise ReportError(503, "PostgreSQL недоступен") from exc
    def report(self, params: SearchParams, materials: list[dict],
               graph: dict | None = None) -> dict:
        payload = {
            "term": params.term,
            "date_from": params.date_from.isoformat(),
            "date_to": params.date_to.isoformat(),
            "department_id": None,
            "group_id": None,
            "missing_policy": "strict",
            "include_trace": False,
            "limit": 10,
        }
        graph = graph or {}
        try:
            with self._connect() as conn:
                with conn.transaction():
                    conn.execute("SET LOCAL search_path = practice03, pg_catalog")
                    row = conn.execute(
                        self._report_sql,
                        {"params": Jsonb(payload), "materials": Jsonb(materials),
                         "graph_schedule": Jsonb(graph.get("schedule", [])),
                         "graph_members": Jsonb(graph.get("members", []))},
                    ).fetchone()
        except psycopg.errors.QueryCanceled as exc:
            raise ReportError(503, "Запрос к PostgreSQL превысил таймаут") from exc
        except ReportError:
            raise
        except psycopg.Error as exc:
            raise ReportError(503, "Ошибка запроса PostgreSQL; проверьте схему practice03 "
                                   "и подключение к исходной ПР3") from exc
        result: dict[str, Any] = row[0]
        if not isinstance(result, dict):
            raise ReportError(503, "PostgreSQL вернул некорректный результат")
        return result





def create_app(settings=None):
    s = settings or service_settings()
    user_public = s.user_public_key_file.read_text()
    service_public = s.service_issuer_public_key_file.read_text()
    search = MaterialSearch(s.es_url, s.es_index)
    graph = GraphRepo(s.neo4j_uri, s.neo4j_user, s.neo4j_password)
    repo = PgRepo(s.pg_dsn, s.sql_dir)
    cards = CardStore(s.redis_host, s.redis_port)

    @asynccontextmanager
    async def lifespan(app):
        yield
        graph.close()
        search._client.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    install_error_handlers(app)
    install_no_store_middleware(app)

    @app.get('/reports/attendance')
    def report(params: Annotated[SearchParams, Query()], authorization: Annotated[str, Header()] = '',
               x_user_token: Annotated[str, Header()] = ''):
        token = authorization[7:] if authorization.startswith('Bearer ') else ''
        verify_service_token(token, service_public, 'report-service', 'lab1:read', ['gateway'])
        user = verify_user_token(x_user_token, user_public)
        if 'lab1:read' not in user['scope'].split():
            raise ReportError(403, 'Нет права на получение отчёта')
        return create_report(params, search, graph, repo, cards)

    @app.get('/internal/reports/attendance')
    def selftest(params: Annotated[SearchParams, Query()], authorization: Annotated[str, Header()] = ''):
        token = authorization[7:] if authorization.startswith('Bearer ') else ''
        verify_service_token(token, service_public, 'report-service', 'lab1:verify', ['generator'])
        return create_report(params, search, graph, repo, cards)

    @app.get('/health')
    def health():
        return {'status': 'up'}

    return app


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(create_app(), host='0.0.0.0', port=8001)
