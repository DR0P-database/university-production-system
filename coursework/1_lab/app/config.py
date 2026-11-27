"""Настройки, параметры запроса и общие HTTP-ошибки."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_REVISION = 3
USER_ISSUER = "lab1-user-issuer"
USER_AUDIENCE = "lab1-users"
USER_TOKEN_USE = "user"
USER_TOKEN_TTL_SECONDS = 900
SERVICE_ISSUER = "lab1-service-issuer"
SERVICE_TOKEN_USE = "service"
SERVICE_TOKEN_TTL_SECONDS = 60
SERVICE_TOKEN_MAX_TTL_SECONDS = 120
ASSERTION_AUDIENCE = "urn:lab1:service-token"
CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
ASSERTION_MAX_LIFETIME_SECONDS = 60
SCOPE_READ = "lab1:read"
SCOPE_VERIFY = "lab1:verify"
SCOPE_DATASET_STATE_UPDATE = "dataset:state:update"
SCOPE_DATASET_STATE_READ = "dataset:state:read"
def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default
def _path_env(name: str, default: Path) -> Path:
    return Path(_env(name, str(default)))
@dataclass(kw_only=True)
class CommonAuthSettings:
    user_public_key_file: Path = field(default_factory=lambda: _path_env(
        "USER_ISSUER_PUBLIC_KEY_FILE", PROJECT_ROOT / "secrets" / "user_public.pem"))
    service_issuer_public_key_file: Path = field(default_factory=lambda: _path_env(
        "SERVICE_ISSUER_PUBLIC_KEY_FILE", PROJECT_ROOT / "secrets" / "service_issuer_public.pem"))
@dataclass(kw_only=True)
class GatewaySettings(CommonAuthSettings):
    user_issuer_private_key_file: Path = field(default_factory=lambda: _path_env(
        "USER_ISSUER_PRIVATE_KEY_FILE", PROJECT_ROOT / "secrets" / "user_private.pem"))
    service_issuer_private_key_file: Path = field(default_factory=lambda: _path_env(
        "SERVICE_ISSUER_PRIVATE_KEY_FILE", PROJECT_ROOT / "secrets" / "service_issuer_private.pem"))
    clients_file: Path = field(default_factory=lambda: _path_env(
        "LAB1_CLIENTS_FILE", PROJECT_ROOT / "secrets" / "clients.json"))
    replay_db_file: Path = field(default_factory=lambda: _path_env(
        "REPLAY_DB_FILE", PROJECT_ROOT / "secrets" / "replay.sqlite"))
    service_client_private_key_file: Path = field(default_factory=lambda: _path_env(
        "SERVICE_CLIENT_PRIVATE_KEY_FILE", PROJECT_ROOT / "secrets" / "gateway_client_private.pem"))
    service_token_url: str = _env("SERVICE_TOKEN_URL", "http://gateway:8000/auth/service-token")
    report_base_url: str = _env("REPORT_URL", "http://report:8001")
    rooms_base_url: str = _env("ROOMS_URL", "http://rooms:8001")
    hours_base_url: str = _env("HOURS_URL", "http://hours:8001")
    users_file: Path = field(default_factory=lambda: _path_env(
        "LAB1_USERS_FILE", PROJECT_ROOT / "secrets" / "users.json"))
@dataclass(kw_only=True)
class ServiceSettings(CommonAuthSettings):
    pg_dsn: str = os.environ.get("PG_DSN", "").strip()
    es_url: str = _env("ES_URL", "http://127.0.0.1:9200")
    es_index: str = _env("ES_INDEX", "practice03_materials")
    neo4j_uri: str = _env("NEO4J_URI", "bolt://127.0.0.1:7687")
    neo4j_user: str = _env("NEO4J_USER", "neo4j")
    neo4j_password: str = os.environ.get("NEO4J_PASSWORD", "").strip()
    redis_host: str = _env("REDIS_HOST", "127.0.0.1")
    redis_port: int = int(_env("REDIS_PORT", "6379"))
    mongo_uri: str = _env("MONGO_URI", "mongodb://demo-mongo:27017")
    sql_dir: Path = PROJECT_ROOT / "sql"
def service_settings() -> ServiceSettings:
    return ServiceSettings()

from typing import Any
class ReportError(Exception):
    def __init__(self, status: int, message: str, details: Any = None):
        self.status = int(status)
        self.message = message
        self.details = details
        super().__init__(message)
    def body(self) -> dict:
        payload: dict[str, Any] = {"error": self.message}
        if self.details is not None:
            payload["details"] = self.details
        return payload
def install_error_handlers(app) -> None:
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from starlette.responses import JSONResponse
    @app.exception_handler(ReportError)
    async def _report_error(request, exc: ReportError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None
        return JSONResponse(status_code=exc.status, content=exc.body(), headers=headers)
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request, exc: StarletteHTTPException):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(status_code=exc.status_code,
                            content={"error": str(exc.detail)}, headers=headers)
    @app.exception_handler(RequestValidationError)
    async def _validation_error(request, exc: RequestValidationError):
        safe = [{"type": e.get("type"), "loc": e.get("loc"), "msg": e.get("msg")}
                for e in exc.errors()[:20]]
        return JSONResponse(status_code=422,
                            content={"error": "Неверные параметры запроса", "details": safe})

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
class NoStoreMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return response
def install_no_store_middleware(app) -> None:
    app.add_middleware(NoStoreMiddleware)

import os
from dataclasses import dataclass, field
from pathlib import Path
SERVICE_ISSUER = "lab1-service-issuer"
USER_ISSUER = "lab1-user-issuer"
USER_AUDIENCE = "lab1-users"
DEFAULT_SERVICE_CLIENT_ID = "generator"
def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, "")
    return value.strip() if value.strip() else default
@dataclass(kw_only=True)
class GeneratorSettings:
    service_client_id: str = field(
        default_factory=lambda: _env("SERVICE_CLIENT_ID", DEFAULT_SERVICE_CLIENT_ID))
    private_key_file: Path = field(default_factory=lambda: Path(_env(
        "SERVICE_CLIENT_PRIVATE_KEY_FILE", "/secrets/generator_client_private.pem")))
    token_url: str = field(default_factory=lambda: _env(
        "SERVICE_TOKEN_URL", "http://gateway:8000/auth/service-token"))
    request_timeout: float = field(
        default_factory=lambda: float(_env("GENERATOR_REQUEST_TIMEOUT", "10")))
    pg_host: str = field(default_factory=lambda: _env("DEMO_PG_HOST", "demo-postgres"))
    pg_port: int = field(default_factory=lambda: int(_env("DEMO_PG_PORT", "5432")))
    pg_db: str = field(default_factory=lambda: _env("DEMO_PG_DB", "lab1_demo"))
    pg_user: str = field(default_factory=lambda: _env("DEMO_PG_USER", "demo"))
    pg_password: str = field(default_factory=lambda: os.environ.get("DEMO_PG_PASSWORD", ""))
    redis_host: str = field(default_factory=lambda: _env("DEMO_REDIS_HOST", "demo-redis"))
    redis_port: int = field(default_factory=lambda: int(_env("DEMO_REDIS_PORT", "6379")))
    redis_db: int = 3
    neo4j_uri: str = field(default_factory=lambda: _env(
        "DEMO_NEO4J_URI", "bolt://demo-neo4j:7687"))
    neo4j_user: str = field(default_factory=lambda: _env("DEMO_NEO4J_USER", "neo4j"))
    neo4j_password: str = field(
        default_factory=lambda: os.environ.get("DEMO_NEO4J_PASSWORD", ""))
    es_url: str = field(default_factory=lambda: _env("DEMO_ES_URL", "http://demo-es:9200"))
    mongo_uri: str = _env("DEMO_MONGO_URI", "mongodb://demo-mongo:27017")
    gateway_internal_url: str = field(
        default_factory=lambda: _env("GATEWAY_INTERNAL_URL", "http://gateway:8000"))
    report_internal_url: str = field(
        default_factory=lambda: _env("REPORT_INTERNAL_URL", "http://report:8001"))
    es_index: str = "practice03_materials"
    es_timeout: float = field(default_factory=lambda: float(_env("DEMO_ES_TIMEOUT", "30")))
    def pg_dsn(self) -> str:
        return (f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} "
                f"user={self.pg_user} password={self.pg_password}")
    def validate_runtime(self):
        from urllib.parse import urlparse
        if self.pg_db != "lab1_demo" or self.pg_host != "demo-postgres":
            raise RuntimeError("Генератору разрешена только собственная demo-PostgreSQL")
        hosts = [self.redis_host, urlparse(self.neo4j_uri).hostname, urlparse(self.es_url).hostname]
        if hosts != ["demo-redis", "demo-neo4j", "demo-es"] or urlparse(self.mongo_uri).hostname != "demo-mongo":
            raise RuntimeError("Генератору разрешены только собственные demo-хранилища")
        if not self.pg_password or not self.neo4j_password:
            raise RuntimeError("Не заданы пароли demo-хранилищ")

import datetime as dt
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
class SearchParams(BaseModel):
    """Полнотекстовый поиск слова или фразы за указанный период."""
    model_config = ConfigDict(extra="forbid")
    term: str = Field(min_length=1, max_length=100, description="Слово или фраза для поиска в материалах лекций.", examples=["целостность", "реляционная модель"])
    date_from: dt.date = Field(description="Начало периода включительно.", examples=["2026-09-07"])
    date_to: dt.date = Field(description="Конец периода включительно.", examples=["2026-12-27"])

    @field_validator("term")
    @classmethod
    def searchable_term(cls, value):
        value = value.strip()
        if not any(char.isalnum() for char in value):
            raise ValueError("Введите слово или фразу с буквами или цифрами")
        return value

    @field_validator("date_from", "date_to", mode="before")
    @classmethod
    def iso_date(cls, value):
        if not isinstance(value, str):
            raise ValueError("Дата должна быть YYYY-MM-DD")
        try:
            parsed = dt.date.fromisoformat(value)
        except ValueError:
            raise ValueError("Дата должна быть YYYY-MM-DD") from None
        if parsed.isoformat() != value:
            raise ValueError("Дата должна быть YYYY-MM-DD")
        return value

    @model_validator(mode="after")
    def period_order(self):
        if self.date_from > self.date_to:
            raise ValueError("date_from не может быть позже date_to")
        return self

class DatasetStatePayload(BaseModel):
    """Тело POST /internal/dataset/state (только генератор; guard демо-набора)."""

    model_config = ConfigDict(extra="forbid")

    generation_id: str = Field(
        description="Идентификатор генерации (job_id генератора); CAS-ключ перехода.",
        min_length=1, max_length=64, examples=["gen-1a2b3c4d5e6f"])
    status: Literal["loading", "ready", "failed"] = Field(
        description="loading — до любой мутации хранилищ; ready — после всех проекций "
                    "и настоящей проверки отчёта; failed — при ошибке генерации.")
    details: dict | None = Field(
        default=None,
        description="Небезопасные данные не передаются: job_id/fingerprint/seed/counts.")


def gateway_settings():
    return GatewaySettings()


class RoomParams(BaseModel):
    course_code: str = Field(min_length=1, max_length=64, description="Код предмета, например demo_storage")
    semester: int = Field(ge=1, le=12, description="Номер семестра с начала обучения")
    study_year: int = Field(ge=1, le=6, description="Курс обучения, например 4 для семестра 7")
    academic_year: int = Field(ge=1900, le=2200, description="Начальный год учебного года, например 2026")

    @model_validator(mode="after")
    def check_study_year(self):
        if (self.semester + 1) // 2 != self.study_year:
            raise ValueError("Семестр не соответствует курсу обучения")
        return self


class GroupHoursParams(BaseModel):
    group_code: str = Field(min_length=1, max_length=32, description="Код группы, например ДЕМО-11-26")
