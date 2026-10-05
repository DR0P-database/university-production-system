#!/usr/bin/env sh
set -eu

create_service_database() {
  database_name="$1"
  role_name="$2"
  role_password="$3"

  psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 \
    --set database_name="$database_name" \
    --set role_name="$role_name" \
    --set role_password="$role_password" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'role_name', :'role_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'role_name')
\gexec

SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'role_name', :'role_password')
\gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'database_name', :'role_name')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'database_name')
\gexec

SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'database_name')
\gexec
SQL
}

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database())
\gexec
SQL

create_service_database "$ACADEMIC_DB_NAME" "$ACADEMIC_DB_USER" "$ACADEMIC_DB_PASSWORD"
create_service_database "$STUDENT_DB_NAME" "$STUDENT_DB_USER" "$STUDENT_DB_PASSWORD"
create_service_database "$SCHEDULE_DB_NAME" "$SCHEDULE_DB_USER" "$SCHEDULE_DB_PASSWORD"
create_service_database "$ATTENDANCE_DB_NAME" "$ATTENDANCE_DB_USER" "$ATTENDANCE_DB_PASSWORD"
