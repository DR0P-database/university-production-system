-- baseline.sql — базовая (неоптимизированная) версия отчёта ЛР1.
--
-- Тот же контракт четырёх источников, что у optimized.sql (результаты обязаны
-- совпадать при одинаковых входах):
--   %(params)s          — jsonb: term, date_from, date_to, department_id, group_id,
--                         match_mode, missing_policy, include_trace, limit
--   %(materials)s       — jsonb: находки Elasticsearch [{"id":..,"lecture_id":..,"course_id":..}]
--   %(graph_schedule)s  — jsonb: расписание из графа Neo4j (см. optimized.sql)
--   %(graph_members)s   — jsonb: состав ожидаемых участников из графа
--
-- Отличия от optimized.sql — только производительность (не семантика):
--   1) числитель/знаменатель считаются «в лоб»: широкий набор ожиданий
--      (участник графа × занятие) LEFT JOIN к attendance по каждой паре,
--      jsonb_agg(sessions) строится для ВСЕХ кандидатов до LIMIT;
--   2) без LATERAL/OFFSET 0-барьера, MATERIALIZED actual_marks и второй
--      проходки winner_sessions.
--
-- Инварианты корректности (неизменны):
--   * знаменатель — подходящее расписание (графовое множество проведённых
--     лекций найденных тем + авторитетный фильтр кафедры PG), а не существующие
--     строки посещений: нулевая посещаемость не теряется (LEFT JOIN);
--   * студент ожидается только как участник графа своей группы и с даты
--     зачисления (enrollment_date — авторитет PG);
--   * дубли материалов одной лекции не умножают посещаемость (DISTINCT lecture_id),
--     а занятия одной темы с разными датами учитываются раздельно;
--   * «нет отметки» ≠ «отсутствовал»: unknown_count>0 делает точный рейтинг
--     невозможным;
--   * сортировка по НЕОКРУГЛЁННОМУ проценту, устойчивый tie-break по зачётке
--     (COLLATE "C") и id; LIMIT применяется после расчёта по всем кандидатам;
--   * границы ключа партиционирования attendance (week_start_date) заданы
--     константами периода для отсечения партиций (partition pruning);
--   * карточка победителя не читается: SQL возвращает student_pg для сверки
--     с Redis-карточкой (сам ответ собирает приложение).
WITH
params AS (
  SELECT j,
         (j->>'date_from')::date AS d1,
         (j->>'date_to')::date AS d2,
         (j->>'department_id')::int AS department_id,
         (j->>'group_id')::int AS group_id,
         (j->>'limit')::int AS row_limit,
         coalesce((j->>'include_trace')::boolean, false) AS include_trace
  FROM (SELECT %(params)s::jsonb AS j) p
),
hits AS (
  SELECT * FROM jsonb_to_recordset(%(materials)s::jsonb)
    AS h(id integer, lecture_id integer, course_id integer)
),
-- Материал считается действительным, только если его связи совпадают с PostgreSQL:
-- material.id → lecture.id → course.id (source of truth). Расхождения → unlinked_materials.
valid_hits AS (
  SELECT h.id, h.lecture_id
  FROM hits h
  JOIN practice03.lecture_materials m ON m.id = h.id AND m.lecture_id = h.lecture_id
  JOIN practice03.lectures l ON l.id = m.lecture_id AND l.course_id = h.course_id
),
-- Дедупликация тем: несколько материалов одной лекции дают одну тему.
matched_lectures AS (
  SELECT DISTINCT lecture_id FROM valid_hits
),
graph_schedule AS (
  SELECT * FROM jsonb_to_recordset(%(graph_schedule)s::jsonb)
    AS g(schedule_id integer, lecture_id integer, course_id integer,
         group_id integer, scheduled_date date, status text)
),
graph_members AS (
  SELECT * FROM jsonb_to_recordset(%(graph_members)s::jsonb)
    AS m(student_id integer, group_id integer, record_book text)
),
-- Каноническое расписание PG с ограничениями, проверяемыми графом.
canonical_schedule AS (
  SELECT sc.id AS schedule_id, sc.lecture_id, l.course_id, sc.group_id,
         sc.scheduled_date, 'completed'::text AS status
  FROM practice03.schedule sc
  JOIN matched_lectures ml ON ml.lecture_id = sc.lecture_id
  JOIN practice03.lectures l ON l.id = sc.lecture_id
  JOIN practice03.courses c ON c.id = l.course_id
  CROSS JOIN params p
  WHERE l.lesson_type = 'lecture'
    AND sc.status = 'completed'
    AND sc.scheduled_date BETWEEN p.d1 AND p.d2
    AND (p.group_id IS NULL OR sc.group_id = p.group_id)
),
graph_missing_schedules AS (
  SELECT c.schedule_id FROM canonical_schedule c
  LEFT JOIN graph_schedule g ON g.schedule_id = c.schedule_id
  WHERE g.schedule_id IS NULL
),
graph_extra_schedules AS (
  SELECT g.schedule_id FROM graph_schedule g
  LEFT JOIN canonical_schedule c ON c.schedule_id = g.schedule_id
  WHERE c.schedule_id IS NULL
),
graph_wrong_schedules AS (
  SELECT c.schedule_id
  FROM canonical_schedule c
  JOIN graph_schedule g ON g.schedule_id = c.schedule_id
  WHERE g.lecture_id IS DISTINCT FROM c.lecture_id
     OR g.course_id IS DISTINCT FROM c.course_id
     OR g.group_id IS DISTINCT FROM c.group_id
     OR g.scheduled_date IS DISTINCT FROM c.scheduled_date
     OR g.status IS DISTINCT FROM c.status
),
-- Выбранное расписание = переданный графовый набор + авторитетный фильтр кафедры PG.
selected_schedule AS (
  SELECT sc.*, g.course_id, l.title AS lecture_title, c.title AS course_title
  FROM graph_schedule g
  JOIN practice03.schedule sc ON sc.id = g.schedule_id
  JOIN practice03.lectures l ON l.id = g.lecture_id
  JOIN practice03.courses c ON c.id = g.course_id
  JOIN practice03.study_groups grp ON grp.id = sc.group_id
  CROSS JOIN params p
  WHERE (p.department_id IS NULL OR grp.department_id = p.department_id)
),
canonical_members AS (
  SELECT st.id AS student_id, st.group_id, st.record_book
  FROM practice03.students st
  WHERE st.group_id IN (SELECT group_id FROM graph_schedule)
),
graph_missing_members AS (
  SELECT c.student_id FROM canonical_members c
  LEFT JOIN graph_members g ON g.student_id = c.student_id AND g.group_id = c.group_id
  WHERE g.student_id IS NULL
),
graph_extra_members AS (
  SELECT g.student_id FROM graph_members g
  LEFT JOIN canonical_members c ON c.student_id = g.student_id AND c.group_id = g.group_id
  WHERE c.student_id IS NULL
),
graph_wrong_members AS (
  SELECT c.student_id
  FROM canonical_members c
  JOIN graph_members g ON g.student_id = c.student_id
  WHERE g.group_id IS DISTINCT FROM c.group_id
     OR g.record_book IS DISTINCT FROM c.record_book
),
-- Ожидания: участник графа на каждом занятии своей группы, начиная с даты
-- зачисления (enrollment_date — авторитет PG).
expected AS (
  SELECT gm.student_id, sc.*
  FROM selected_schedule sc
  JOIN graph_members gm ON gm.group_id = sc.group_id
  JOIN practice03.students st ON st.id = gm.student_id
  WHERE st.enrollment_date <= sc.scheduled_date
),
-- Отметки: LEFT JOIN — занятия без строки посещения дают is_present IS NULL (unknown).
marked AS (
  SELECT e.*, a.is_present
  FROM expected e
  LEFT JOIN practice03.attendance a
    ON a.schedule_id = e.id
   AND a.student_id = e.student_id
   AND a.week_start_date = e.week_start_date
   -- Константные границы недели для отсечения партиций (pruning).
   AND a.week_start_date >= (SELECT d1 - (extract(isodow FROM d1)::int - 1) FROM params)
   AND a.week_start_date <= (SELECT d2 - (extract(isodow FROM d2)::int - 1) FROM params)
),
counts AS (
  SELECT student_id,
         count(*) AS expected_count,
         count(*) FILTER (WHERE is_present IS TRUE) AS present_count,
         count(*) FILTER (WHERE is_present IS FALSE) AS absent_count,
         count(*) FILTER (WHERE is_present IS NULL) AS unknown_count,
         jsonb_agg(jsonb_build_object(
              'schedule_id', id, 'lecture_id', lecture_id, 'course_id', course_id,
              'course_title', course_title, 'lecture_title', lecture_title,
              'date', scheduled_date, 'is_present', is_present)
            ORDER BY scheduled_date, starts_at, id) AS sessions
  FROM marked
  GROUP BY student_id
),
ranked AS (
  SELECT co.*, st.record_book,
         100.0 * present_count / expected_count AS raw_percentage
  FROM counts co
  JOIN practice03.students st ON st.id = co.student_id
  WHERE unknown_count = 0
  ORDER BY 100.0 * present_count / expected_count,
            st.record_book COLLATE "C",
            student_id
  LIMIT (SELECT row_limit FROM params)
),
details AS (
  SELECT r.raw_percentage, r.record_book, r.student_id,
         jsonb_build_object(
            'student_pg', to_jsonb(st),
            'group', to_jsonb(g),
            'specialty', to_jsonb(sp),
            'department', to_jsonb(d),
            'institute', to_jsonb(i),
            'university', to_jsonb(u),
            'attendance_percentage', round(r.raw_percentage, 2),
            'present_count', r.present_count,
            'absent_count', r.absent_count,
            'expected_count', r.expected_count,
            'unknown_count', r.unknown_count,
            'period', jsonb_build_object('from', p.d1, 'to', p.d2, 'inclusive', true),
            'term', p.j->>'term',
            'sessions', r.sessions) AS doc
  FROM ranked r
  JOIN practice03.students st ON st.id = r.student_id
  JOIN practice03.study_groups g ON g.id = st.group_id
  JOIN practice03.specialties sp ON sp.id = g.specialty_id
  JOIN practice03.departments d ON d.id = g.department_id
  JOIN practice03.institutes i ON i.id = d.institute_id
  JOIN practice03.universities u ON u.id = i.university_id
  CROSS JOIN params p
)
SELECT jsonb_build_object(
  'matched_lecture_ids',
    coalesce((SELECT jsonb_agg(lecture_id ORDER BY lecture_id) FROM matched_lectures), '[]'::jsonb),
  'unlinked_materials',
    coalesce((SELECT jsonb_agg(h.id ORDER BY h.id) FROM hits h
              LEFT JOIN valid_hits v ON v.id = h.id WHERE v.id IS NULL), '[]'::jsonb),
  'graph_schedule_count', (SELECT count(*) FROM graph_schedule),
  'graph_member_count', (SELECT count(*) FROM graph_members),
  'graph_group_ids',
    coalesce((SELECT jsonb_agg(DISTINCT group_id ORDER BY group_id) FROM graph_schedule), '[]'::jsonb),
  'graph_missing_schedules',
    coalesce((SELECT jsonb_agg(schedule_id ORDER BY schedule_id) FROM graph_missing_schedules), '[]'::jsonb),
  'graph_extra_schedules',
    coalesce((SELECT jsonb_agg(schedule_id ORDER BY schedule_id) FROM graph_extra_schedules), '[]'::jsonb),
  'graph_wrong_schedules',
    coalesce((SELECT jsonb_agg(schedule_id ORDER BY schedule_id) FROM graph_wrong_schedules), '[]'::jsonb),
  'graph_missing_members',
    coalesce((SELECT jsonb_agg(student_id ORDER BY student_id) FROM graph_missing_members), '[]'::jsonb),
  'graph_extra_members',
    coalesce((SELECT jsonb_agg(student_id ORDER BY student_id) FROM graph_extra_members), '[]'::jsonb),
  'graph_wrong_members',
    coalesce((SELECT jsonb_agg(student_id ORDER BY student_id) FROM graph_wrong_members), '[]'::jsonb),
  'selected_schedule_count', (SELECT count(*) FROM selected_schedule),
  'selected_schedule',
    CASE WHEN (SELECT include_trace FROM params)
         THEN coalesce((SELECT jsonb_agg(to_jsonb(sc) ORDER BY scheduled_date, starts_at, id)
                        FROM selected_schedule sc), '[]'::jsonb)
         ELSE '[]'::jsonb END,
  'aggregation',
    CASE WHEN (SELECT include_trace FROM params)
         THEN coalesce((SELECT jsonb_agg(jsonb_build_object(
                     'student_id', student_id, 'expected_count', expected_count,
                     'present_count', present_count, 'absent_count', absent_count,
                     'unknown_count', unknown_count, 'raw_percentage',
                       round(100.0 * present_count / expected_count, 4))
                     ORDER BY student_id) FROM counts), '[]'::jsonb)
         ELSE '[]'::jsonb END,
  'incomplete_students',
    coalesce((SELECT jsonb_agg(jsonb_build_object(
                'student_id', student_id, 'expected_count', expected_count,
                'present_count', present_count, 'unknown_count', unknown_count,
                'minimum_percentage', round(100.0 * present_count / expected_count, 2),
                'maximum_percentage', round(100.0 * (present_count + unknown_count) / expected_count, 2))
              ORDER BY student_id) FROM counts WHERE unknown_count > 0), '[]'::jsonb),
  'eligible_student_count', (SELECT count(*) FROM counts),
  'complete_student_count', (SELECT count(*) FROM counts WHERE unknown_count = 0),
  'results',
    coalesce((SELECT jsonb_agg(doc ORDER BY raw_percentage, record_book COLLATE "C", student_id)
              FROM details), '[]'::jsonb)
) AS report;
