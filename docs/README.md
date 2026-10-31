# University Production System

Микросервисный backend университетской системы на FastAPI с PostgreSQL,
MongoDB, Elasticsearch, Redis и Neo4j.

- [ARCHITECTURE.md](ARCHITECTURE.md) — сервисы, модели данных, хранилища и
  архитектурные правила.
- [TODO.md](TODO.md) — что реализовано и план дальнейшего развития.

## Состав

| Компонент | Назначение |
|---|---|
| `gateway` | единая внешняя точка, JWT, proxy и объединённый OpenAPI |
| `academic-service` | структура университета, курсы, лекции и материалы |
| `student-service` | группы и студенты |
| `schedule-service` | расписание |
| `attendance-service` | посещаемость |
| `tools/data-seeder` | идемпотентное заполнение и проверка демонстрационных данных |

Предметные сервисы доступны только во внутренних Docker networks. Снаружи API
публикуется через Gateway: `http://localhost:8000`.

## Быстрый запуск

Подготовьте development-конфигурацию:

```bash
cp .env.example .env
```

Замените как минимум `JWT_SECRET` и при необходимости локальные пароли. Затем:

```bash
docker compose up -d --build
docker compose ps
```

После успешных healthcheck:

- Swagger UI: `http://localhost:8000/docs`;
- ReDoc: `http://localhost:8000/redoc`;
- Gateway health: `http://localhost:8000/health`.

Полезные development-интерфейсы задаются переменными `.env`:

| Интерфейс | URL по умолчанию |
|---|---|
| pgAdmin | `http://localhost:5050` |
| Redis Commander | `http://localhost:8081` |
| Mongo Express | `http://localhost:8082` |
| Neo4j Browser | `http://localhost:7474` |
| Kibana | `http://localhost:5601` |

## JWT

Development-аккаунт определён в `gateway/config/dev-users.json`:

```text
login:    api-user
password: api-password
```

Получение токена:

```bash
JWT_TOKEN=$(curl -fsS \
  -H "Content-Type: application/json" \
  -d '{"username":"api-user","password":"api-password"}' \
  http://localhost:8000/api/v1/auth/token \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
```

Ролей пока нет. Один корректный токен открывает все API Gateway.

## Примеры запросов

Список студентов:

```bash
curl \
  -H "Authorization: Bearer $JWT_TOKEN" \
  "http://localhost:8000/api/v1/students/students?limit=30&offset=0"
```

Поиск студента по номеру билета. Повторный запрос должен вернуть
`X-Cache: HIT`:

```bash
curl -i \
  -H "Authorization: Bearer $JWT_TOKEN" \
  "http://localhost:8000/api/v1/students/students/by-card/SEED-000001"
```

Поиск описаний и материалов лекций в Elasticsearch:

```bash
curl --get \
  -H "Authorization: Bearer $JWT_TOKEN" \
  --data-urlencode "q=нормализация" \
  --data-urlencode "document_type=material" \
  "http://localhost:8000/api/v1/academic/search/documents"
```

Дополнительные фильтры: `lecture_id`, `content_type`, `limit`, `offset`.

Neo4j-запрос студента с группой и университетом:

```bash
curl \
  -H "Authorization: Bearer $JWT_TOKEN" \
  "http://localhost:8000/api/v1/students/graph/students/<STUDENT_UUID>"
```

Расписание студента из Neo4j:

```bash
curl \
  -H "Authorization: Bearer $JWT_TOKEN" \
  "http://localhost:8000/api/v1/schedule/students/<STUDENT_UUID>"
```

Остальные endpoints и их схемы доступны в Swagger.

## Тестовые данные

Seeder пишет данные только через API сервисов-владельцев:

```bash
docker compose --profile tools build seed-data verify-data
docker compose --profile tools run --rm seed-data
```

Собирать tools достаточно один раз после изменения `seeder.py`. Не добавляйте
`--build` к каждому `run`: иначе Compose может без необходимости пересобрать и
пересоздать зависимые сервисы.

Стандартный набор содержит:

- 2 университета, 4 института, 8 кафедр и 8 специальностей;
- 16 курсов, 96 лекций и 192 текстовых материала;
- 1000 студентов в 34 группах, не больше 30 человек в группе;
- 408 занятий и 4000 отметок посещаемости;
- 288 поисковых документов Elasticsearch;
- 1464 узла и 1496 связей Neo4j в чистой базе.

Повторный запуск идемпотентен. Проверка уже загруженного набора:

```bash
docker compose --profile tools run --rm verify-data
```

Объёмы настраиваются через `SEED_*` в `.env`.

## Локальные проверки

```bash
poetry run ruff check .
poetry run pytest -q
docker compose --profile tools config --quiet
```

Остановка контейнеров:

```bash
docker compose down
```

Полное удаление development-данных выполняйте только осознанно:

```bash
docker compose down -v
```

## Структура репозитория

```text
gateway/                    API Gateway и JWT
services/academic-service/  academic domain, MongoDB, Elasticsearch, Neo4j
services/student-service/   students, Redis, Neo4j
services/schedule-service/  schedule, Neo4j
services/attendance-service attendance
databases/                  Compose-конфигурация хранилищ
tools/data-seeder/          seed и verify
tests/                      contract и business-rule tests
```
