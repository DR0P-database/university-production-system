# University Production System

Микросервисный backend университетской системы на FastAPI и PostgreSQL.

## Состав

- `gateway` — единая внешняя точка входа на порту `8000`;
- `academic-service` — структура университета и учебные материалы;
- `student-service` — группы и студенты;
- `schedule-service` — расписание;
- `attendance-service` — посещаемость;
- четыре логические PostgreSQL-базы с отдельными владельцами и Alembic.

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
docker compose --profile tools run --rm seed-data
```

По умолчанию генератор создаёт 2 университета, 34 группы, 1000 студентов,
408 занятий и 4000 отметок посещаемости. В группе находится не больше 30
студентов. Academic, student, schedule и attendance данные записываются только
через API сервиса-владельца своей БД.

Повторный запуск безопасен и не создаёт дубликаты. Отдельная проверка уже
загруженного набора:

```bash
docker compose --profile tools run --rm verify-data
```

Параметры объёма находятся в `.env.example`. Подробный порядок и критерии
готовности описаны в `DATA_BOOTSTRAP_PLAN.md`.

Пример запроса через Gateway с токеном существующего auth-слоя:

```bash
curl \
  -H "Authorization: Bearer $JWT_TOKEN" \
  "http://localhost:8000/api/v1/students/students?limit=30&offset=0"
```

## Проверки

```bash
poetry run ruff check .
poetry run pytest -q
docker compose --profile tools config --quiet
```

Существующая JWT-реализация относится к следующему этапу работ и в рамках
пунктов 1.1–1.3 не изменялась.
