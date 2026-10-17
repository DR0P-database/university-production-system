# University Production System

Микросервисный backend университетской системы на FastAPI с polyglot-хранением.

## Состав

- `gateway` — единая внешняя точка входа на порту `8000`;
- `academic-service` — структура университета и учебные материалы;
- `student-service` — группы и студенты;
- `schedule-service` — расписание;
- `attendance-service` — посещаемость;
- четыре логические PostgreSQL-базы с отдельными владельцами и Alembic;
- MongoDB для полного текста и метаданных учебных материалов;
- Elasticsearch для поисковой проекции лекций;
- Redis для cache-aside поиска студента по номеру студенческого билета;
- Neo4j для связной read-модели структуры, групп, студентов и расписания.

## Запуск

Заполните `.env`, затем запустите систему:

```bash
docker compose up --build
```

Внутренние сервисы доступны только внутри Docker network. Снаружи API
публикует Gateway: `http://localhost:8000`.

Gateway подключён только к `services-network`, PostgreSQL — только к внутренней
`database-network`. Каждый микросервис подключён к обеим сетям и использует
собственного владельца БД.

## Объёмный тестовый набор данных

После запуска миграций загрузите идемпотентный набор через внутренние REST API:

```bash
docker compose --profile tools run --rm --build seed-data
```

По умолчанию генератор создаёт 2 университета, 34 группы, 1000 студентов,
408 занятий и 4000 отметок посещаемости. В группе находится не больше 30
студентов. Academic, student, schedule и attendance данные записываются только
через API сервиса-владельца своей БД.

Каждая лекция получает детерминированный Markdown-конспект и практическое
задание с ключевыми словами. Повторный запуск обновляет устаревшие seed-материалы
через API и не создаёт дубликаты.

При создании материала academic-service оставляет структуру и ссылки в
PostgreSQL, сохраняет `content_text` и `metadata_json` в MongoDB и обновляет
поисковый документ лекции в Elasticsearch. Формат REST-запросов и ответов при
этом не меняется.

Обычные `GET /api/v1/academic/lectures` и `GET .../lectures/{id}` читают
структурную карточку лекции из PostgreSQL. Запросы материалов сначала получают
`id`, `lecture_id`, тип, название и ссылку из PostgreSQL, затем academic-service
добавляет `content_text` и `metadata_json` из MongoDB. Elasticsearch не является
источником ответа этих endpoints: в него отдельно собирается поисковый документ
из карточки лекции и курса в PostgreSQL плюс текстов материалов в MongoDB.

Создание и изменение студента обновляет Redis-кэш. Запрос по уникальному номеру
`GET /api/v1/students/students/by-card/{student_card_number}` использует
cache-aside и возвращает `X-Cache: HIT` или `MISS`; при недоступном Redis сервис
продолжает читать PostgreSQL. TTL студента по умолчанию равен 24 часам и
настраивается через `STUDENT_CACHE_TTL_SECONDS`.

Neo4j хранит общую производную read-модель. Academic-service синхронизирует
`University -> Institute -> Department -> Specialty`, student-service — группы,
студентов и связи с кафедрой/специальностью, schedule-service — занятия группы.
Каждый сервис пересобирает только принадлежащую ему часть графа из PostgreSQL и
обновляет её после CRUD. Посещаемость в Neo4j не сохраняется.

Повторный запуск безопасен и не создаёт дубликаты. Отдельная проверка уже
загруженного набора:

```bash
docker compose --profile tools run --rm --build verify-data
```

Параметры объёма находятся в `.env.example`. Подробный порядок и критерии
готовности описаны в `DATA_BOOTSTRAP_PLAN.md`.

## JWT-доступ к Gateway

Gateway выдаёт короткоживущий JWT после проверки Argon2-хэша пароля:

```bash
JWT_TOKEN=$(curl -fsS \
  -H "Content-Type: application/json" \
  -d '{"username":"api-user","password":"api-password"}' \
  http://localhost:8000/api/v1/auth/token \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
```

Доступные только для development аккаунты находятся в
`gateway/config/dev-users.json`:

| Логин | Пароль |
|---|---|
| `api-user` | `api-password` |

Ролей и разграничения прав нет: любой корректный access token открывает доступ
ко всем API через Gateway. В production development-файл пользователей должен
заменяться внешним auth provider или секретным volume.

Пример авторизованного запроса:

```bash
curl \
  -H "Authorization: Bearer $JWT_TOKEN" \
  "http://localhost:8000/api/v1/students/students?limit=30&offset=0"
```

Поиск одного студента по номеру билета (повторите команду, чтобы увидеть
`X-Cache: HIT`):

```bash
curl -i \
  -H "Authorization: Bearer $JWT_TOKEN" \
  "http://localhost:8000/api/v1/students/students/by-card/SEED-000001"
```

Проверка Neo4j-проекции и получение структуры конкретного университета:

```bash
curl \
  -H "Authorization: Bearer $JWT_TOKEN" \
  "http://localhost:8000/api/v1/academic/graph/stats"

curl \
  -H "Authorization: Bearer $JWT_TOKEN" \
  "http://localhost:8000/api/v1/academic/graph/universities/<UNIVERSITY_UUID>"
```

Запросы, полностью выполняемые через Neo4j:

```bash
curl -H "Authorization: Bearer $JWT_TOKEN" \
  "http://localhost:8000/api/v1/students/graph/universities/<UNIVERSITY_UUID>/students"

curl -H "Authorization: Bearer $JWT_TOKEN" \
  "http://localhost:8000/api/v1/students/graph/students/<STUDENT_UUID>"

curl -H "Authorization: Bearer $JWT_TOKEN" \
  "http://localhost:8000/api/v1/schedule/students/<STUDENT_UUID>"
```

`verify-data` дополнительно проверяет Redis `HIT`. В чистой базе стандартный
seed создаёт в Neo4j 1464 узла и 1496 связей. Если в PostgreSQL уже есть обычные
данные, verifier не считает их ошибкой: он сравнивает Neo4j со всеми актуальными
данными PostgreSQL, отдельно проверяет размер seed-набора и выполняет новые
graph API по реальному студенту.

## Проверки

```bash
poetry run ruff check .
poetry run pytest -q
docker compose --profile tools config --quiet
```
