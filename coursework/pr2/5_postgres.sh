#!/usr/bin/env bash
cd "$(dirname "$0")/.."
# ПР2, PostgreSQL: посещение лекций с партиционированием по неделе.
# Отметки посещения генерируются случайно.

docker compose exec -T postgres psql -U user -d main_db -v ON_ERROR_STOP=1 -e <<'SQL'
\echo '\n===== 1. Создание хранилища (схема pr2, таблица attendance с партициями по неделе) ====='
DROP SCHEMA IF EXISTS pr2 CASCADE;
CREATE SCHEMA pr2;
SET search_path = pr2;

CREATE TABLE students (
    record_book text PRIMARY KEY,
    full_name   text NOT NULL,
    group_name  text NOT NULL
);

CREATE TABLE courses (
    code  text PRIMARY KEY,
    title text NOT NULL,
    kind  text NOT NULL CHECK (kind IN ('обязательный', 'по выбору'))
);

-- Ключ партиционирования (week_start) обязан входить в первичный ключ
CREATE TABLE attendance (
    id           bigint GENERATED ALWAYS AS IDENTITY,
    record_book  text NOT NULL REFERENCES students,
    course_code  text NOT NULL REFERENCES courses,
    lecture_date date NOT NULL,
    week_start   date NOT NULL,
    is_present   boolean NOT NULL,
    PRIMARY KEY (id, week_start),
    UNIQUE (record_book, course_code, lecture_date, week_start)
) PARTITION BY RANGE (week_start);

-- По одной партиции на каждую учебную неделю (4 недели с 1 сентября 2025)
DO $$
DECLARE w date;
BEGIN
  FOR w IN SELECT generate_series(date '2025-09-01', date '2025-09-22', interval '1 week')::date LOOP
    EXECUTE format('CREATE TABLE attendance_w%s PARTITION OF attendance FOR VALUES FROM (%L) TO (%L)',
                   to_char(w, 'YYYYMMDD'), w, w + 7);
  END LOOP;
END $$;
CREATE TABLE attendance_default PARTITION OF attendance DEFAULT;

\d+ attendance

\echo '\n===== 2. Добавление данных ====='
INSERT INTO students VALUES
  ('ПР2-0001', 'Студент 01',     'ПР2-ДЕМО-01'),
  ('ПР2-0002', 'Студент 02',      'ПР2-ДЕМО-01'),
  ('ПР2-0003', 'Студент 03',     'ПР2-ДЕМО-01'),
  ('ПР2-0004', 'Студент 04',    'ПР2-ДЕМО-01'),
  ('ПР2-0005', 'Студент 05',        'ПР2-ДЕМО-01'),
  ('ПР2-0006', 'Студент 06',   'ПР2-ДЕМО-01'),
  ('ПР2-0007', 'Студент 07', 'ПР2-ДЕМО-01'),
  ('ПР2-0008', 'Студент 08',    'ПР2-ДЕМО-01');

INSERT INTO courses VALUES
  ('ARCH', 'Проектирование архитектуры ПО', 'обязательный'),
  ('ML',   'Машинное обучение',             'обязательный'),
  ('TEST', 'Тестирование ПО',               'обязательный');

-- Лекции каждого курса раз в неделю (пн/ср/пт), явка — случайно с вероятностью 80%
INSERT INTO attendance (record_book, course_code, lecture_date, week_start, is_present)
SELECT s.record_book, c.code, d.lecture_date,
       date_trunc('week', d.lecture_date)::date,
       random() < 0.8
FROM students s
CROSS JOIN courses c
CROSS JOIN LATERAL (
  SELECT g.w::date + CASE c.code WHEN 'ARCH' THEN 0 WHEN 'ML' THEN 2 ELSE 4 END AS lecture_date
  FROM generate_series(date '2025-09-01', date '2025-09-22', interval '1 week') AS g(w)
) d;

SELECT tableoid::regclass AS partition, count(*) AS rows, sum(is_present::int) AS present
FROM attendance GROUP BY 1 ORDER BY 1;

\echo '\n===== 3. Чтение по ключу ====='
SELECT * FROM students WHERE record_book = 'ПР2-0003';
-- Условие по week_start: планировщик читает только одну партицию (partition pruning)
EXPLAIN (COSTS OFF)
SELECT * FROM attendance WHERE record_book = 'ПР2-0003' AND week_start = '2025-09-08';
SELECT a.lecture_date, c.title, a.is_present
FROM attendance a JOIN courses c ON c.code = a.course_code
WHERE a.record_book = 'ПР2-0003' AND a.week_start = '2025-09-08'
ORDER BY a.lecture_date;

\echo '\n===== 4. Изменение и сохранение ====='
BEGIN;
UPDATE attendance SET is_present = true
WHERE record_book = 'ПР2-0003' AND week_start = '2025-09-08'
RETURNING record_book, course_code, lecture_date, is_present;
UPDATE students SET full_name = 'Студент 03 (староста)' WHERE record_book = 'ПР2-0003'
RETURNING *;
COMMIT;

\echo '\n===== 5. Удаление записей ====='
DELETE FROM attendance WHERE record_book = 'ПР2-0008';
DELETE FROM students WHERE record_book = 'ПР2-0008' RETURNING *;
-- Удаление целой недели — мгновенное отсоединение партиции вместо DELETE
ALTER TABLE attendance DETACH PARTITION attendance_w20250922;
DROP TABLE attendance_w20250922;
SELECT tableoid::regclass AS partition, count(*) FROM attendance GROUP BY 1 ORDER BY 1;

\echo '\n===== 6. Удаление хранилища ====='
DROP SCHEMA pr2 CASCADE;
SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'pr2';
SQL
