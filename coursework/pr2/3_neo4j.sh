#!/usr/bin/env bash
cd "$(dirname "$0")/.."
# ПР2, Neo4j: связи группа — студент — курс с учётом курсов по выбору.
# Community-редакция не умеет создавать отдельные БД, поэтому «хранилище» —
# набор ограничений уникальности (схема) + узлы с метками Group/Student/Course.

c() { echo "cypher> $1"; docker compose exec -T neo4j cypher-shell -u neo4j -p password --format plain "$1"; echo; }
step() { printf '\n===== %s =====\n' "$1"; }

step "1. Создание хранилища (ограничения уникальности ключей)"
c "CREATE CONSTRAINT group_name IF NOT EXISTS FOR (g:Group) REQUIRE g.name IS UNIQUE;"
c "CREATE CONSTRAINT student_rb IF NOT EXISTS FOR (s:Student) REQUIRE s.record_book IS UNIQUE;"
c "CREATE CONSTRAINT course_code IF NOT EXISTS FOR (c:Course) REQUIRE c.code IS UNIQUE;"
c "SHOW CONSTRAINTS YIELD name, labelsOrTypes, properties;"

step "2. Добавление данных"
c "CREATE (:Group {name: 'ПР2-ДЕМО-01', specialty: 'Программная инженерия', enrollment_year: 2022});"
c "UNWIND [
  {code:'ARCH', title:'Проектирование архитектуры ПО', kind:'обязательный'},
  {code:'ML',   title:'Машинное обучение',             kind:'обязательный'},
  {code:'TEST', title:'Тестирование ПО',               kind:'обязательный'},
  {code:'CV',   title:'Компьютерное зрение',           kind:'по выбору'},
  {code:'BC',   title:'Блокчейн-технологии',           kind:'по выбору'}
] AS row CREATE (:Course {code: row.code, title: row.title, kind: row.kind});"
c "UNWIND [
  ['ПР2-0001','Студент 01'],     ['ПР2-0002','Студент 02'],
  ['ПР2-0003','Студент 03'],     ['ПР2-0004','Студент 04'],
  ['ПР2-0005','Студент 05'],        ['ПР2-0006','Студент 06'],
  ['ПР2-0007','Студент 07'], ['ПР2-0008','Студент 08']
] AS row
MATCH (g:Group {name: 'ПР2-ДЕМО-01'})
CREATE (:Student {record_book: row[0], full_name: row[1]})-[:MEMBER_OF]->(g);"
# Обязательные курсы изучает вся группа
c "MATCH (g:Group {name: 'ПР2-ДЕМО-01'}), (c:Course {kind: 'обязательный'}) CREATE (g)-[:STUDIES]->(c);"
# Курс по выбору выбирает каждый студент сам
c "UNWIND [
  ['ПР2-0001','CV'], ['ПР2-0002','BC'], ['ПР2-0003','CV'], ['ПР2-0004','CV'],
  ['ПР2-0005','BC'], ['ПР2-0006','CV'], ['ПР2-0007','BC'], ['ПР2-0008','CV']
] AS row
MATCH (s:Student {record_book: row[0]}), (c:Course {code: row[1]})
CREATE (s)-[:CHOSE {semester: 7}]->(c);"
c "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS cnt;"
c "MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS cnt;"

step "3. Чтение по ключу (все курсы студента ПР2-0003)"
c "MATCH (s:Student {record_book: 'ПР2-0003'})-[:MEMBER_OF]->(g:Group)
OPTIONAL MATCH (g)-[:STUDIES]->(req:Course)
OPTIONAL MATCH (s)-[:CHOSE]->(el:Course)
RETURN s.full_name AS student, g.name AS grp,
       collect(DISTINCT req.title) AS required, collect(DISTINCT el.title) AS elective;"
c "MATCH (s:Student)-[:CHOSE]->(c:Course {code: 'CV'}) RETURN c.title AS course, collect(s.full_name) AS students;"

step "4. Изменение и сохранение (ПР2-0003 меняет курс по выбору CV -> BC)"
c "MATCH (s:Student {record_book: 'ПР2-0003'})-[r:CHOSE]->(:Course {code: 'CV'}) DELETE r
WITH s MATCH (bc:Course {code: 'BC'}) CREATE (s)-[:CHOSE {semester: 7}]->(bc);"
c "MATCH (s:Student {record_book: 'ПР2-0003'}) SET s.email = 'student03.updated@example.test' RETURN s;"
c "MATCH (s:Student {record_book: 'ПР2-0003'})-[:CHOSE]->(c) RETURN s.full_name, c.title;"

step "5. Удаление записей (студент ПР2-0008 вместе со связями)"
c "MATCH (s:Student {record_book: 'ПР2-0008'}) DETACH DELETE s;"
c "MATCH (s:Student) RETURN count(s) AS students;"

step "6. Удаление хранилища"
c "MATCH (n) WHERE n:Group OR n:Student OR n:Course DETACH DELETE n;"
c "DROP CONSTRAINT group_name IF EXISTS;"
c "DROP CONSTRAINT student_rb IF EXISTS;"
c "DROP CONSTRAINT course_code IF EXISTS;"
c "MATCH (n) RETURN count(n) AS nodes;"
c "SHOW CONSTRAINTS;"
