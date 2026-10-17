const databaseName = process.env.MONGODB_ACADEMIC_DB;
const username = process.env.MONGODB_ACADEMIC_USER;
const password = process.env.MONGODB_ACADEMIC_PASSWORD;
const academicDatabase = db.getSiblingDB(databaseName);
const roles = [{ role: "readWrite", db: databaseName }];

if (academicDatabase.getUser(username)) {
  academicDatabase.updateUser(username, { pwd: password, roles });
} else {
  academicDatabase.createUser({ user: username, pwd: password, roles });
}
