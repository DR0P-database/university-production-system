-- Дословный DDL из приложения А указанного пользователем отчета ПР3.
BEGIN;
SET LOCAL lock_timeout = '5s';
CREATE SCHEMA practice03;
SET LOCAL search_path = practice03, public;

CREATE TABLE universities (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code varchar(32) NOT NULL UNIQUE,
    name text NOT NULL CHECK (btrim(name) <> ''),
    short_name text,
    address text,
    website text
);
CREATE TABLE institutes (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    university_id integer NOT NULL REFERENCES universities(id),
    code varchar(32) NOT NULL,
    name text NOT NULL CHECK (btrim(name) <> ''),
    UNIQUE (university_id, code)
);
CREATE TABLE departments (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    institute_id integer NOT NULL REFERENCES institutes(id),
    code varchar(32) NOT NULL,
    name text NOT NULL CHECK (btrim(name) <> ''),
    UNIQUE (institute_id, code)
);
CREATE TABLE specialties (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code varchar(20) NOT NULL UNIQUE,
    name text NOT NULL CHECK (btrim(name) <> ''),
    degree_level varchar(12) NOT NULL
        CHECK (degree_level IN ('bachelor','master','specialist')),
    duration_years smallint NOT NULL CHECK (duration_years BETWEEN 1 AND 10)
);
CREATE TABLE department_specialties (
    department_id integer NOT NULL REFERENCES departments(id),
    specialty_id integer NOT NULL REFERENCES specialties(id),
    is_primary boolean NOT NULL DEFAULT false,
    PRIMARY KEY (department_id, specialty_id)
);
CREATE UNIQUE INDEX department_specialties_one_primary
    ON department_specialties (specialty_id) WHERE is_primary;
CREATE INDEX department_specialties_reverse
    ON department_specialties (specialty_id, department_id);

CREATE TABLE study_groups (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    specialty_id integer NOT NULL REFERENCES specialties(id),
    department_id integer NOT NULL REFERENCES departments(id),
    code varchar(32) NOT NULL UNIQUE,
    training_profile text NOT NULL CHECK (btrim(training_profile) <> ''),
    enrollment_year smallint NOT NULL CHECK (enrollment_year BETWEEN 1900 AND 2200),
    curator_name text,
    group_leader_student_id integer UNIQUE,
    CONSTRAINT study_groups_department_specialty_fk
        FOREIGN KEY (department_id, specialty_id)
        REFERENCES department_specialties (department_id, specialty_id)
);
COMMENT ON COLUMN study_groups.department_id IS 'Выпускающая кафедра группы';
CREATE INDEX study_groups_specialty ON study_groups (specialty_id);
CREATE INDEX study_groups_department_specialty ON study_groups (department_id, specialty_id);
CREATE TABLE students (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    group_id integer NOT NULL REFERENCES study_groups(id),
    record_book varchar(20) NOT NULL UNIQUE CHECK (btrim(record_book) <> ''),
    last_name text NOT NULL CHECK (btrim(last_name) <> ''),
    first_name text NOT NULL CHECK (btrim(first_name) <> ''),
    patronymic text,
    email text,
    phone varchar(32),
    enrollment_date date NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','academic_leave','expelled','graduated'))
);
ALTER TABLE study_groups ADD CONSTRAINT study_groups_leader_fk
    FOREIGN KEY (group_leader_student_id) REFERENCES students(id);
CREATE INDEX students_group ON students (group_id, id);

CREATE TABLE courses (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    specialty_id integer NOT NULL,
    department_id integer NOT NULL,
    code varchar(64) NOT NULL,
    title text NOT NULL CHECK (btrim(title) <> ''),
    description text NOT NULL DEFAULT '',
    academic_year_start smallint NOT NULL CHECK (academic_year_start BETWEEN 1900 AND 2200),
    semester smallint NOT NULL CHECK (semester BETWEEN 1 AND 12),
    is_elective boolean NOT NULL DEFAULT false,
    FOREIGN KEY (department_id, specialty_id)
        REFERENCES department_specialties (department_id, specialty_id),
    UNIQUE (specialty_id, code, academic_year_start, semester)
);
CREATE INDEX courses_department_specialty ON courses (department_id, specialty_id);

CREATE TABLE lectures (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    course_id integer NOT NULL REFERENCES courses(id),
    title text NOT NULL CHECK (btrim(title) <> ''),
    annotation text NOT NULL DEFAULT '',
    lesson_type varchar(8) NOT NULL CHECK (lesson_type IN ('lecture','practice','lab')),
    order_number smallint NOT NULL CHECK (order_number > 0),
    academic_hours smallint NOT NULL DEFAULT 2 CHECK (academic_hours > 0),
    tags text[] NOT NULL DEFAULT '{}',
    requires_equipment boolean NOT NULL DEFAULT false,
    UNIQUE (course_id, order_number)
);
COMMENT ON COLUMN lectures.requires_equipment IS 'Нужно ли оборудование для занятия';

CREATE TABLE lecture_materials (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lecture_id integer NOT NULL REFERENCES lectures(id),
    material_type varchar(16) NOT NULL DEFAULT 'text' CHECK (material_type = 'text'),
    title text NOT NULL CHECK (btrim(title) <> ''),
    position smallint NOT NULL CHECK (position > 0),
    metadata jsonb NOT NULL DEFAULT '{}',
    UNIQUE (lecture_id, position),
    CHECK (jsonb_typeof(metadata) = 'object'),
    CHECK (NOT (metadata ?| ARRAY['content_text','content','body','file_data','data_base64']))
);
COMMENT ON TABLE lecture_materials IS 'Карточки материалов; полные тексты хранятся в Elasticsearch';

CREATE TABLE schedule (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lecture_id integer NOT NULL REFERENCES lectures(id),
    group_id integer NOT NULL REFERENCES study_groups(id),
    scheduled_date date NOT NULL,
    week_start_date date NOT NULL,
    starts_at time NOT NULL,
    ends_at time NOT NULL,
    classroom varchar(50) NOT NULL,
    teacher_name text NOT NULL,
    status varchar(12) NOT NULL CHECK (status IN ('scheduled','completed','cancelled')),
    CHECK (ends_at > starts_at),
    CHECK (week_start_date = scheduled_date - (extract(isodow FROM scheduled_date)::integer - 1)),
    UNIQUE (id, week_start_date),
    UNIQUE (lecture_id, group_id, scheduled_date, starts_at)
);
CREATE INDEX schedule_group_date ON schedule (group_id, scheduled_date, starts_at);
CREATE INDEX schedule_lecture_date ON schedule (lecture_id, scheduled_date);

CREATE TABLE attendance (
    week_start_date date NOT NULL,
    schedule_id integer NOT NULL,
    student_id integer NOT NULL REFERENCES students(id),
    is_present boolean NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    marked_by text,
    note text,
    PRIMARY KEY (week_start_date, schedule_id, student_id),
    FOREIGN KEY (schedule_id, week_start_date) REFERENCES schedule(id, week_start_date)
) PARTITION BY RANGE (week_start_date);
CREATE INDEX attendance_student_week ON attendance (student_id, week_start_date, schedule_id);
CREATE INDEX attendance_schedule_week ON attendance (schedule_id, week_start_date);

CREATE FUNCTION create_attendance_partitions(first_monday date, week_count integer)
RETURNS void LANGUAGE plpgsql
SET search_path = practice03, pg_catalog, public AS $$
DECLARE d date; partition_name text;
BEGIN
    IF first_monday IS NULL OR extract(isodow FROM first_monday) <> 1
        OR week_count IS NULL OR week_count < 1 OR week_count > 104 THEN
        RAISE EXCEPTION 'Monday and week_count in 1..104 required';
    END IF;
    FOR i IN 0..week_count-1 LOOP
        d := first_monday + i*7;
        partition_name := 'attendance_w' || to_char(d,'YYYY_MM_DD');
        EXECUTE format('CREATE TABLE IF NOT EXISTS practice03.%I
                        PARTITION OF practice03.attendance FOR VALUES FROM (%L) TO (%L)',
                        partition_name, d, d+7);
    END LOOP;
END;
$$;
SELECT create_attendance_partitions(DATE '2026-09-07', 16);

COMMENT ON TABLE universities IS 'Университеты';
COMMENT ON TABLE institutes IS 'Институты университетов';
COMMENT ON TABLE departments IS 'Кафедры институтов';
COMMENT ON TABLE specialties IS 'Направления подготовки';
COMMENT ON TABLE department_specialties IS 'Закрепление кафедр за направлениями';
COMMENT ON TABLE study_groups IS 'Группы с выпускающей кафедрой';
COMMENT ON TABLE students IS 'Студенты и их текущие группы';
COMMENT ON TABLE courses IS 'Курсы учебного периода';
COMMENT ON TABLE lectures IS 'Темы занятий и признак потребности в оборудовании';
COMMENT ON TABLE schedule IS 'Проведение занятия для группы';
COMMENT ON TABLE attendance IS 'Отметки посещаемости по недельным партициям';
COMMIT;
