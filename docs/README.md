# University Production System

Микросервисный backend университетской системы на FastAPI с PostgreSQL,
MongoDB, Elasticsearch, Redis и Neo4j.

[Учебный стенд ПР №1–3 и ЛР №1–3](../coursework/README.md) · [Описание изменений](../coursework/CHANGES.md).

- [ARCHITECTURE.md](ARCHITECTURE.md) — сервисы, модели данных, хранилища и
  архитектурные правила.
- [TODO.md](../TODO.md) — что реализовано и план дальнейшего развития.

## Состав

| Компонент | Назначение |
|---|---|
| `gateway` | единая внешняя точка, JWT, proxy и объединённый OpenAPI |
| `academic-service` | структура университета, курсы, лекции и материалы |
| `student-service` | группы и студенты |
| `schedule-service` | расписание |
| `attendance-service` | посещаемость |
| `report-service` | отчёт ЛР1 по минимальной посещаемости лекций |
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
