#!/bin/bash
# Остановка демо-стенда ЛР1. Томованный данные сохраняются.
# Полная очистка (в т.ч. demo-данные): scripts/stop.sh --volumes
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "${1:-}" = "--volumes" ]; then
    echo "Остановка стенда и УДАЛЕНИЕ томов с demo-данными (секреты в secrets/ остаются)..."
    docker compose down --volumes
else
    docker compose down
    echo "Стенд остановлен (тома данных сохранены; полная очистка: scripts/stop.sh --volumes)"
fi
