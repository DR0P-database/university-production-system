# TODO — план развития университетской микросервисной системы

- [] Полный текст должен хранится в нужной спец. БД и это не postgres. С остальными данными то же. Postgres является только ссылкой на файл или другой обьект 
- [] neo4j основная цель -- связь студентов с лекцией 

Этот файл фиксирует порядок работ по проекту так, чтобы каждая следующая лабораторная расширяла предыдущую и не требовала переработки уже готовой архитектуры.

---

## 0. Общий фундамент проекта

Этот блок не относится к одной конкретной лабораторной. Это базовые решения, которые должны сохраняться дальше.

### Архитектура

- [x] Выделить микросервисы:
  - `academic-service`
  - `student-service`
  - `schedule-service`
  - `attendance-service`
- [x] Разделить владение таблицами между сервисами.
- [x] Зафиксировать ER-модель.
- [x] Использовать UUID как идентификаторы.
- [x] Разделить реальные PostgreSQL `FOREIGN KEY` внутри сервиса и межсервисные UUID без FK.
- [x] Зафиксировать PostgreSQL-типы, `NOT NULL`, `UNIQUE`, `CHECK`, индексы.
- [x] Спроектировать REST API.
- [x] Использовать единый внешний API-префикс `/api/v1/...`.
- [x] Реализовать API Gateway.
- [x] Реализовать базовую межсервисную валидацию.

### Общие технические задачи

- [x] Привести ошибки всех сервисов к единому формату: `code`, `message`, `details`, `request_id`.
- [x] Добавить `request_id / correlation_id`.
- [x] Добавить пагинацию на collection-endpoints.
- [x] Добавить `date_from/date_to` для расписания.
- [x] Нормализовать HTTP-коды:
  - `400` — нарушение бизнес-правила;
  - `401` — нет/невалидная аутентификация;
  - `403` — недостаточно прав;
  - `404` — объект или связанный объект не найден;
  - `409` — конфликт данных;
  - `422` — ошибка структуры/валидации запроса;
  - `503` — зависимый сервис недоступен.
- [x] Добавить межсервисные бизнес-проверки:
  - `lecture.course.specialty_id == group.specialty_id`;
  - `schedule.group_id == student.group_id` при Attendance.
- [x] Настроить отдельный Alembic для каждой БД.
- [x] Подготовить стабильный набор тестовых данных.
- [x] Добавить базовые integration-тесты API-контрактов и бизнес-правил.

### Правило владения данными

```text
academic-service   -> academic_db
student-service    -> student_db
schedule-service   -> schedule_db
attendance-service -> attendance_db
```

Запрещено:

```text
service A -> SQL -> database B
```

Разрешено:

```text
service A -> REST / events -> service B
```

---

# Лабораторная работа 1 — микросервисы, REST API, API Gateway, JWT

## Цель

Закрыть базовую микросервисную архитектуру:

```text
Client
  |
  v
API Gateway
  |
  +--> academic-service
  +--> student-service
  +--> schedule-service
  +--> attendance-service
```

Каждый сервис имеет собственную БД и не обращается напрямую к таблицам других сервисов.

## 1.1. PostgreSQL

- [x] Определить четыре логические БД:
  - `academic_db`
  - `student_db`
  - `schedule_db`
  - `attendance_db`
- [x] Распределить таблицы по сервисам.
- [x] Создать отдельного PostgreSQL-пользователя для каждой БД:
  - `academic_user`
  - `student_user`
  - `schedule_user`
  - `attendance_user`
- [x] Ограничить права каждого пользователя только своей БД.
- [x] Поднимать схему только через Alembic migrations.
- [x] Проверить PK, FK, UNIQUE, CHECK, NOT NULL и индексы.
- [x] Добавить и проверить идемпотентную загрузку объёмных тестовых данных.

### Важно

На ЛР1 можно использовать один физический PostgreSQL-контейнер с четырьмя логическими БД. Разносить PostgreSQL на четыре отдельных сервера пока не нужно.

## 1.2. REST API

### Academic service

- [x] CRUD для universities, institutes, departments, specialties, courses, lectures, materials.
- [x] API связи кафедра ↔ специальность.
- [x] Получение материалов конкретной лекции.
- [x] Фильтры.

### Student service

- [x] CRUD для groups и students.
- [x] Получение студентов конкретной группы.
- [x] Фильтры.

### Schedule service

- [x] CRUD расписания.
- [x] Фильтры: `group_id`, `lecture_id`, `status`, `scheduled_date`, `week_start_date`.
- [x] Проверка существования lecture и group.
- [x] Добавить `date_from` и `date_to`.
- [x] Добавить бизнес-проверку соответствия специальности группы и курса.

### Attendance service

- [x] Получение Attendance.
- [x] Идемпотентный `PUT` по `schedule_id + student_id`.
- [x] Массовая отметка посещения.
- [x] Получение журнала занятия.
- [x] Получение истории студента.
- [x] Проверять, что студент принадлежит группе занятия.

### Общие задачи API

- [x] Добавить пагинацию: `limit`, `offset`.
- [x] Ограниченную сортировку пока не добавлять: подтверждённой потребности нет.
- [x] Проверить единообразные response/error schemas.
- [x] Проверить OpenAPI/Swagger.

## 1.3. API Gateway

- [x] Проксирование:

```text
/api/v1/academic/*   -> academic-service
/api/v1/students/*   -> student-service
/api/v1/schedule/*   -> schedule-service
/api/v1/attendance/* -> attendance-service
```

- [x] `GET /health`.
- [x] Сделать Gateway единственной внешней точкой входа.
- [x] Закрыть прямой внешний доступ к сервисам.
- [x] Оставить внутренний доступ между сервисами через Docker network.
- [x] Передавать `request_id/correlation_id`.
- [x] Настроить timeout для upstream-сервисов.
- [x] Возвращать `503`, если зависимый сервис недоступен.

## 1.4. JWT-доступ к Gateway

- [x] Определить способ выдачи JWT.
- [x] Проверять подпись JWT на Gateway.
- [x] Проверять expiration.
- [x] Требовать валидный JWT для любого обращения к API через Gateway.
- [x] Не вводить роли: корректный токен предоставляет одинаковый доступ ко всем
  API Gateway.

### Архитектурное правило

Микросервисы не должны самостоятельно выдавать JWT. Аутентификация должна оставаться отдельной ответственностью auth/gateway-слоя.

## 1.5. Docker Compose

- [x] Поднимать весь проект одной командой.
- [x] Добавить healthcheck PostgreSQL.
- [x] Добавить healthcheck сервисов.
- [x] Добавить healthcheck Gateway.
- [x] Вынести конфигурацию в environment variables.
- [x] Не хранить секреты в исходном коде.
- [x] Разделить Docker networks: frontend/service network и database network.
- [x] Gateway не должен иметь доступ к PostgreSQL network.
- [x] PostgreSQL наружу открывать только в текущем development Compose.

## 1.6. Тестирование ЛР1

Проверить полный end-to-end сценарий:

```text
University
-> Institute
-> Department
-> Specialty
-> Course
-> Lecture
-> Group
-> Student
-> Schedule
-> Attendance
```

Проверить негативные сценарии:

- [x] Нельзя создать Schedule с несуществующей Lecture.
- [x] Нельзя создать Schedule с несуществующей Group.
- [x] Нельзя поставить Attendance студенту из другой группы.
- [x] Повторный Attendance не создаёт дубликат.
- [x] Недоступный dependency-service даёт `503`.
- [x] Запрос без JWT отклоняется.
- [x] Запрос с истёкшим или некорректным JWT отклоняется.
- [x] Duplicate уникального значения даёт `409`.

## Definition of Done — ЛР1

```text
Docker Compose поднимается
+
4 микросервиса работают
+
4 логические БД работают
+
REST API работает
+
Gateway работает
+
JWT работает
+
межсервисная валидация работает
+
есть end-to-end сценарий
+
есть базовые интеграционные тесты
```

---

# Лабораторная работа 2 — RabbitMQ и асинхронные события

## Главный принцип

ЛР2 не должна ломать REST API или менять ownership данных. RabbitMQ добавляется как новый канал взаимодействия для событий. REST остаётся для синхронных запросов.

## 2.1. Определить события

Минимальный набор:

```text
academic.specialty.updated
academic.lecture.created
academic.lecture.updated

student.created
student.updated
student.group_changed

schedule.created
schedule.updated
schedule.cancelled

attendance.marked
attendance.updated
```

Не нужно публиковать событие на каждую техническую операцию. Событие должно означать реальное изменение состояния предметной области.

## 2.2. Стандарт события

Все события должны иметь единый envelope:

```text
event_id
event_type
event_version
occurred_at
producer
correlation_id
payload
```

Обязательно использовать `event_version`.

## 2.3. RabbitMQ

- [ ] Добавить RabbitMQ в Docker Compose.
- [ ] Создать exchange.
- [ ] Определить routing keys.
- [ ] Создать очереди consumers.
- [ ] Реализовать producers.
- [ ] Реализовать consumers.
- [ ] ACK только после успешной обработки.
- [ ] Retry для временных ошибок.
- [ ] Dead Letter Queue для неуспешных сообщений.
- [ ] Сделать consumers идемпотентными.
- [ ] Добавить логирование `event_id`, `event_type`, `correlation_id`.

## 2.4. Transactional Outbox

Рекомендуется внедрить сразу в ЛР2.

Проблема без Outbox:

```text
1. Запись сохранена в PostgreSQL
2. Нужно отправить событие в RabbitMQ
3. RabbitMQ недоступен
4. Данные сохранены
5. Событие потеряно
```

Правильная схема:

```text
BEGIN

INSERT business_data
INSERT outbox_event

COMMIT
```

Далее отдельный publisher отправляет события из Outbox в RabbitMQ.

TODO:

- [ ] Добавить `outbox_events`.
- [ ] Записывать событие в одной транзакции с бизнес-изменением.
- [ ] Реализовать publisher.
- [ ] Помечать опубликованные события.
- [ ] Добавить retry.
- [ ] Не привязывать domain-layer напрямую к RabbitMQ.

## 2.5. Когда REST, а когда RabbitMQ

REST использовать, если нужен немедленный ответ:

```text
существует ли Lecture?
получить Group
получить Student
получить Schedule
```

RabbitMQ использовать, если событие уже произошло, а другим сервисам нужно об этом узнать.

## Definition of Done — ЛР2

```text
ЛР1 продолжает работать
+
RabbitMQ работает
+
есть producers
+
есть consumers
+
есть реальные domain events
+
consumer идемпотентен
+
ошибка consumer не теряет сообщение
+
есть retry/DLQ
+
REST-контракты ЛР1 не сломаны
```

---

# Лабораторная работа 3 — партиционирование, шардирование и репликация

## Главный принцип

Публичный REST API желательно не менять. Меняется инфраструктура хранения, а не контракт клиента с системой.

## 3.1. Зафиксировать реальные access patterns

Основные запросы:

```text
Schedule:
- group_id + date
- week_start_date
- lecture_id

Attendance:
- schedule_id
- student_id
- week_start_date

Student:
- group_id

Academic:
- department
- specialty
```

- [ ] Проверить текущие SQL-запросы.
- [ ] Проверить execution plans.
- [ ] Удалить бесполезные индексы.
- [ ] Добавить отсутствующие индексы под реальные запросы.

## 3.2. Партиционирование Attendance

Использовать:

```text
PARTITION BY RANGE (week_start_date)
```

- [ ] Сделать `attendance` partitioned table.
- [ ] Создавать недельные partitions.
- [ ] Проверить partition pruning.
- [ ] Проверить индексы partitions.
- [ ] Автоматизировать создание новых недельных partitions.
- [ ] Проверить миграцию существующих данных.

## 3.3. Шардирование

Нужно определить shard key на основе реальных access patterns.

Потенциальный вариант для Attendance:

```text
group_id
```

Но сейчас `group_id` непосредственно в Attendance отсутствует.

Вариант A:

```text
Attendance
-> schedule_id
-> Schedule
-> group_id
```

Вариант B: денормализовать `attendance.group_id` и использовать его непосредственно как shard key.

TODO:

- [ ] Выбрать стратегию.
- [ ] Обосновать shard key.
- [ ] Описать функцию маршрутизации.
- [ ] Создать минимум два shard.
- [ ] Проверить распределение данных.
- [ ] Проверить запрос к одному shard.
- [ ] Проверить fan-out запрос, если он нужен.
- [ ] Проверить поведение при добавлении нового shard.

## 3.4. Репликация PostgreSQL

- [ ] Поднять primary.
- [ ] Поднять replica.
- [ ] Настроить streaming replication.
- [ ] Проверить WAL.
- [ ] Проверить появление изменений на replica.
- [ ] Определить, какие запросы можно отправлять на read replica.
- [ ] Не зашивать физические адреса БД в application code.
- [ ] Держать topology/configuration во внешних настройках.

## 3.5. Versioning / optimistic locking

При необходимости добавить:

```text
version
created_by
```

Не обязательно добавлять их во все таблицы. Использовать только там, где реально требуется контроль конкурентного изменения.

## Definition of Done — ЛР3

```text
API ЛР1 не сломан
+
RabbitMQ ЛР2 продолжает работать
+
Attendance partitioned
+
определена стратегия шардирования
+
данные реально распределяются по shard-ам
+
работает репликация
+
индексы оптимизированы
+
есть демонстрация запросов
+
есть объяснение выбора shard key
```

---

# Задел на последующие работы — CDC и polyglot persistence

PostgreSQL остаётся source of truth.

Специализированные хранилища используются как projection/read-model/cache:

```text
PostgreSQL
    |
    | source of truth
    v
events / CDC
    |
    +--> Redis
    +--> MongoDB
    +--> Neo4j
    +--> Elasticsearch
```

## Redis

Планируемые данные:

```text
schedule cache
current lessons
sessions
```

TODO:

- [ ] Определить key naming.
- [ ] Определить TTL.
- [ ] Выбрать cache pattern.
- [ ] Определить invalidation strategy.
- [ ] Обеспечить fallback на PostgreSQL при недоступности Redis.

## Neo4j

Планируемая проекция:

```text
University
-> Institute
-> Department
-> Specialty
-> LectureCourse
```

TODO:

- [ ] Определить nodes.
- [ ] Определить relationships.
- [ ] Настроить синхронизацию.
- [ ] Реализовать графовые запросы.
- [ ] PostgreSQL оставить authoritative source.

## MongoDB

Планируемая проекция: `LectureMaterial`.

TODO:

- [ ] Определить document schema.
- [ ] Группировать материалы как агрегат лекции, если это удобно для чтения.
- [ ] Настроить синхронизацию с PostgreSQL.
- [ ] Не делать MongoDB источником истины для структурированных данных.

## Elasticsearch

Планируемый индекс: `lectures`.

Поля:

```text
title
annotation
content_text
lecture_type
course
```

TODO:

- [ ] Создать mapping.
- [ ] Настроить analyzer.
- [ ] Настроить полнотекстовый поиск.
- [ ] Настроить fuzzy search.
- [ ] Настроить highlight.
- [ ] Настроить обновление индекса через CDC/events.
- [ ] PostgreSQL оставить source of truth.

---

# Архитектурные правила на весь проект

1. Публичный REST API менять только при реальной необходимости.
2. Один сервис владеет одной предметной областью и своей БД.
3. Никаких cross-database SQL-запросов.
4. Межсервисные связи — UUID без PostgreSQL FK.
5. PostgreSQL — источник истины для структурированных данных.
6. Redis/MongoDB/Neo4j/Elasticsearch — производные представления или кэш.
7. Синхронный запрос с немедленным ответом — REST.
8. Факт произошедшего изменения — event.
9. Domain layer не должен зависеть от RabbitMQ/Redis/Elastic/Mongo/Neo4j напрямую.
10. Инфраструктура должна подключаться через adapters/repositories.
11. UUID должны сохраняться одинаковыми во всех projections.
12. Все события должны иметь `event_id`, `event_type`, `event_version`, `correlation_id`.
13. Consumers должны быть идемпотентными.
14. Новая лабораторная должна расширять предыдущую, а не заменять её.

---

# Критический путь проекта

```text
СЕЙЧАС
|
+-- доделать API-мелочи
+-- закончить PostgreSQL/Alembic
+-- JWT
+-- роли
+-- Gateway security
+-- Docker Compose
+-- integration/e2e tests
|
v
ЛР1 ГОТОВА
|
+-- event contracts
+-- RabbitMQ
+-- Transactional Outbox
+-- consumers
+-- retry / DLQ
+-- idempotency
|
v
ЛР2 ГОТОВА
|
+-- partition Attendance
+-- shard strategy
+-- shards
+-- replication
+-- index/performance review
|
v
ЛР3 ГОТОВА
|
+-- CDC
+-- Redis
+-- MongoDB
+-- Neo4j
+-- Elasticsearch
|
v
ПОСЛЕДУЮЩИЕ РАБОТЫ
```

---

# Текущий ближайший TODO

- [x] Исправить HTTP status codes межсервисной валидации.
- [x] Добавить пагинацию.
- [x] Добавить `date_from/date_to` в Schedule.
- [x] Добавить проверку `lecture specialty == group specialty`.
- [x] Добавить проверку `student.group_id == schedule.group_id`.
- [x] Проверить отдельные Alembic migrations.
- [x] Проверить права PostgreSQL users.
- [x] Реализовать JWT.
- [x] Защитить API Gateway единым JWT dependency без ролевых проверок.
- [x] Закрыть прямой внешний доступ к микросервисам.
- [x] Проверить весь проект через end-to-end сценарий.
- [ ] После этого фиксировать ЛР1 как завершённую и переходить к RabbitMQ.
