"""Пароли, USER/SERVICE JWT и private_key_jwt. Приватные ключи не передаются по сети."""
from __future__ import annotations
from .config import (USER_AUDIENCE, USER_ISSUER, USER_TOKEN_TTL_SECONDS, USER_TOKEN_USE,
    ASSERTION_AUDIENCE, ASSERTION_MAX_LIFETIME_SECONDS, CLIENT_ASSERTION_TYPE,
    SERVICE_ISSUER, SERVICE_TOKEN_MAX_TTL_SECONDS, SERVICE_TOKEN_TTL_SECONDS, SERVICE_TOKEN_USE, ReportError)
import hashlib
import hmac
import json
import secrets
import time
import uuid
from pathlib import Path
import jwt
from fastapi import Request
PBKDF2_ROUNDS = 600_000
_CLOCK_LEEWAY = 5
USER_JWT_REQUIRED_CLAIMS = ["exp", "iat", "nbf", "iss", "aud", "sub", "scope", "jti", "token_use"]
def password_hash(password: str, salt_hex: str | None = None) -> str:
    salt = salt_hex or secrets.token_bytes(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt}${digest.hex()}"
def check_password(password: str, encoded: str) -> bool:
    try:
        alg, rounds, salt, digest = encoded.split("$")
        if alg != "pbkdf2_sha256" or int(rounds) != PBKDF2_ROUNDS:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(actual, digest)
    except (ValueError, TypeError):
        return False
def load_private_key(path: Path) -> str:
    if not Path(path).is_file():
        raise RuntimeError(f"Не найден приватный ключ JWT: {path}. Запустите scripts/setup.py")
    return Path(path).read_text()
def load_public_key(path: Path) -> str:
    if not Path(path).is_file():
        raise RuntimeError(f"Не найден публичный ключ JWT: {path}. Запустите scripts/setup.py")
    return Path(path).read_text()
def issue_user_token(subject: str, scopes: list[str], private_key_pem: str,
                     lifetime_seconds: int = USER_TOKEN_TTL_SECONDS,
                     issuer: str = USER_ISSUER, audience: str = USER_AUDIENCE) -> str:
    now = int(time.time())
    claims = {
        "sub": subject,
        "scope": " ".join(scopes),
        "iss": issuer,
        "aud": audience,
        "token_use": USER_TOKEN_USE,
        "iat": now,
        "nbf": now,
        "exp": now + int(lifetime_seconds),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, private_key_pem, algorithm="RS256")
def verify_user_token(token: str, public_key_pem: str,
                      issuer: str = USER_ISSUER,
                      audience: str = USER_AUDIENCE) -> dict:
    if not isinstance(token, str) or not 8 < len(token) <= 8192:
        raise ReportError(401, "Недействительный или просроченный токен доступа")
    try:
        claims = jwt.decode(
            token, public_key_pem, algorithms=["RS256"], issuer=issuer,
            options={
                "require": USER_JWT_REQUIRED_CLAIMS,
                "verify_signature": True, "verify_exp": True, "verify_nbf": True,
                "verify_iat": True, "verify_iss": True, "verify_aud": False,
            })
    except (jwt.PyJWTError, TypeError, ValueError) as exc:
        raise ReportError(401, "Недействительный или просроченный токен доступа") from exc
    if claims.get("aud") != audience:
        raise ReportError(401, "Недействительный или просроченный токен доступа")
    if claims.get("token_use") != USER_TOKEN_USE:
        raise ReportError(401, "Недействительный или просроченный токен доступа")
    for name in ("exp", "iat", "nbf"):
        if type(claims.get(name)) is not int:
            raise ReportError(401, "Недействительный или просроченный токен доступа")
    for name in ("sub", "scope", "jti"):
        value = claims.get(name)
        if not isinstance(value, str) or not value:
            raise ReportError(401, "Недействительный или просроченный токен доступа")
    now = time.time()
    if claims["exp"] <= claims["iat"] or claims["iat"] > now + _CLOCK_LEEWAY:
        raise ReportError(401, "Недействительный или просроченный токен доступа")
    return claims
class UsersStore:
    def __init__(self, users: list[dict]):
        self._users = {u["username"]: u for u in users}
    @classmethod
    def from_file(cls, path: Path) -> "UsersStore":
        if not Path(path).is_file():
            raise RuntimeError(f"Не найден файл пользователей: {path}. Запустите scripts/setup.py")
        data = json.loads(Path(path).read_text())
        if not isinstance(data, list) or not data:
            raise RuntimeError(f"Файл пользователей {path} пуст или повреждён")
        return cls(data)
    def authenticate(self, username: str, password: str) -> dict:
        user = self._users.get(username)
        encoded = user["password_hash"] if user else _DUMMY_HASH
        password_ok = check_password(password, encoded)
        if user is None or not password_ok:
            raise ReportError(401, "Неверное имя пользователя или пароль")
        return user
_DUMMY_HASH = password_hash("timing-safe-dummy")

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
import jwt
def create_client_assertion(client_id: str, private_key_pem: str,
                            audience: str = ASSERTION_AUDIENCE,
                            lifetime_seconds: int = ASSERTION_MAX_LIFETIME_SECONDS,
                            jti: str | None = None) -> str:
    now = int(time.time())
    claims = {
        "iss": client_id,
        "sub": client_id,
        "aud": audience,
        "iat": now,
        "nbf": now,
        "exp": now + int(lifetime_seconds),
        "jti": jti or uuid.uuid4().hex,
    }
    return jwt.encode(claims, private_key_pem, algorithm="RS256")
def _require_int(claims: dict, name: str) -> int:
    value = claims.get(name)
    if type(value) is not int:
        raise ReportError(401, "Недействительный токен: неверный формат утверждений")
    return value
def _require_str(claims: dict, name: str, non_empty: bool = True) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or (non_empty and not value):
        raise ReportError(401, "Недействительный токен: неверный формат утверждений")
    return value
def _decode_strict(token: str, public_key_pem: str, *, issuer: str,
                   expected_audience: str) -> dict:
    if not isinstance(token, str) or not 8 < len(token) <= 8192:
        raise ReportError(401, "Недействительный токен")
    try:
        claims = jwt.decode(
            token, public_key_pem, algorithms=["RS256"], issuer=issuer,
            options={
                "require": ["exp", "iat", "nbf", "iss", "aud", "sub", "jti"],
                "verify_signature": True, "verify_exp": True, "verify_nbf": True,
                "verify_iat": True, "verify_iss": True, "verify_aud": False,
            })
    except ReportError:
        raise
    except (jwt.PyJWTError, TypeError, ValueError) as exc:
        raise ReportError(401, "Недействительный токен") from exc
    if claims.get("aud") != expected_audience:
        raise ReportError(401, "Недействительный токен")
    return claims
def _check_lifespan(claims: dict, max_ttl: int) -> tuple[int, int]:
    iat = _require_int(claims, "iat")
    exp = _require_int(claims, "exp")
    _require_int(claims, "nbf")
    now = time.time()
    if exp <= iat or exp - iat > max_ttl:
        raise ReportError(401, "Недействительный токен: недопустимое время жизни")
    if iat > now + 5:
        raise ReportError(401, "Недействительный токен")
    return iat, exp
def verify_service_token(token: str, public_key_pem: str, audience: str,
                         required_scope: str,
                         allowed_clients: list[str] | None = None) -> dict:
    claims = _decode_strict(token, public_key_pem, issuer=SERVICE_ISSUER,
                            expected_audience=audience)
    if claims.get("token_use") != SERVICE_TOKEN_USE:
        raise ReportError(401, "Недействительный сервисный токен")
    sub = _require_str(claims, "sub")
    client_id = _require_str(claims, "client_id")
    if sub != client_id:
        raise ReportError(401, "Недействительный сервисный токен")
    _require_str(claims, "jti")
    _require_str(claims, "scope")
    _check_lifespan(claims, SERVICE_TOKEN_MAX_TTL_SECONDS)
    if allowed_clients is not None and client_id not in allowed_clients:
        raise ReportError(401, "Сервисный токен выдан другому клиенту")
    if required_scope not in claims["scope"].split():
        raise ReportError(403, f"Недостаточно прав: требуется scope {required_scope}")
    return claims
def verify_client_assertion(assertion: str, client_id: str,
                            public_key_pem: str) -> tuple[str, int]:
    claims = _decode_strict(assertion, public_key_pem, issuer=client_id,
                            expected_audience=ASSERTION_AUDIENCE)
    sub = _require_str(claims, "sub")
    if claims.get("iss") != client_id or sub != client_id:
        raise ReportError(401, "Недействительный client assertion")
    jti = _require_str(claims, "jti")
    _, exp = _check_lifespan(claims, ASSERTION_MAX_LIFETIME_SECONDS)
    return jti, exp
class ClientRegistry:
    def __init__(self, clients: dict[str, dict]):
        self._clients = clients
    @classmethod
    def from_file(cls, path: Path) -> "ClientRegistry":
        if not Path(path).is_file():
            raise RuntimeError(f"Не найден реестр клиентов: {path}. Запустите scripts/setup.py")
        data = json.loads(Path(path).read_text())
        if not isinstance(data, dict) or not data:
            raise RuntimeError(f"Реестр клиентов {path} пуст или повреждён")
        return cls(data)
    def public_key(self, client_id: str) -> str | None:
        record = self._clients.get(client_id)
        if not record or "public_key" not in record:
            return None
        return record["public_key"]
    def allowed_scopes(self, client_id: str, audience: str) -> set[str] | None:
        record = self._clients.get(client_id)
        if not record:
            return None
        grants = record.get("grants") or {}
        if audience not in grants:
            return None
        return set(grants[audience])
class ReplayStore:
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
                "CREATE TABLE IF NOT EXISTS used_assertions ("
                " jti TEXT PRIMARY KEY,"
                " client_id TEXT NOT NULL,"
                " expires_at INTEGER NOT NULL)")
    def check_and_remember(self, jti: str, client_id: str, expires_at: int) -> bool:
        now = int(time.time())
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM used_assertions WHERE expires_at < ?", (now - 300,))
                conn.execute(
                    "INSERT INTO used_assertions (jti, client_id, expires_at) VALUES (?,?,?)",
                    (jti, client_id, int(expires_at)))
            return True
        except sqlite3.IntegrityError:
            return False
def issue_service_token(client_id: str, audience: str, scopes: list[str],
                        issuer_private_key_pem: str, ttl_seconds: int = SERVICE_TOKEN_TTL_SECONDS,
                        issuer: str = SERVICE_ISSUER,
                        jti: str | None = None) -> str:
    ttl = int(ttl_seconds)
    if not 1 <= ttl <= SERVICE_TOKEN_MAX_TTL_SECONDS:
        raise ValueError(f"TTL сервисного токена должен быть 1.."
                         f"{SERVICE_TOKEN_MAX_TTL_SECONDS} секунд, получено {ttl}")
    now = int(time.time())
    claims = {
        "sub": client_id,
        "client_id": client_id,
        "token_use": SERVICE_TOKEN_USE,
        "aud": audience,
        "scope": " ".join(scopes),
        "iss": issuer,
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
        "jti": jti or uuid.uuid4().hex,
    }
    return jwt.encode(claims, issuer_private_key_pem, algorithm="RS256")
class ServiceTokenClient:
    def __init__(self, client_id: str, private_key_file: Path | str, token_url: str,
                 timeout: float = 10.0, http_client=None):
        self.client_id = client_id
        self.token_url = token_url
        self.timeout = timeout
        path = Path(private_key_file)
        if not path.is_file():
            raise RuntimeError(
                f"Не найден приватный identity-ключ клиента {client_id}: {path}. "
                "Запустите scripts/setup.py")
        self._private_key = path.read_text()
        self._http = http_client
        self._cache: dict[tuple[str, str], tuple[str, float]] = {}
        self._lock = threading.Lock()
    def get_token(self, audience: str, scope: str) -> str:
        key = (audience, scope)
        now = time.time()
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[1] > now:
                return cached[0]
        assertion = create_client_assertion(self.client_id, self._private_key)
        try:
            import httpx
            client = self._http or httpx
            response = client.post(
                self.token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_assertion_type": CLIENT_ASSERTION_TYPE,
                    "client_assertion": assertion,
                    "audience": audience,
                    "scope": scope,
                },
                timeout=self.timeout)
        except Exception as exc:
            raise ReportError(503, "Не удалось получить сервисный токен") from exc
        if response.status_code != 200:
            raise ReportError(503, "Не удалось получить сервисный токен")
        try:
            payload = response.json()
            token = payload["access_token"]
            expires_in = int(payload["expires_in"])
        except (ValueError, KeyError, TypeError) as exc:
            raise ReportError(503, "Некорректный ответ сервиса токенов") from exc
        with self._lock:
            self._cache[key] = (token, time.time() + max(expires_in - 5, 1))
        return token
