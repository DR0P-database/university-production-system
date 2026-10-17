from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from pwdlib import PasswordHash
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    jwt_secret: SecretStr = Field(min_length=32)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_issuer: str = "university-gateway"
    jwt_audience: str = "university-api"
    jwt_access_token_expire_minutes: int = Field(default=30, ge=1, le=1440)
    jwt_clock_skew_seconds: int = Field(default=5, ge=0, le=60)
    auth_users_file: Path = (
        Path(__file__).resolve().parents[1] / "config/dev-users.json"
    )


class UserAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1)
    password_hash: str = Field(min_length=1)
    active: bool = True


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=200, default="api-user")
    password: str = Field(min_length=1, max_length=500, default="api-password")


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


settings = AuthSettings()  # type: ignore[call-arg]  # populated from environment
password_hash = PasswordHash.recommended()
bearer_scheme = HTTPBearer(auto_error=False, scheme_name="BearerAuth")

# A valid hash is checked even for an unknown username to reduce timing differences.
DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$4uj3uTL/Y0ZNkq7Li+kFng$"
    "k8atvchowiSqe6Gs4gNa5ixOS0Bz9OlGLeS+ef8wt14"
)


def auth_error(code: str, message: str) -> HTTPException:
    return HTTPException(
        401,
        {"code": code, "message": message, "details": {}},
        headers={"WWW-Authenticate": "Bearer"},
    )


@lru_cache
def get_accounts() -> dict[str, UserAccount]:
    try:
        raw_accounts = json.loads(settings.auth_users_file.read_text())
        accounts = [UserAccount.model_validate(item) for item in raw_accounts]
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"Unable to load auth users from {settings.auth_users_file}"
        ) from exc
    if len({account.username for account in accounts}) != len(accounts):
        raise RuntimeError("Auth user names must be unique")
    return {account.username: account for account in accounts}


def authenticate_account(username: str, password: str) -> UserAccount:
    account = get_accounts().get(username)
    candidate_hash = account.password_hash if account else DUMMY_PASSWORD_HASH
    valid_password = password_hash.verify(password, candidate_hash)
    if account is None or not valid_password or not account.active:
        raise auth_error("INVALID_CREDENTIALS", "Incorrect username or password")
    return account


def create_access_token(account: UserAccount) -> TokenResponse:
    now = datetime.now(UTC)
    lifetime = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {
        "sub": account.username,
        "type": "access",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "nbf": now,
        "exp": now + lifetime,
        "jti": str(uuid4()),
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return TokenResponse(access_token=token, expires_in=int(lifetime.total_seconds()))


def decode_access_token(token: str) -> str:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            leeway=settings.jwt_clock_skew_seconds,
            options={
                "require": ["sub", "type", "iss", "aud", "iat", "nbf", "exp", "jti"]
            },
        )
        if payload["type"] != "access" or not isinstance(payload["sub"], str):
            raise InvalidTokenError("Unexpected token payload")
        return payload["sub"]
    except ExpiredSignatureError as exc:
        raise auth_error("TOKEN_EXPIRED", "Access token has expired") from exc
    except (InvalidTokenError, KeyError, ValueError) as exc:
        raise auth_error("INVALID_TOKEN", "Access token is invalid") from exc


async def require_access_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Security(bearer_scheme)
    ],
) -> None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise auth_error("UNAUTHORIZED", "Bearer token is required")
    decode_access_token(credentials.credentials)
