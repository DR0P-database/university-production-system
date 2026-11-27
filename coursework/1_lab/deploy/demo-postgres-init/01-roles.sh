#!/bin/bash
# Генератор владеет demo-БД; сервис отчёта имеет только SELECT.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
CREATE ROLE demo LOGIN PASSWORD '${DEMO_GENERATOR_DB_PASSWORD}' NOCREATEDB;
CREATE ROLE report_reader LOGIN PASSWORD '${DEMO_REPORT_DB_PASSWORD}';
ALTER DATABASE lab1_demo OWNER TO demo;

-- Всё, что генератор создаст позже (схема practice03, метаданные готовности),
-- автоматически читаемо сервису отчёта — default privileges роли demo.
ALTER DEFAULT PRIVILEGES FOR ROLE demo GRANT SELECT ON TABLES TO report_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE demo GRANT USAGE ON SCHEMAS TO report_reader;
EOSQL

echo "Роли demo/report_reader созданы; default privileges для report_reader настроены."
