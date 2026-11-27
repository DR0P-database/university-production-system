"""Вход пользователя, сервисные токены и передача запроса отчёту."""
import json
import sqlite3
import time
from pathlib import Path
from typing import Any
STATUS_LOADING = "loading"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
_STATUSES = (STATUS_LOADING, STATUS_READY, STATUS_FAILED)
class DatasetStateConflict(Exception):
    def __init__(self, message: str, current: dict[str, Any] | None):
        self.current = current
        super().__init__(message)
def _row_to_state(row: tuple | None) -> dict[str, Any] | None:
    if row is None:
        return None
    generation_id, status, updated_at, details = row
    state: dict[str, Any] = {
        "generation_id": generation_id,
        "status": status,
        "updated_at": updated_at,
    }
    if details:
        try:
            state["details"] = json.loads(details)
        except ValueError:
            state["details"] = None
    return state
class DatasetStateStore:
    def __init__(self, path: Path):
        self._path = str(path)
        self._init_db()
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn
    def _init_db(self) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS dataset_state ("
                " singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),"
                " generation_id text NOT NULL,"
                " status text NOT NULL CHECK (status IN"
                "   ('loading','ready','failed')),"
                " updated_at text NOT NULL,"
                " details text)")
    def get(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT generation_id, status, updated_at, details"
                " FROM dataset_state WHERE singleton").fetchone()
        return _row_to_state(row)
    def publish_loading(self, generation_id: str,
                        details: dict[str, Any] | None = None) -> dict[str, Any]:
        if not generation_id:
            raise ValueError("generation_id обязателен")
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO dataset_state"
                " (singleton, generation_id, status, updated_at, details)"
                " VALUES (true, ?, 'loading', ?, ?)"
                " ON CONFLICT(singleton) DO UPDATE SET"
                "  generation_id=excluded.generation_id, status='loading',"
                "  updated_at=excluded.updated_at, details=excluded.details",
                (generation_id, now,
                 json.dumps(details, ensure_ascii=False) if details else None))
        state = self.get()
        assert state is not None and state["status"] == STATUS_LOADING
        return state
    def complete(self, generation_id: str, status: str,
                 details: dict[str, Any] | None = None) -> dict[str, Any]:
        if status not in (STATUS_READY, STATUS_FAILED):
            raise ValueError("complete() принимает только ready/failed")
        if not generation_id:
            raise ValueError("generation_id обязателен")
        current = self.get()
        if current is None or current["generation_id"] != generation_id:
            raise DatasetStateConflict(
                "Состояние набора принадлежит другой генерации", current)
        if status == STATUS_READY and current["status"] == STATUS_FAILED:
            raise DatasetStateConflict(
                "Генерация уже помечена failed; ready для неё невозможен", current)
        if current["status"] == status:
            return current
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE dataset_state SET status=?, updated_at=?, details=?"
                " WHERE singleton AND generation_id=? AND status=?",
                (status, now,
                 json.dumps(details, ensure_ascii=False) if details else None,
                 generation_id, current["status"]))
            if cur.rowcount != 1:
                raise DatasetStateConflict(
                    "Состояние набора изменилось конкурирующей операцией", self.get())
        state = self.get()
        assert state is not None
        return state


from contextlib import asynccontextmanager
from typing import Annotated
import anyio
import httpx
from fastapi import Depends, FastAPI, Form, Header, Query
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from .config import (CLIENT_ASSERTION_TYPE, DATA_REVISION, DatasetStatePayload, ReportError, SearchParams, RoomParams, GroupHoursParams,
    gateway_settings, install_error_handlers, install_no_store_middleware)
from .auth import UsersStore, ClientRegistry, ReplayStore, ServiceTokenClient, issue_user_token, verify_user_token, verify_client_assertion, issue_service_token, verify_service_token


def create_app(settings=None, http_client=None):
    s = settings or gateway_settings()
    user_private = s.user_issuer_private_key_file.read_text()
    user_public = s.user_public_key_file.read_text()
    service_private = s.service_issuer_private_key_file.read_text()
    service_public = s.service_issuer_public_key_file.read_text()
    users = UsersStore.from_file(s.users_file)
    clients = ClientRegistry.from_file(s.clients_file)
    replay = ReplayStore(s.replay_db_file)
    dataset = DatasetStateStore(s.replay_db_file)
    tokens = ServiceTokenClient('gateway', s.service_client_private_key_file, s.service_token_url)
    http = http_client or httpx.AsyncClient(timeout=60)
    oauth = OAuth2PasswordBearer(tokenUrl='/auth/token')

    @asynccontextmanager
    async def lifespan(app):
        yield
        await http.aclose()

    app = FastAPI(title='Учебная аналитика — ЛР №1–3', description='Войдите через Authorize и выберите отчёт.', lifespan=lifespan)
    install_error_handlers(app)
    install_no_store_middleware(app)
    app.state.dataset = dataset
    app.state.tokens = tokens

    def user_access(token: Annotated[str, Depends(oauth)]):
        claims = verify_user_token(token, user_public)
        if 'lab1:read' not in claims['scope'].split():
            raise ReportError(403, 'Нет права на получение отчёта')
        return token

    def generator_access(authorization, scope):
        token = authorization[7:] if authorization.startswith('Bearer ') else ''
        return verify_service_token(token, service_public, 'gateway-internal', scope, ['generator'])

    @app.post('/auth/token', tags=['Вход'])
    def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]):
        user = users.authenticate(form.username, form.password)
        scopes = form.scopes or user['scopes']
        if not set(scopes) <= set(user['scopes']):
            raise ReportError(400, 'invalid_scope')
        token = issue_user_token(user['username'], scopes, user_private)
        return {'access_token': token, 'token_type': 'Bearer', 'expires_in': 900, 'scope': ' '.join(scopes)}

    @app.post('/auth/service-token', include_in_schema=False)
    def service_token(grant_type: Annotated[str, Form()], client_id: Annotated[str, Form()],
                      client_assertion_type: Annotated[str, Form()], client_assertion: Annotated[str, Form()],
                      audience: Annotated[str, Form()], scope: Annotated[str, Form()] = ''):
        if grant_type != 'client_credentials' or client_assertion_type != CLIENT_ASSERTION_TYPE:
            raise ReportError(400, 'Неверный способ аутентификации сервиса')
        public = clients.public_key(client_id)
        if public is None:
            raise ReportError(401, 'Неизвестный сервис')
        jti, expires = verify_client_assertion(client_assertion, client_id, public)
        if not replay.check_and_remember(jti, client_id, expires):
            raise ReportError(401, 'Повтор client assertion')
        allowed = clients.allowed_scopes(client_id, audience)
        requested = scope.split() if scope else sorted(allowed or [])
        if not allowed or not requested or not set(requested) <= allowed:
            raise ReportError(403, 'Недопустимые права сервиса')
        token = issue_service_token(client_id, audience, requested, service_private, 60)
        return {'access_token': token, 'token_type': 'Bearer', 'expires_in': 60, 'scope': ' '.join(requested)}

    @app.get('/internal/dataset/state', include_in_schema=False)
    def read_state(authorization: Annotated[str, Header()] = ''):
        generator_access(authorization, 'dataset:state:read')
        return {'state': dataset.get()}

    @app.post('/internal/dataset/state', include_in_schema=False)
    def write_state(payload: DatasetStatePayload, authorization: Annotated[str, Header()] = ''):
        generator_access(authorization, 'dataset:state:update')
        try:
            state = dataset.publish_loading(payload.generation_id, payload.details or {}) if payload.status == 'loading' else dataset.complete(payload.generation_id, payload.status, payload.details or {})
        except DatasetStateConflict:
            raise ReportError(409, 'Устаревшая версия загрузки данных') from None
        return {'state': state}

    async def forward(url, path, audience, params, user_token):
        before = dataset.get()
        if not before or before['status'] != 'ready' or (before['details'] or {}).get('revision') != DATA_REVISION:
            raise ReportError(503, 'Начальные данные ещё не готовы')
        token = await anyio.to_thread.run_sync(tokens.get_token, audience, 'lab1:read')
        try:
            response = await http.get(url + path, params=params.model_dump(mode='json'), headers={'Authorization': 'Bearer ' + token, 'X-User-Token': user_token})
            body = response.json()
        except (httpx.HTTPError, ValueError):
            raise ReportError(503, 'Сервис отчёта недоступен') from None
        after = dataset.get()
        if not after or after['status'] != 'ready' or before['generation_id'] != after['generation_id']:
            raise ReportError(503, 'Данные изменились во время запроса; повторите запрос')
        return JSONResponse(status_code=response.status_code, content=body)

    @app.get('/api/v1/reports/attendance', tags=['ЛР №1'], summary='Десять студентов с минимальной посещаемостью')
    async def report(params: Annotated[SearchParams, Query()], user_token: Annotated[str, Depends(user_access)]):
        return await forward(s.report_base_url, '/reports/attendance', 'report-service', params, user_token)

    @app.get('/api/v1/reports/classroom-capacity', tags=['ЛР №2'], summary='Вместимость аудитории и оборудование')
    async def rooms(params: Annotated[RoomParams, Query()], user_token: Annotated[str, Depends(user_access)]):
        return await forward(s.rooms_base_url, '/reports/classroom-capacity', 'rooms-service', params, user_token)

    @app.get('/api/v1/reports/group-lecture-hours', tags=['ЛР №3'], summary='Запланированные и посещённые часы группы')
    async def hours(params: Annotated[GroupHoursParams, Query()], user_token: Annotated[str, Depends(user_access)]):
        return await forward(s.hours_base_url, '/reports/group-lecture-hours', 'hours-service', params, user_token)

    @app.get('/health', include_in_schema=False)
    def health():
        return {'status': 'up'}

    return app


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(create_app(), host='0.0.0.0', port=8000)
