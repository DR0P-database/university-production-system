ALTER TABLE practice03.lectures ADD COLUMN IF NOT EXISTS equipment_requirements text;

-- Дополняем справочник синтетического набора, сохраняя расписание и отметки.
UPDATE practice03.lectures l
SET requires_equipment = true,
    equipment_requirements = CASE WHEN l.lesson_type = 'lab'
                                THEN 'Компьютеры с учебным ПО'
                                ELSE 'Проектор и экран' END
FROM practice03.courses c
WHERE c.id = l.course_id AND c.code LIKE 'demo\_%' ESCAPE '\'
  AND (l.requires_equipment OR (l.lesson_type = 'lecture' AND l.order_number = 1))
  AND l.equipment_requirements IS NULL;

UPDATE practice03.lectures l
SET tags = array_append(l.tags, 'специальная-дисциплина')
FROM practice03.courses c
WHERE c.id = l.course_id AND c.code IN ('demo_arch', 'demo_storage', 'demo_security')
  AND l.lesson_type = 'lecture' AND l.order_number IN (1, 6)
  AND NOT 'специальная-дисциплина' = ANY(l.tags);
