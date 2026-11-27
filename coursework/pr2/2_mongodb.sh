#!/usr/bin/env bash
cd "$(dirname "$0")/.."
# ПР2, MongoDB: один документ на группу — данные группы и её состав вложенным массивом.

docker compose exec -T mongodb mongosh -u admin -p password --authenticationDatabase admin --quiet <<'JS'
const step = s => print(`\n===== ${s} =====`);
const show = x => printjson(x);

step("1. Создание хранилища (БД university, коллекция groups со схемой-валидатором)");
db = db.getSiblingDB("university");
db.createCollection("groups", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["_id", "specialty", "students"],
    properties: {
      students: { bsonType: "array", items: { bsonType: "object", required: ["record_book", "full_name"] } }
    }
  } }
});
show(db.getCollectionNames());

step("2. Добавление данных");
show(db.groups.insertOne({
  _id: "ПР2-ДЕМО-01",
  specialty: { code: "09.03.04", name: "Программная инженерия" },
  institute: "Институт информационных технологий",
  enrollment_year: 2022,
  semester: 7,
  curator: "Куратор демогруппы",
  students: [
    { record_book: "ПР2-0001", full_name: "Студент 01",     is_leader: true  },
    { record_book: "ПР2-0002", full_name: "Студент 02",      is_leader: false },
    { record_book: "ПР2-0003", full_name: "Студент 03",     is_leader: false },
    { record_book: "ПР2-0004", full_name: "Студент 04",    is_leader: false },
    { record_book: "ПР2-0005", full_name: "Студент 05",        is_leader: false },
    { record_book: "ПР2-0006", full_name: "Студент 06",   is_leader: false },
    { record_book: "ПР2-0007", full_name: "Студент 07", is_leader: false },
    { record_book: "ПР2-0008", full_name: "Студент 08",    is_leader: false }
  ],
  courses: [
    { code: "ARCH", title: "Проектирование архитектуры ПО", kind: "обязательный" },
    { code: "ML",   title: "Машинное обучение",             kind: "обязательный" },
    { code: "TEST", title: "Тестирование ПО",               kind: "обязательный" },
    { code: "CV",   title: "Компьютерное зрение",           kind: "по выбору" },
    { code: "BC",   title: "Блокчейн-технологии",           kind: "по выбору" }
  ]
}));
show(db.groups.countDocuments());

step("3. Чтение по ключу (_id = ПР2-ДЕМО-01)");
show(db.groups.findOne({ _id: "ПР2-ДЕМО-01" }));
print("Только один студент из состава группы:");
show(db.groups.findOne({ _id: "ПР2-ДЕМО-01" }, { students: { $elemMatch: { record_book: "ПР2-0003" } } }));

step("4. Изменение и сохранение");
show(db.groups.updateOne({ _id: "ПР2-ДЕМО-01" }, { $set: { curator: "Сергеев С.С." } }));
show(db.groups.updateOne(
  { _id: "ПР2-ДЕМО-01", "students.record_book": "ПР2-0003" },
  { $set: { "students.$.email": "student03.updated@example.test" } }
));
show(db.groups.findOne({ _id: "ПР2-ДЕМО-01" }, { curator: 1, students: { $elemMatch: { record_book: "ПР2-0003" } } }));

step("5. Удаление записей");
print("Удаляем студента ПР2-0008 из состава группы:");
show(db.groups.updateOne({ _id: "ПР2-ДЕМО-01" }, { $pull: { students: { record_book: "ПР2-0008" } } }));
print("Студентов в группе:", db.groups.findOne({ _id: "ПР2-ДЕМО-01" }).students.length);
print("Удаляем сам документ группы:");
show(db.groups.deleteOne({ _id: "ПР2-ДЕМО-01" }));
show(db.groups.countDocuments());

step("6. Удаление хранилища");
show(db.groups.drop());
show(db.dropDatabase());
show(db.adminCommand({ listDatabases: 1, nameOnly: true }).databases.map(d => d.name));
JS
