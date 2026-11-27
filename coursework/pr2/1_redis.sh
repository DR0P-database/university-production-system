#!/usr/bin/env bash
cd "$(dirname "$0")/.."
# ПР2, Redis: список студентов, ключ — номер зачётной книжки.
# Хранилище — отдельная логическая БД Redis №1, запись — hash student:<зачётка>.

r() { echo "redis> $*"; docker compose exec -T redis redis-cli -a password --no-auth-warning -n 1 "$@"; }
step() { printf '\n===== %s =====\n' "$1"; }

step "1. Создание хранилища (логическая БД 1, проверяем что пустая)"
r DBSIZE

step "2. Добавление данных"
r HSET student:ПР2-0001 full_name "Студент 01"      group "ПР2-ДЕМО-01" birth_date 2004-03-15 email student01@example.test
r HSET student:ПР2-0002 full_name "Студент 02"       group "ПР2-ДЕМО-01" birth_date 2004-07-02 email student02@example.test
r HSET student:ПР2-0003 full_name "Студент 03"      group "ПР2-ДЕМО-01" birth_date 2003-11-21 email student03@example.test
r HSET student:ПР2-0004 full_name "Студент 04"     group "ПР2-ДЕМО-01" birth_date 2004-01-09 email student04@example.test
r HSET student:ПР2-0005 full_name "Студент 05"         group "ПР2-ДЕМО-01" birth_date 2004-05-30 email student05@example.test
r HSET student:ПР2-0006 full_name "Студент 06"    group "ПР2-ДЕМО-01" birth_date 2004-09-12 email student06@example.test
r HSET student:ПР2-0007 full_name "Студент 07"  group "ПР2-ДЕМО-01" birth_date 2003-12-04 email student07@example.test
r HSET student:ПР2-0008 full_name "Студент 08"     group "ПР2-ДЕМО-01" birth_date 2004-02-18 email student08@example.test
r DBSIZE
r KEYS 'student:*'

step "3. Чтение по ключу (номер зачётки ПР2-0003)"
r HGETALL student:ПР2-0003
r HGET student:ПР2-0003 full_name

step "4. Изменение и сохранение"
r HSET student:ПР2-0003 email student03.updated@example.test phone "+1-202-555-0103"
r HGETALL student:ПР2-0003
r SAVE

step "5. Удаление записи"
r DEL student:ПР2-0008
r EXISTS student:ПР2-0008
r DBSIZE

step "6. Удаление хранилища"
r FLUSHDB
r DBSIZE
