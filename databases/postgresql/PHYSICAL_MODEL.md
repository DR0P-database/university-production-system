# PostgreSQL physical model v0.1

Физическая модель является основой для SQLAlchemy 2.0 и Alembic для четырёх сервисов:

- `academic_db` — структура университета и учебный контент;
- `student_db` — группы и студенты;
- `schedule_db` — расписание;
- `attendance_db` — посещаемость.

## Общие правила

### Идентификаторы и время

- Все идентификаторы имеют тип `UUID`.
- Значение по умолчанию для идентификаторов:

  ```sql
  UUID PRIMARY KEY DEFAULT gen_random_uuid()
  ```

- `created_at`, `updated_at` и `marked_at` имеют тип `TIMESTAMPTZ`.
- Значения времени хранятся в UTC.
- Для `created_at` и `updated_at` используется:

  ```sql
  TIMESTAMPTZ NOT NULL DEFAULT now()
  ```

- PostgreSQL не обновляет `updated_at` автоматически. Это будет реализовано в SQLAlchemy или общим trigger'ом.

### Ограничения и индексы

- Для статусов используется `VARCHAR + CHECK`, а не PostgreSQL `ENUM`, чтобы значения можно было проще изменять миграциями.
- Все обязательные поля имеют `NOT NULL`.
- PostgreSQL не создаёт индекс на FK автоматически, поэтому нужные FK индексируются вручную.
- Межсервисные UUID также индексируются, если по ним выполняются запросы.
- Для удаления используются `RESTRICT`, если удаление родителя не должно каскадно удалять данные, и `CASCADE` для чистых таблиц связей и подчинённого учебного контента.

## `academic_db`

### `universities`

| Поле | Тип | Ограничения |
|---|---|---|
| `id` | `UUID` | PK, `NOT NULL`, `DEFAULT gen_random_uuid()` |
| `name` | `VARCHAR(500)` | `NOT NULL` |
| `short_name` | `VARCHAR(100)` | nullable |
| `address` | `TEXT` | nullable |
| `website` | `VARCHAR(255)` | nullable |
| `founded_year` | `SMALLINT` | nullable |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |

Ограничение:

```sql
CHECK (founded_year IS NULL OR founded_year > 0)
```

`name` не является `UNIQUE`: у организаций теоретически могут совпадать названия.

### `institutes`

| Поле | Тип | Ограничения |
|---|---|---|
| `id` | `UUID` | PK |
| `university_id` | `UUID` | `NOT NULL`, FK |
| `name` | `VARCHAR(500)` | `NOT NULL` |
| `short_name` | `VARCHAR(100)` | nullable |
| `dean` | `VARCHAR(300)` | nullable |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |

```sql
FOREIGN KEY (university_id)
REFERENCES universities(id)
ON DELETE RESTRICT

CREATE INDEX ix_institutes_university_id
ON institutes(university_id);
```

### `departments`

| Поле | Тип | Ограничения |
|---|---|---|
| `id` | `UUID` | PK |
| `institute_id` | `UUID` | `NOT NULL`, FK |
| `name` | `VARCHAR(500)` | `NOT NULL` |
| `short_name` | `VARCHAR(100)` | nullable |
| `head` | `VARCHAR(300)` | nullable |
| `room` | `VARCHAR(50)` | nullable |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |

```sql
FOREIGN KEY (institute_id)
REFERENCES institutes(id)
ON DELETE RESTRICT

CREATE INDEX ix_departments_institute_id
ON departments(institute_id);
```

### `specialties`

| Поле | Тип | Ограничения |
|---|---|---|
| `id` | `UUID` | PK |
| `name` | `VARCHAR(500)` | `NOT NULL` |
| `code` | `VARCHAR(20)` | `NOT NULL`, `UNIQUE` |
| `degree_level` | `VARCHAR(20)` | `NOT NULL` |
| `duration_years` | `SMALLINT` | `NOT NULL` |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |

```sql
CHECK (degree_level IN ('bachelor', 'master', 'specialist'))
CHECK (duration_years > 0)
```

Отдельный индекс на `code` не нужен: `UNIQUE` создаёт уникальный B-tree индекс.

### `department_specialties`

| Поле | Тип | Ограничения |
|---|---|---|
| `department_id` | `UUID` | часть составного PK, `NOT NULL`, FK |
| `specialty_id` | `UUID` | часть составного PK, `NOT NULL`, FK |
| `is_primary` | `BOOLEAN` | `NOT NULL`, `DEFAULT false` |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |

```sql
PRIMARY KEY (department_id, specialty_id)

FOREIGN KEY (department_id)
REFERENCES departments(id)
ON DELETE CASCADE

FOREIGN KEY (specialty_id)
REFERENCES specialties(id)
ON DELETE CASCADE

CREATE INDEX ix_department_specialties_specialty_id
ON department_specialties(specialty_id);

CREATE UNIQUE INDEX uq_specialty_primary_department
ON department_specialties(specialty_id)
WHERE is_primary = true;
```

Отдельный `UNIQUE (department_id, specialty_id)` не нужен: эту уникальность уже гарантирует составной PK.

### `lecture_courses`

| Поле | Тип | Ограничения |
|---|---|---|
| `id` | `UUID` | PK |
| `specialty_id` | `UUID` | `NOT NULL`, FK |
| `name` | `VARCHAR(500)` | `NOT NULL` |
| `description` | `TEXT` | nullable |
| `semester` | `SMALLINT` | `NOT NULL` |
| `total_hours` | `SMALLINT` | `NOT NULL` |
| `lecture_hours` | `SMALLINT` | `NOT NULL`, `DEFAULT 0` |
| `practice_hours` | `SMALLINT` | `NOT NULL`, `DEFAULT 0` |
| `lab_hours` | `SMALLINT` | `NOT NULL`, `DEFAULT 0` |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |

```sql
CHECK (semester BETWEEN 1 AND 12)
CHECK (total_hours >= 0)
CHECK (lecture_hours >= 0)
CHECK (practice_hours >= 0)
CHECK (lab_hours >= 0)
CHECK (lecture_hours + practice_hours + lab_hours <= total_hours)

FOREIGN KEY (specialty_id)
REFERENCES specialties(id)
ON DELETE RESTRICT

CREATE INDEX ix_lecture_courses_specialty_id
ON lecture_courses(specialty_id);
```

### `lectures`

| Поле | Тип | Ограничения |
|---|---|---|
| `id` | `UUID` | PK |
| `course_id` | `UUID` | `NOT NULL`, FK |
| `title` | `VARCHAR(500)` | `NOT NULL` |
| `annotation` | `TEXT` | nullable |
| `lecture_type` | `VARCHAR(20)` | `NOT NULL` |
| `order_number` | `SMALLINT` | `NOT NULL` |
| `duration_minutes` | `SMALLINT` | `NOT NULL`, `DEFAULT 90` |
| `requirements` | `TEXT` | nullable |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |

```sql
CHECK (lecture_type IN ('lecture', 'practice', 'lab'))
CHECK (order_number > 0)
CHECK (duration_minutes > 0)
UNIQUE (course_id, order_number)

FOREIGN KEY (course_id)
REFERENCES lecture_courses(id)
ON DELETE CASCADE
```

Отдельный индекс на `course_id` не нужен: его покрывает индекс `UNIQUE (course_id, order_number)`.

### `lecture_materials`

| Поле | Тип | Ограничения |
|---|---|---|
| `id` | `UUID` | PK |
| `lecture_id` | `UUID` | `NOT NULL`, FK |
| `content_type` | `VARCHAR(50)` | `NOT NULL` |
| `title` | `VARCHAR(500)` | nullable |
| `file_url` | `TEXT` | nullable |
| `content_ref` | `TEXT` | nullable, ссылка на MongoDB-документ |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |

```sql
CHECK (content_type IN (
    'text', 'presentation', 'pdf', 'video_link', 'code_sample', 'exercise'
))

CHECK (
    content_ref IS NOT NULL
    OR file_url IS NOT NULL
)

FOREIGN KEY (lecture_id)
REFERENCES lectures(id)
ON DELETE CASCADE

CREATE INDEX ix_lecture_materials_lecture_id
ON lecture_materials(lecture_id);
```

`content_text` и `metadata` физически находятся в MongoDB, в коллекции
`academic_content.lecture_material_contents`. MongoDB `_id` совпадает с UUID
материала. `file_url` остаётся внешней ссылкой на бинарный объект; сами файлы
текущий API не принимает и не хранит.

## `student_db`

### `student_groups`

| Поле | Тип | Ограничения |
|---|---|---|
| `id` | `UUID` | PK |
| `specialty_id` | `UUID` | `NOT NULL`, external, без FK |
| `department_id` | `UUID` | `NOT NULL`, external, без FK |
| `name` | `VARCHAR(50)` | `NOT NULL`, `UNIQUE` |
| `enrollment_year` | `SMALLINT` | `NOT NULL` |
| `curator` | `VARCHAR(300)` | nullable |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |

Обе внешние ссылки являются обычными `UUID` без `REFERENCES`.

```sql
CHECK (enrollment_year > 0)

CREATE INDEX ix_student_groups_specialty_id
ON student_groups(specialty_id);

CREATE INDEX ix_student_groups_department_id
ON student_groups(department_id);
```

### `students`

| Поле | Тип | Ограничения |
|---|---|---|
| `id` | `UUID` | PK |
| `group_id` | `UUID` | `NOT NULL`, FK |
| `first_name` | `VARCHAR(100)` | `NOT NULL` |
| `last_name` | `VARCHAR(100)` | `NOT NULL` |
| `patronymic` | `VARCHAR(100)` | nullable |
| `email` | `VARCHAR(255)` | nullable, `UNIQUE` |
| `phone` | `VARCHAR(30)` | nullable |
| `student_card_number` | `VARCHAR(50)` | nullable, `UNIQUE` |
| `enrollment_date` | `DATE` | `NOT NULL` |
| `status` | `VARCHAR(20)` | `NOT NULL`, `DEFAULT 'active'` |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |

```sql
FOREIGN KEY (group_id)
REFERENCES student_groups(id)
ON DELETE RESTRICT

CHECK (status IN ('active', 'academic_leave', 'expelled', 'graduated'))

CREATE INDEX ix_students_group_id
ON students(group_id);
```

Индекс по `(last_name, first_name)` можно добавить позднее, если появится подтверждённая потребность в поиске по ФИО.

## `schedule_db`

`course_id` намеренно отсутствует: курс определяется через цепочку `schedule.lecture_id → academic_db.lectures.course_id`.

### `schedule`

| Поле | Тип | Ограничения |
|---|---|---|
| `id` | `UUID` | PK |
| `lecture_id` | `UUID` | `NOT NULL`, external, без FK |
| `group_id` | `UUID` | `NOT NULL`, external, без FK |
| `scheduled_date` | `DATE` | `NOT NULL` |
| `week_start_date` | `DATE` | `NOT NULL` |
| `start_time` | `TIME` | `NOT NULL` |
| `end_time` | `TIME` | `NOT NULL` |
| `classroom` | `VARCHAR(50)` | nullable |
| `teacher_name` | `VARCHAR(300)` | nullable |
| `status` | `VARCHAR(20)` | `NOT NULL`, `DEFAULT 'scheduled'` |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |

`lecture_id` и `group_id` проверяются приложением через соответствующие сервисы.

```sql
CHECK (end_time > start_time)
CHECK (status IN ('scheduled', 'completed', 'cancelled'))
CHECK (EXTRACT(ISODOW FROM week_start_date) = 1)

CREATE INDEX ix_schedule_lecture_id
ON schedule(lecture_id);

CREATE INDEX ix_schedule_scheduled_date
ON schedule(scheduled_date);

CREATE INDEX ix_schedule_week_start_date
ON schedule(week_start_date);

CREATE INDEX ix_schedule_group_date
ON schedule(group_id, scheduled_date);
```

Отдельный индекс только на `group_id` не требуется: составной индекс `(group_id, scheduled_date)` подходит для запросов по одной группе.

## `attendance_db`

### `attendance`

| Поле | Тип | Ограничения |
|---|---|---|
| `id` | `UUID` | часть составного PK |
| `schedule_id` | `UUID` | `NOT NULL`, external, без FK |
| `student_id` | `UUID` | `NOT NULL`, external, без FK |
| `week_start_date` | `DATE` | часть составного PK, `NOT NULL` |
| `is_present` | `BOOLEAN` | `NOT NULL`, `DEFAULT false` |
| `marked_at` | `TIMESTAMPTZ` | nullable |
| `marked_by` | `UUID` | nullable, external, без FK |
| `note` | `VARCHAR(500)` | nullable |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, `DEFAULT now()` |

Чтобы подготовить таблицу к будущему партиционированию по `week_start_date`, используется составной первичный ключ:

```sql
PRIMARY KEY (id, week_start_date)

UNIQUE (schedule_id, student_id, week_start_date)

CHECK (EXTRACT(ISODOW FROM week_start_date) = 1)
```

`schedule_id` и `student_id` ссылаются на другие БД логически, но не объявляются PostgreSQL FK. `marked_by` — UUID пользователя из будущей auth-системы.

Индексы:

```sql
CREATE INDEX ix_attendance_schedule_id
ON attendance(schedule_id);

CREATE INDEX ix_attendance_student_id
ON attendance(student_id);

CREATE INDEX ix_attendance_week_start_date
ON attendance(week_start_date);
```

Отдельный составной индекс на `(schedule_id, student_id, week_start_date)` не нужен: его создаёт `UNIQUE`.

## Граница FK и external UUID

### Настоящие PostgreSQL FK

```text
academic_db:
  institutes.university_id -> universities.id
  departments.institute_id -> institutes.id
  department_specialties.department_id -> departments.id
  department_specialties.specialty_id -> specialties.id
  lecture_courses.specialty_id -> specialties.id
  lectures.course_id -> lecture_courses.id
  lecture_materials.lecture_id -> lectures.id

student_db:
  students.group_id -> student_groups.id
```

### Межсервисные external UUID без FK

```text
student_db:
  student_groups.specialty_id -> academic_db.specialties.id
  student_groups.department_id -> academic_db.departments.id

schedule_db:
  schedule.lecture_id -> academic_db.lectures.id
  schedule.group_id -> student_db.student_groups.id

attendance_db:
  attendance.schedule_id -> schedule_db.schedule.id
  attendance.student_id -> student_db.students.id
  attendance.marked_by -> будущая auth-система
```

## Зафиксированные отклонения от логической ER-модели

1. `TIMESTAMP` в логической схеме физически реализуется как `TIMESTAMPTZ`.
2. Статусы реализуются через `VARCHAR + CHECK`, а не через PostgreSQL `ENUM`.
3. Для `attendance` используется `PRIMARY KEY (id, week_start_date)`, чтобы не менять PK при последующем партиционировании по `week_start_date`.
4. Для `department_specialties` используется составной PK `(department_id, specialty_id)`; отдельный дублирующий `UNIQUE` не нужен.
5. Для специальности добавлено правило: только одна кафедра может быть `is_primary = true`.
