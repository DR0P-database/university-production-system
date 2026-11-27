"""Подготовка ключей/паролей и проверка запуска стенда."""
from __future__ import annotations
import argparse
import json
import secrets as pysecrets
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from app.config import SCOPE_READ, SCOPE_VERIFY, SCOPE_DATASET_STATE_READ, SCOPE_DATASET_STATE_UPDATE
from app.auth import password_hash
from app.auth import ReplayStore
CLIENT_GRANTS = {
    "gateway": {audience: [SCOPE_READ] for audience in ("report-service", "rooms-service", "hours-service")},
    "generator": {"gateway-internal": [SCOPE_DATASET_STATE_READ, SCOPE_DATASET_STATE_UPDATE],
                  "report-service": [SCOPE_VERIFY]},
}
DEMO_USERS = [
    {"username": "admin", "scopes": ["lab1:read"], "full_name": "Администратор"},
    {"username": "analyst", "scopes": ["lab1:read"], "full_name": "Аналитик"},
    {"username": "guest", "scopes": ["profile:read"], "full_name": "Гость"},
]
def _write(path: Path, data: str | bytes, mode: int) -> None:
    if isinstance(data, str):
        data = data.encode()
    path.write_bytes(data)
    path.chmod(mode)
def _generate_rsa(key_size: int):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return private_pem, public_pem
def generate_secrets(out_dir: Path, force: bool = False, key_size: int = 3072) -> dict:
    if key_size < 2048:
        raise SystemExit("Ключи RSA меньше 2048 бит не допускаются")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir.chmod(0o700)
    existing = sorted(p.name for p in out_dir.glob("*"))
    if existing and not force:
        raise SystemExit(
            f"Каталог {out_dir} не пуст ({', '.join(existing[:5])}...). "
            "Используйте --force для перегенерации (старые токены/пароли станут невалидными).")
    created: list[str] = []
    def write_pair(name: str) -> tuple[str, str]:
        private, public = _generate_rsa(key_size)
        _write(out_dir / f"{name}_private.pem", private, 0o600)
        _write(out_dir / f"{name}_public.pem", public, 0o644)
        created.extend([f"{name}_private.pem", f"{name}_public.pem"])
        return private, public
    write_pair("user")
    write_pair("service_issuer")
    client_publics: dict[str, str] = {}
    for client_id in CLIENT_GRANTS:
        _, public = write_pair(f"{client_id}_client")
        client_publics[client_id] = public
    registry = {
        client_id: {
            "public_key": client_publics[client_id],
            "grants": grants,
        }
        for client_id, grants in CLIENT_GRANTS.items()
    }
    _write(out_dir / "clients.json",
           json.dumps(registry, ensure_ascii=False, indent=2) + "\n", 0o600)
    created.append("clients.json")
    _write_users(out_dir)
    created.extend(["users.json", "demo-credentials.txt"])
    ReplayStore(out_dir / "replay.sqlite")
    created.append("replay.sqlite")
    return {
        "secrets_dir": str(out_dir),
        "key_size": key_size,
        "files": created,
        "users": [spec["username"] for spec in DEMO_USERS],
        "clients": sorted(CLIENT_GRANTS),
    }
def _write_users(out_dir: Path) -> None:
    credentials: list[dict] = []
    for spec in DEMO_USERS:
        password = pysecrets.token_urlsafe(14)
        credentials.append({
            "username": spec["username"],
            "password": password,
            "record": {
                "username": spec["username"],
                "password_hash": password_hash(password),
                "scopes": spec["scopes"],
                "full_name": spec["full_name"],
            },
        })
    _write(out_dir / "users.json",
           json.dumps([c["record"] for c in credentials], ensure_ascii=False, indent=2) + "\n",
           0o600)
    lines = ["# Доступы локального стенда ЛР1 (сгенерированы scripts/setup.py)",
             "# Файл секретный (0600), не коммитится. Swagger: Authorize -> username/password.",
             "# Поля client_id/client_secret в Swagger оставляйте пустыми.", ""]
    for c in credentials:
        lines.append(f"{c['username']}: {c['password']}  # scopes: "
                     f"{' '.join(c['record']['scopes'])}")
    _write(out_dir / "demo-credentials.txt", "\n".join(lines) + "\n", 0o600)
def _rebuild_clients_registry(out_dir: Path) -> bool:
    registry: dict[str, dict] = {}
    for client_id, grants in CLIENT_GRANTS.items():
        public_file = out_dir / f"{client_id}_client_public.pem"
        if not public_file.is_file():
            return False
        registry[client_id] = {"public_key": public_file.read_text(),
                               "grants": grants}
    try:
        current = json.loads((out_dir / "clients.json").read_text())
    except (ValueError, TypeError):
        current = None
    if current == registry:
        return False
    _write(out_dir / "clients.json",
           json.dumps(registry, ensure_ascii=False, indent=2) + "\n", 0o600)
    return True
def ensure_secrets(out_dir: Path, key_size: int = 3072) -> dict:
    out_dir = Path(out_dir)
    required_keys = ["user_private.pem", "service_issuer_private.pem",
                     "clients.json", "users.json"]
    missing = [name for name in required_keys if not (out_dir / name).is_file()]
    if any(name != "users.json" for name in missing):
        return generate_secrets(out_dir, force=bool(list(out_dir.glob("*"))), key_size=key_size)
    rebuilt_clients = False
    if not missing:
        try:
            rebuilt_clients = _rebuild_clients_registry(out_dir)
        except OSError:
            rebuilt_clients = False
    if "users.json" in missing:
        _write_users(out_dir)
        ReplayStore(out_dir / "replay.sqlite")
        return {"secrets_dir": str(out_dir), "files": ["users.json", "demo-credentials.txt"],
                "users": [spec["username"] for spec in DEMO_USERS],
                "clients": sorted(CLIENT_GRANTS), "regenerated": "users_only"}
    try:
        users = json.loads((out_dir / "users.json").read_text())
        if not any(u.get("username") == "admin" for u in users):
            _write_users(out_dir)
            return {"secrets_dir": str(out_dir),
                    "files": ["users.json", "demo-credentials.txt"],
                    "users": [spec["username"] for spec in DEMO_USERS],
                    "clients": sorted(CLIENT_GRANTS), "regenerated": "users_only"}
    except (ValueError, TypeError):
        _write_users(out_dir)
        return {"secrets_dir": str(out_dir), "files": ["users.json", "demo-credentials.txt"],
                "users": [spec["username"] for spec in DEMO_USERS],
                "clients": sorted(CLIENT_GRANTS), "regenerated": "users_only"}
    if rebuilt_clients:
        return {"secrets_dir": str(out_dir), "files": ["clients.json"],
                "users": [u["username"] for u in users],
                "clients": sorted(CLIENT_GRANTS), "regenerated": "clients_only"}
    return {"secrets_dir": str(out_dir), "files": [], "users": [u["username"] for u in users],
            "clients": sorted(CLIENT_GRANTS), "regenerated": None}

import os
import secrets
import subprocess
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
ENV_FILE = PROJECT_ROOT / ".env"
GATEWAY_URL = 'http://127.0.0.1:' + os.environ.get('LAB_GATEWAY_PORT', '8000')
ENV_KEYS = (
    "DEMO_POSTGRES_ADMIN_PASSWORD",
    "DEMO_GENERATOR_DB_PASSWORD",
    "DEMO_REPORT_DB_PASSWORD",
    "DEMO_NEO4J_PASSWORD",
)
def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values
def ensure_env() -> list[str]:
    current = read_env(ENV_FILE)
    created = []
    for key in ENV_KEYS:
        if not current.get(key):
            current[key] = secrets.token_urlsafe(20)
            created.append(key)
    if created:
        lines = ["# Локальные пароли demo-стенда ЛР1 (bootstrap). 0600, НЕ коммитится."]
        lines += [f"{key}={current[key]}" for key in ENV_KEYS]
        ENV_FILE.write_text("\n".join(lines) + "\n")
        os.chmod(ENV_FILE, 0o600)
    return created
def main() -> int:
    created_env = ensure_env()
    summary = ensure_secrets(PROJECT_ROOT / "secrets")
    print("Bootstrap ЛР1 (идемпотентно):")
    if created_env:
        print(f"  .env: созданы пароли {', '.join(created_env)} (значения не печатаются)")
    else:
        print("  .env: уже на месте — пароли не изменены")
    if summary.get("regenerated") == "users_only":
        print("  secrets/: пересозданы только пользователи; JWT-ключи не тронуты")
    elif summary.get("regenerated") == "clients_only":
        print("  secrets/: пересобран clients.json (grants по контракту); "
              "ключи и пользователи не тронуты")
    elif not summary["files"]:
        print("  secrets/: уже на месте — ничего не изменено")
    else:
        print("  secrets/: сгенерированы (JWT-ключи, реестр клиентов, пользователи)")
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(PROJECT_ROOT / "docker-compose.yml"),
             "config", "-q"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            print("  docker compose config: OK")
        else:
            print("  docker compose config: ОШИБКА (см. ниже)")
            print("  " + result.stderr.strip().replace("\n", "\n  "))
            return 1
    except FileNotFoundError:
        print("  docker compose недоступен — проверьте Docker Desktop (не критично)")
    except subprocess.TimeoutExpired:
        print("  docker compose config: таймаут — проверьте Docker вручную")
    print(f"\nSwagger {GATEWAY_URL}/docs")
    print("Учётные данные пользователей: secrets/demo-credentials.txt (0600)")
    return 0


def check_report():
    import time
    import httpx
    password = next(x for x in (PROJECT_ROOT / "secrets/demo-credentials.txt").read_text().splitlines() if x.startswith("admin:")).split(":", 1)[1].strip().split()[0]
    reports = (
        ("attendance", {"term": "целостность", "date_from": "2026-09-07", "date_to": "2026-12-27"}),
        ("classroom-capacity", {"course_code": "demo_storage", "semester": 7,
                                "study_year": 4, "academic_year": 2026}),
        ("group-lecture-hours", {"group_code": "ДЕМО-11-26"}),
    )
    with httpx.Client(base_url=GATEWAY_URL, timeout=30) as http:
        for _ in range(120):
            try:
                login = http.post("/auth/token", data={"username": "admin", "password": password})
                login.raise_for_status()
                http.headers["Authorization"] = "Bearer " + login.json()["access_token"]
                first_path, first_params = reports[0]
                response = http.get(f"/api/v1/reports/{first_path}", params=first_params)
                if response.status_code == 200 and response.json()["results"]:
                    print(f"ЛР №1: HTTP 200, строк: {len(response.json()['results'])}")
                    for index, (path, params) in enumerate(reports[1:], start=2):
                        result = http.get(f"/api/v1/reports/{path}", params=params)
                        if not result.is_success or not result.json().get("results"):
                            print(f"ЛР №{index}: HTTP {result.status_code}, {result.text[:300]}")
                            return 1
                        print(f"ЛР №{index}: HTTP 200, строк: {len(result.json()['results'])}")
                    print(f"Swagger {GATEWAY_URL}/docs")
                    return 0
            except httpx.HTTPError:
                pass
            time.sleep(2)
    print("Данные не готовы; проверьте docker compose logs generator")
    return 1


if __name__ == "__main__":
    raise SystemExit(check_report() if "--check" in sys.argv else main())
