-- Искусственный контрольный набор, не исходные 104 студента ПР3.
SET search_path = practice03, public;
INSERT INTO universities(code,name) VALUES ('TEST','Тестовый университет');
INSERT INTO institutes(university_id,code,name) VALUES (1,'I','Институт');
INSERT INTO departments(institute_id,code,name) VALUES (1,'D','Кафедра');
INSERT INTO specialties(code,name,degree_level,duration_years) VALUES ('TEST','Специальность','bachelor',4);
INSERT INTO department_specialties VALUES (1,1,true);
INSERT INTO study_groups(specialty_id,department_id,code,training_profile,enrollment_year)
VALUES (1,1,'TEST-1','Профиль',2023),(1,1,'TEST-2','Профиль',2023);
INSERT INTO students(group_id,record_book,last_name,first_name,enrollment_date)
SELECT CASE WHEN i=14 THEN 2 ELSE 1 END, 'T'||lpad(i::text,3,'0'),'Студент '||i,'Тест','2023-09-01'
FROM generate_series(1,14) i;
INSERT INTO courses(specialty_id,department_id,code,title,academic_year_start,semester)
VALUES (1,1,'TEST','Контрольный курс',2026,7);
INSERT INTO lectures(course_id,title,lesson_type,order_number)
VALUES (1,'Целостность','lecture',1),(1,'Практика','practice',2);
INSERT INTO lecture_materials(lecture_id,title,position) VALUES (1,'Первый материал',1),(1,'Второй материал',2);
INSERT INTO schedule(lecture_id,group_id,scheduled_date,week_start_date,starts_at,ends_at,classroom,teacher_name,status)
VALUES
 (1,1,'2026-09-07','2026-09-07','09:00','10:30','1','Тест','completed'),
 (1,1,'2026-09-14','2026-09-14','09:00','10:30','1','Тест','completed'),
 (1,1,'2026-09-15','2026-09-14','09:00','10:30','1','Тест','cancelled'),
 (1,1,'2026-09-16','2026-09-14','09:00','10:30','1','Тест','scheduled'),
 (2,1,'2026-09-17','2026-09-14','09:00','10:30','1','Тест','completed');
INSERT INTO attendance(week_start_date,schedule_id,student_id,is_present)
SELECT sc.week_start_date,sc.id,st.id,
 CASE WHEN st.id=1 THEN false WHEN st.id<=11 THEN sc.id=1 ELSE true END
FROM schedule sc CROSS JOIN students st
WHERE sc.id IN (1,2) AND st.id<=13 AND NOT (st.id=13 AND sc.id=2);
