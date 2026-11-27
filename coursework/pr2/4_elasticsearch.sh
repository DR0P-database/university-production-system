#!/usr/bin/env bash
cd "$(dirname "$0")/.."
# ПР2, Elasticsearch: курсы с полнотекстовым описанием (русский анализатор).

ES=http://127.0.0.1:19200
q() { local m=$1 p=$2; shift 2; echo "> $m $p"; curl -s -X "$m" "$ES$p" -H 'Content-Type: application/json' "$@"; echo; }
step() { printf '\n===== %s =====\n' "$1"; }

step "1. Создание хранилища (индекс courses с маппингом)"
q PUT /courses -d '{
  "settings": { "number_of_shards": 1, "number_of_replicas": 0 },
  "mappings": { "properties": {
    "code":        { "type": "keyword" },
    "title":       { "type": "text", "analyzer": "russian", "fields": { "raw": { "type": "keyword" } } },
    "kind":        { "type": "keyword" },
    "semester":    { "type": "integer" },
    "hours":       { "type": "integer" },
    "description": { "type": "text", "analyzer": "russian" },
    "tags":        { "type": "keyword" }
  } }
}'

step "2. Добавление данных (bulk)"
curl -s -X POST "$ES/courses/_bulk?refresh=true" -H 'Content-Type: application/x-ndjson' --data-binary @- <<'EOF' | python3 -c 'import json,sys; r=json.load(sys.stdin); print("errors:", r["errors"], "items:", len(r["items"]))'
{"index":{"_id":"ARCH"}}
{"code":"ARCH","title":"Проектирование архитектуры ПО","kind":"обязательный","semester":7,"hours":72,"description":"Архитектурные стили и паттерны: монолит, микросервисы, событийная архитектура. Нотации C4 и DFD, API Gateway, JWT-аутентификация, polyglot persistence и выбор хранилищ данных.","tags":["архитектура","микросервисы","базы данных"]}
{"index":{"_id":"ML"}}
{"code":"ML","title":"Машинное обучение","kind":"обязательный","semester":7,"hours":72,"description":"Линейные модели, деревья решений, градиентный бустинг и нейронные сети. Подготовка данных, кросс-валидация и метрики качества классификации и регрессии.","tags":["анализ данных","нейросети"]}
{"index":{"_id":"TEST"}}
{"code":"TEST","title":"Тестирование ПО","kind":"обязательный","semester":7,"hours":54,"description":"Модульное, интеграционное и нагрузочное тестирование. Автоматизация тестов, непрерывная интеграция, покрытие кода и тестовые двойники.","tags":["качество","CI"]}
{"index":{"_id":"CV"}}
{"code":"CV","title":"Компьютерное зрение","kind":"по выбору","semester":7,"hours":54,"description":"Обработка изображений, свёрточные нейронные сети, детекция и сегментация объектов. Практика на OpenCV и PyTorch с использованием GPU.","tags":["нейросети","изображения"]}
{"index":{"_id":"BC"}}
{"code":"BC","title":"Блокчейн-технологии","kind":"по выбору","semester":7,"hours":54,"description":"Распределённые реестры, алгоритмы консенсуса, смарт-контракты и криптографические примитивы. Разработка децентрализованных приложений.","tags":["криптография","распределённые системы"]}
EOF
q GET '/courses/_count'

step "3. Чтение по ключу (_id = CV)"
q GET '/courses/_doc/CV?pretty'
echo "Полнотекстовый поиск по описанию: «нейронная сеть» (найдёт и «нейронные сети» благодаря стеммингу)"
q GET '/courses/_search?filter_path=hits.hits._id,hits.hits._score,hits.hits._source.title&pretty' -d '{
  "query": { "match": { "description": "нейронная сеть" } }
}'

step "4. Изменение и сохранение"
q POST '/courses/_update/CV?refresh=true' -d '{
  "doc": { "hours": 72, "description": "Обработка изображений и видео, свёрточные нейронные сети, трансформеры, детекция и сегментация объектов. Практика на OpenCV и PyTorch с использованием GPU." }
}'
q GET '/courses/_doc/CV?filter_path=_version,_source.hours,_source.description&pretty'

step "5. Удаление записи"
q DELETE '/courses/_doc/BC?refresh=true'
q GET '/courses/_count'

step "6. Удаление хранилища"
q DELETE /courses
q GET '/_cat/indices/courses?v'
