# TODO и состояние проекта

Актуально на 31 октября 2026 года. Архитектурные решения и модели данных
описаны в [ARCHITECTURE.md](ARCHITECTURE.md).

## Реализовано

### Базовая архитектура и PostgreSQL

- [x] Выделены `academic-service`, `student-service`, `schedule-service` и
  `attendance-service`.
- [x] Для сервисов созданы отдельные логические PostgreSQL-базы и владельцы.
- [x] Запрещён cross-database SQL; межсервисные связи представлены external
  UUID и проверяются через API.
- [x] Зафиксированы UUID, `TIMESTAMPTZ`, `NOT NULL`, `UNIQUE`, `CHECK`, FK и
  индексы.
- [x] У каждого сервиса собственные SQLAlchemy-модели и Alembic migrations.
- [x] Добавлены RANGE-партиционирование Attendance по неделям, миграция
  существующих данных и создание партиций перед записью через API.

### REST API

- [x] Academic CRUD: университеты, институты, кафедры, специальности, курсы,
  лекции и материалы.
- [x] API назначения специальности кафедре и получения материалов лекции.
- [x] Student CRUD: группы и студенты, студенты группы, поиск по номеру билета.
- [x] Schedule CRUD, фильтры по группе, лекции, статусу и диапазону дат.
- [x] Attendance journal/history, одиночный и массовый идемпотентный PUT.
- [x] Межсервисные проверки существования объектов и соответствия
  специальности группы курсу лекции.
- [x] Проверка принадлежности студента группе занятия перед Attendance.
- [x] Пагинация `limit/offset` и единый формат ошибок с `request_id`.
- [x] Явные OpenAPI-схемы материалов, graph API и Elasticsearch search.

### Gateway и доступ

- [x] Gateway является единственной внешней точкой REST API.
- [x] Реализован универсальный proxy без дублирования handlers сервисов.
- [x] OpenAPI внутренних сервисов объединяется в `/openapi.json` Gateway.
- [x] Настроены upstream timeouts, `503` и передача `X-Request-ID`.
- [x] Реализованы выдача и проверка JWT, expiration, issuer и audience.
- [x] Все proxy API требуют access token.
- [x] Роли намеренно не вводились: действительный токен имеет единый уровень
  доступа.

### Polyglot persistence

- [x] MongoDB хранит полный `content_text` и metadata материала; PostgreSQL —
  структуру, `content_ref` и `file_url`.
- [x] Публичный Material API объединяет PostgreSQL и MongoDB и не раскрывает
  `content_ref`.
- [x] Elasticsearch хранит отдельные документы описаний лекций и текстовых
  материалов со строгим mapping.
- [x] Реализован поиск Elasticsearch с фильтрами `document_type`, `lecture_id`
  и `content_type`.
- [x] Redis реализует cache-aside по `student_card_number`, TTL 24 часа,
  инвалидацию и fallback на PostgreSQL.
- [x] Neo4j хранит структуру университета, группы, студентов и расписание.
- [x] Academic-, student- и schedule-service независимо восстанавливают и
  инкрементально обновляют свои части графа.
- [x] Реализованы graph API: университет → студенты, студент → группа и
  университет, студент → расписание.
- [x] PostgreSQL остаётся источником истины; Redis, Elasticsearch и Neo4j
  считаются восстанавливаемыми проекциями.

### Docker и тестовые данные

- [x] Весь проект запускается единым Docker Compose.
- [x] Разделены service и internal database networks.
- [x] Добавлены migration jobs и healthcheck сервисов и инфраструктуры.
- [x] Реализован идемпотентный REST seeder на 1000 студентов.
- [x] Реализован verifier PostgreSQL/MongoDB/Elasticsearch/Redis/Neo4j и
  межсервисных бизнес-связей.
- [x] Добавлены contract и business-rule tests; текущий набор содержит 36
  проходящих тестов.

## Зафиксированные ограничения текущего этапа

- Бинарные PDF и презентации не загружаются; демонстрационные материалы —
  текстовые документы, а `file_url` является внешней ссылкой.
- Один физический PostgreSQL-контейнер содержит четыре логические базы.
- JWT использует development-пользователей; production identity provider пока
  отсутствует.
- Проекции обновляются синхронно/best-effort и восстанавливаются при старте;
  брокера, Outbox и CDC пока нет.
- Elasticsearch использует стандартный analyzer; fuzzy search и highlighting
  пока не настроены.

## Следующий этап: ЛР2 — RabbitMQ и события

REST остаётся для синхронных запросов. RabbitMQ должен передавать факты уже
совершившихся изменений, не меняя ownership и публичные REST-контракты.

### Контракты событий

- [ ] Утвердить минимальный набор domain events:
  - `academic.specialty.updated`;
  - `academic.lecture.created` / `academic.lecture.updated`;
  - `student.created` / `student.updated` / `student.group_changed`;
  - `schedule.created` / `schedule.updated` / `schedule.cancelled`;
  - `attendance.marked` / `attendance.updated`.
- [ ] Ввести единый envelope:

  ```text
  event_id
  event_type
  event_version
  occurred_at
  producer
  correlation_id
  payload
  ```

- [ ] Зафиксировать JSON Schema/Pydantic-модели и правила совместимости версий.

### RabbitMQ

- [ ] Добавить RabbitMQ и management UI в активный Compose.
- [ ] Определить exchange, routing keys, очереди и ownership consumers.
- [ ] Реализовать producers и consumers через инфраструктурные adapters.
- [ ] Делать ACK только после успешной обработки.
- [ ] Добавить retry с backoff и Dead Letter Queue.
- [ ] Логировать `event_id`, `event_type` и `correlation_id`.
- [ ] Сделать consumers идемпотентными и хранить обработанные `event_id`.

### Transactional Outbox

- [ ] Добавить `outbox_events` в базы сервисов-производителей.
- [ ] Записывать business data и outbox event в одной PostgreSQL-транзакции.
- [ ] Реализовать publisher, блокировку/выборку пакетов, retry и отметку
  опубликованных событий.
- [ ] Не связывать domain layer напрямую с RabbitMQ SDK.
- [ ] Добавить тест сценария: PostgreSQL доступен, RabbitMQ временно недоступен,
  событие после восстановления не теряется.

### Definition of Done ЛР2

- [ ] Все сценарии текущего REST API продолжают работать.
- [ ] Есть реальные producer/consumer цепочки, retry и DLQ.
- [ ] Повторная доставка не создаёт дубликаты.
- [ ] Сбой RabbitMQ не приводит к потере зафиксированного события.
- [ ] Есть integration-тесты успешной, повторной и неуспешной доставки.

## После ЛР2: ЛР3 — масштабирование хранения

### Анализ запросов и индексов

- [ ] Собрать реальные SQL access patterns и `EXPLAIN (ANALYZE, BUFFERS)`.
- [ ] Проверить индексы Schedule, Attendance, Student и Academic.
- [ ] Удалить неиспользуемые и добавить подтверждённо необходимые индексы.

### Партиционирование Attendance

- [x] Добавить миграцию `attendance` на `PARTITION BY RANGE (week_start_date)`.
- [x] Создавать недельные partitions автоматически перед записью через API.
- [ ] Проверить partition pruning и локальные индексы.
- [x] Реализовать транзакционный перенос существующих данных и downgrade.

### Шардирование

- [ ] Выбрать shard key на основании измеренных запросов.
- [ ] Решить, нужна ли денормализация `attendance.group_id`.
- [ ] Описать функцию маршрутизации и поведение fan-out запросов.
- [ ] Поднять минимум два shard и проверить распределение и добавление shard.

### Репликация и конкурентные обновления

- [ ] Настроить PostgreSQL primary/replica и streaming replication.
- [ ] Выделить запросы, допустимые на read replica, с учётом replication lag.
- [ ] Вынести topology в конфигурацию, не зашивать адреса в application code.
- [ ] Добавить optimistic locking только для сущностей, где подтверждена
  проблема конкурентных изменений.

### Definition of Done ЛР3

- [ ] REST и события ЛР2 не сломаны.
- [ ] Attendance реально partitioned и демонстрирует pruning.
- [ ] Шарды содержат реально распределённые данные.
- [ ] Реплика получает WAL и обслуживает разрешённые чтения.
- [ ] Измерения показывают эффект выбранных индексов и топологии.

## Дальнейшее развитие

### Надёжность проекций

- [ ] После Outbox перевести Elasticsearch и Neo4j с синхронного обновления на
  события или CDC.
- [ ] Добавить projection checkpoints, retry и административный rebuild.
- [ ] Добавить reconciliation jobs, сравнивающие проекции с источниками истины.
- [ ] Формализовать поведение при частичном отказе MongoDB/PostgreSQL записи
  материала.

### Поиск

- [ ] Выбрать analyzer для русского и английского текста.
- [ ] Добавить fuzzy search с контролируемой дистанцией.
- [ ] Добавить highlighting и безопасные фрагменты результата.
- [ ] Добавить relevance-тесты и измерение качества поиска.

### Security и production readiness

- [ ] Заменить development users внешним identity provider.
- [ ] Решить, требуется ли ролевая модель и какие права действительно нужны.
- [ ] Перенести секреты в secret manager/volume и настроить ротацию.
- [ ] Добавить rate limiting и ограничения размера тела запроса на Gateway.
- [ ] Добавить TLS на внешней границе.

### Наблюдаемость и delivery

- [ ] Добавить структурированные JSON-логи.
- [ ] Добавить Prometheus metrics и distributed tracing.
- [ ] Создать dashboards и alerts для latency, error rate, очередей и lag.
- [ ] Настроить CI: lint, unit/contract tests, Compose validation и migration
  checks.
- [ ] Добавить backup/restore проверки PostgreSQL, MongoDB и Neo4j.

## Ближайший порядок работ

1. Зафиксировать event contracts и routing keys.
2. Добавить RabbitMQ Compose и healthcheck.
3. Реализовать Transactional Outbox в одном сервисе как эталон.
4. Добавить publisher, idempotent consumer, retry и DLQ.
5. Распространить шаблон на остальные domain events.
6. Только после Definition of Done ЛР2 переходить к partitioning/sharding.
