#!/usr/bin/env bash
# ПР1: проверка доступности всех служб, места хранения данных и лог-записей.
# Запуск из корня проекта: bash pr1/check.sh

cd "$(dirname "$0")/.." || exit 1

step() { printf '\n========== %s ==========\n' "$1"; }

step "Статус контейнеров"
docker compose ps --format 'table {{.Name}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

step "Redis: PING"
docker compose exec -T redis redis-cli -a password --no-auth-warning PING
docker compose exec -T redis redis-cli -a password --no-auth-warning CONFIG GET dir
docker compose exec -T redis redis-cli -a password --no-auth-warning CONFIG GET logfile

step "MongoDB: ping"
docker compose exec -T mongodb mongosh -u admin -p password --authenticationDatabase admin --quiet --eval '
  printjson(db.adminCommand({ ping: 1 }));
  print("version:", db.version());
  const opts = db.adminCommand({ getCmdLineOpts: 1 }).parsed;
  print("dbPath:", (opts.storage && opts.storage.dbPath) || "/data/db (по умолчанию)");
  print("logPath:", opts.systemLog.path);'

step "Neo4j: RETURN 1"
docker compose exec -T neo4j cypher-shell -u neo4j -p password \
  "CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition;"
docker compose exec -T neo4j cypher-shell -u neo4j -p password \
  "CALL dbms.listConfig() YIELD name, value WHERE name IN ['server.directories.data','server.directories.logs'] RETURN name, value;"

step "Elasticsearch: cluster health"
curl -s 'http://127.0.0.1:19200/_cluster/health?pretty'
curl -s 'http://127.0.0.1:19200/_nodes/settings?filter_path=nodes.*.settings.path&pretty'

step "PostgreSQL: SELECT version()"
docker compose exec -T postgres psql -U user -d main_db -c 'SELECT version();'
docker compose exec -T postgres psql -U user -d main_db -c 'SHOW data_directory;' -c 'SHOW log_directory;' -c 'SHOW logging_collector;'

step "Файлы данных на хосте (./data)"
du -sh data/* 2>/dev/null

step "Лог-файлы на хосте (./logs)"
find logs -type f -exec ls -lh {} \; | awk '{print $5, $NF}'

step "Последние строки логов"
for f in logs/redis/redis.log logs/mongodb/mongod.log logs/neo4j/neo4j.log; do
  echo "--- $f"; tail -n 3 "$f" 2>/dev/null
done
echo "--- elasticsearch (в Docker основной лог идёт в stdout, в ./logs/elasticsearch — GC-логи JVM)"
docker compose logs --tail 3 elasticsearch 2>&1 | cut -c1-300
echo "--- logs/postgres"; tail -n 3 "$(ls -t logs/postgres/*.log 2>/dev/null | head -1)" 2>/dev/null
