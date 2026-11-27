#!/bin/bash
# Запуск стенда; генератор автоматически загружает данные только при отсутствии ready.
set -euo pipefail
cd "$(dirname "$0")/.."
port="${LAB_GATEWAY_PORT:-8000}"

PY=".venv/bin/python"; [ -x "$PY" ] || PY="python3"

echo "== Bootstrap (идемпотентно; секреты не печатаются) =="
"$PY" scripts/setup.py

echo
echo "== Запуск Gateway, трёх сервисов отчётов, загрузчика и пяти СУБД =="
docker compose up -d --build --remove-orphans

echo
echo "== Ожидание gateway (liveness /health) =="
ready=""
for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:$port/health" >/dev/null 2>&1; then ready=1; break; fi
    sleep 2
done
if [ -z "$ready" ]; then
    echo "gateway не ответил за 120 секунд; смотрите: docker compose ps, docker compose logs gateway"
    exit 1
fi
echo "gateway доступен."

echo "Ожидание первоначальной загрузки данных и проверка трёх отчётов..."
"$PY" scripts/setup.py --check
