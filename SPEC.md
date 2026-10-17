# University Production System — data model

## Общая ER-модель всех сервисов

В общей диаграмме межсервисные связи подписаны как `external`

```mermaid
erDiagram
    UNIVERSITIES ||--|{ INSTITUTES : contains
    INSTITUTES ||--|{ DEPARTMENTS : contains
    DEPARTMENTS ||--o{ DEPARTMENT_SPECIALTIES : has
    SPECIALTIES ||--o{ DEPARTMENT_SPECIALTIES : assigned_to
    SPECIALTIES ||--|{ LECTURE_COURSES : includes
    LECTURE_COURSES ||--|{ LECTURES : contains
    LECTURES ||--|{ LECTURE_MATERIALS : has
    STUDENT_GROUPS ||--|{ STUDENTS : contains
    SPECIALTIES ||--o{ STUDENT_GROUPS : "external UUID, no FK"
    DEPARTMENTS ||--o{ STUDENT_GROUPS : "external UUID, no FK"
    LECTURES ||--o{ SCHEDULE : "external UUID, no FK"
    STUDENT_GROUPS ||--o{ SCHEDULE : "external UUID, no FK"
    SCHEDULE ||--o{ ATTENDANCE : "external UUID, no FK"
    STUDENTS ||--o{ ATTENDANCE : "external UUID, no FK"

    UNIVERSITIES {
        UUID id PK
        VARCHAR name
        TEXT address
        VARCHAR website
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    INSTITUTES {
        UUID id PK
        UUID university_id FK
        VARCHAR name
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    DEPARTMENTS {
        UUID id PK
        UUID institute_id FK
        VARCHAR name
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    SPECIALTIES {
        UUID id PK
        VARCHAR name
        VARCHAR code UK
        VARCHAR degree_level
        INT duration_years
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    DEPARTMENT_SPECIALTIES {
        UUID department_id PK, FK
        UUID specialty_id PK, FK
        BOOLEAN is_primary
        TIMESTAMP created_at
    }

    LECTURE_COURSES {
        UUID id PK
        UUID specialty_id FK
        VARCHAR name
        TEXT description
        INT total_hours
        INT lecture_hours
        INT practice_hours
        INT lab_hours
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    LECTURES {
        UUID id PK
        UUID course_id FK
        VARCHAR title
        TEXT annotation
        VARCHAR lecture_type
        INT order_number
        TEXT requirements
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    LECTURE_MATERIALS {
        UUID id PK
        UUID lecture_id FK
        VARCHAR content_type
        VARCHAR title
        VARCHAR file_url
        TEXT content_ref
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    STUDENT_GROUPS {
        UUID id PK
        UUID specialty_id "external"
        UUID department_id "external"
        VARCHAR name UK
        INT enrollment_year
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    STUDENTS {
        UUID id PK
        UUID group_id FK
        VARCHAR first_name
        VARCHAR last_name
        VARCHAR patronymic
        VARCHAR email UK
        VARCHAR phone
        VARCHAR student_card_number UK
        DATE enrollment_date
        VARCHAR status
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    SCHEDULE {
        UUID id PK
        UUID lecture_id "external"
        UUID group_id "external"
        DATE scheduled_date
        DATE week_start_date
        TIME start_time
        TIME end_time
        VARCHAR classroom
        VARCHAR teacher_name
        VARCHAR status
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    ATTENDANCE {
        UUID id PK
        UUID schedule_id "external"
        UUID student_id "external"
        DATE week_start_date
        BOOLEAN is_present
        TIMESTAMP marked_at
        UUID marked_by "external"
        VARCHAR note
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }
```

## Общая модель системы

```mermaid
flowchart LR
    subgraph ACADEMIC["academic-service / academic_db"]
        U[University]
        I[Institute]
        D[Department]
        S[Specialty]
        C[LectureCourse]
        L[Lecture]
        M[LectureMaterial]

        U -->|1:N| I
        I -->|1:N| D
        D <-->|M:N| S
        S -->|1:N| C
        C -->|1:N| L
        L -->|1:N| M
    end

    subgraph STUDENT["student-service / student_db"]
        G[StudentGroup]
        ST[Student]
        G -->|1:N| ST
    end

    subgraph SCHEDULE["schedule-service / schedule_db"]
        SC[Schedule]
    end

    subgraph ATTENDANCE["attendance-service / attendance_db"]
        AT[Attendance]
    end

    S -. "specialty_id: UUID, no FK" .-> G
    D -. "department_id: UUID, no FK" .-> G
    L -. "lecture_id: UUID, no FK" .-> SC
    G -. "group_id: UUID, no FK" .-> SC
    SC -. "schedule_id: UUID, no FK" .-> AT
    ST -. "student_id: UUID, no FK" .-> AT
```

## Физические правила PostgreSQL v0.1

Полная физическая модель находится в [databases/postgresql/PHYSICAL_MODEL.md](databases/postgresql/PHYSICAL_MODEL.md).

### Основные типы

- Все идентификаторы: `UUID PRIMARY KEY DEFAULT gen_random_uuid()`.
- `created_at`, `updated_at`, `marked_at`: `TIMESTAMPTZ NOT NULL DEFAULT now()`; время хранится в UTC.
- Годы, семестры, длительности и часы: `SMALLINT` с соответствующими `CHECK`.
- Статусы и типы: `VARCHAR` с `CHECK`, PostgreSQL `ENUM` не используется.
- Метаданные материалов: `JSONB NOT NULL DEFAULT '{}'`.
- Обязательные поля: `NOT NULL`.
- `updated_at` обновляется приложением или общим trigger'ом.

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

### Важные физические решения

- `department_specialties` использует составной PK `(department_id, specialty_id)` и `ON DELETE CASCADE`.
- Для одной специальности разрешена только одна primary-кафедра через partial unique index.
- Для `attendance` используется `PRIMARY KEY (id, week_start_date)` как подготовка к партиционированию по `week_start_date`.
- Все остальные удаления и FK используют безопасный `ON DELETE RESTRICT`, если это не таблица связи или подчинённый учебный контент.

## `academic_db`
```mermaid
erDiagram
    UNIVERSITIES ||--|{ INSTITUTES : contains
    INSTITUTES ||--|{ DEPARTMENTS : contains
    DEPARTMENTS ||--o{ DEPARTMENT_SPECIALTIES : has
    SPECIALTIES ||--o{ DEPARTMENT_SPECIALTIES : assigned_to
    SPECIALTIES ||--|{ LECTURE_COURSES : includes
    LECTURE_COURSES ||--|{ LECTURES : contains
    LECTURES ||--|{ LECTURE_MATERIALS : has

    UNIVERSITIES {
        UUID id PK
        VARCHAR name
        VARCHAR short_name
        TEXT address
        VARCHAR website
        INT founded_year
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    INSTITUTES {
        UUID id PK
        UUID university_id FK
        VARCHAR name
        VARCHAR short_name
        VARCHAR dean
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    DEPARTMENTS {
        UUID id PK
        UUID institute_id FK
        VARCHAR name
        VARCHAR short_name
        VARCHAR head
        VARCHAR room
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    SPECIALTIES {
        UUID id PK
        VARCHAR name
        VARCHAR code UK
        VARCHAR degree_level
        INT duration_years
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    DEPARTMENT_SPECIALTIES {
        UUID department_id PK, FK
        UUID specialty_id PK, FK
        BOOLEAN is_primary
        TIMESTAMP created_at
    }

    LECTURE_COURSES {
        UUID id PK
        UUID specialty_id FK
        VARCHAR name
        TEXT description
        INT semester
        INT total_hours
        INT lecture_hours
        INT practice_hours
        INT lab_hours
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    LECTURES {
        UUID id PK
        UUID course_id FK
        VARCHAR title
        TEXT annotation
        VARCHAR lecture_type
        INT order_number
        INT duration_minutes
        TEXT requirements
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    LECTURE_MATERIALS {
        UUID id PK
        UUID lecture_id FK
        VARCHAR content_type
        VARCHAR title
        VARCHAR file_url
        TEXT content_ref
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }
```

Полный `content_text` и произвольный `metadata` материала хранятся в MongoDB
в коллекции `academic_content.lecture_material_contents`. `_id` документа равен
UUID строки `lecture_materials`, а PostgreSQL `content_ref` явно указывает на
этот документ. Публичный REST API объединяет обе записи и сохраняет прежний
контракт.

Elasticsearch содержит только поисковую проекцию лекции: `title`, `annotation`,
`content_text`, `lecture_type` и `course`. Источником текста остаётся MongoDB,
а структурированных связей — PostgreSQL.

Ограничение для таблицы `department_specialties`:

```text
UNIQUE (department_id, specialty_id)
```

## `student_db`

`specialty_id` и `department_id` — внешние UUID из `academic_db`, поэтому это не PostgreSQL `FOREIGN KEY`.

```mermaid
erDiagram
    STUDENT_GROUPS ||--|{ STUDENTS : contains
    DEPARTMENTS ||--o{ STUDENT_GROUPS : "external UUID, no FK"

    STUDENT_GROUPS {
        UUID id PK
        UUID specialty_id "external"
        UUID department_id "external"
        VARCHAR name UK
        INT enrollment_year
        VARCHAR curator
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    STUDENTS {
        UUID id PK
        UUID group_id FK
        VARCHAR first_name
        VARCHAR last_name
        VARCHAR patronymic
        VARCHAR email UK
        VARCHAR phone
        VARCHAR student_card_number UK
        DATE enrollment_date
        VARCHAR status
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    SPECIALTIES {
        UUID id PK
        VARCHAR name
        VARCHAR code
    }

    DEPARTMENTS {
        UUID id PK
        VARCHAR name
    }
```

`SPECIALTIES` на этой диаграмме — внешний справочный объект, физически расположенный в `academic_db`.

```mermaid
flowchart LR
    A[academic_db: specialties.id] -. "specialty_id, no FK" .-> B[student_db: student_groups]
```

## `schedule_db`

`lecture_id` и `group_id` — внешние UUID из `academic_db` и `student_db`. `course_id` намеренно отсутствует: курс определяется через `lecture_id`.

```mermaid
erDiagram
    SCHEDULE {
        UUID id PK
        UUID lecture_id "external"
        UUID group_id "external"
        DATE scheduled_date
        DATE week_start_date
        TIME start_time
        TIME end_time
        VARCHAR classroom
        VARCHAR teacher_name
        VARCHAR status
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    LECTURES {
        UUID id PK
    }

    STUDENT_GROUPS {
        UUID id PK
    }
```

```mermaid
flowchart LR
    A[academic_db: lectures.id] -. "lecture_id, no FK" .-> C[schedule_db: schedule]
    B[student_db: student_groups.id] -. "group_id, no FK" .-> C
```

## `attendance_db`

`schedule_id` и `student_id` — внешние UUID из `schedule_db` и `student_db`.

```mermaid
erDiagram
    ATTENDANCE {
        UUID id PK
        UUID schedule_id "external"
        UUID student_id "external"
        DATE week_start_date
        BOOLEAN is_present
        TIMESTAMP marked_at
        UUID marked_by
        VARCHAR note
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    SCHEDULE {
        UUID id PK
    }

    STUDENTS {
        UUID id PK
    }
```

```mermaid
flowchart LR
    A[schedule_db: schedule.id] -. "schedule_id, no FK" .-> C[attendance_db: attendance]
    B[student_db: students.id] -. "student_id, no FK" .-> C
```

Ограничение для таблицы `attendance`:

```text
UNIQUE (schedule_id, student_id, week_start_date)
```

## Redis-проекция студента

PostgreSQL `student_db` остаётся источником истины. `student-service` применяет
cache-aside только для получения одного студента по уникальному
`student_card_number`:

```text
student:card:{student_card_number} -> полный публичный Student JSON
TTL = STUDENT_CACHE_TTL_SECONDS (по умолчанию 86400 секунд / 24 часа)
```

При промахе или недоступности Redis выполняется запрос в PostgreSQL. После
создания или изменения студента значение записывается в кэш, а при изменении
номера или удалении старый ключ инвалидируется.

## Neo4j-проекция структуры, студентов и расписания

PostgreSQL-базы остаются источниками истины. Каждый сервис проецирует в Neo4j
собственные сущности:

```text
(University)-[:HAS_INSTITUTE]->(Institute)
  -[:HAS_DEPARTMENT]->(Department)
  -[:OFFERS_SPECIALTY]->(Specialty)

(Department)-[:HAS_GROUP]->(StudentGroup)
(StudentGroup)-[:STUDIES_SPECIALTY]->(Specialty)
(StudentGroup)-[:HAS_STUDENT]->(Student)
(StudentGroup)-[:HAS_SCHEDULE]->(Schedule)
```

Курсы, лекции и посещаемость в Neo4j не сохраняются. Узлы имеют уникальные
ограничения по UUID. Academic-, student- и schedule-service при старте
синхронизируют только свою часть графа, не удаляя узлы других доменов;
дальнейшие CRUD-операции обновляют проекцию через `MERGE`. Graph API позволяют
получить студентов университета, университет и группу студента, а также
расписание студента без чтения PostgreSQL.
