#https://playground.structurizr.com/
workspace "University Production System" "C4-модель университетской системы" {
    model {
        user = person "Пользователь API" "Получает токен и отправляет запросы через HTTP-клиент."

        university = softwareSystem "University Production System" "Учебная структура, студенты, расписание, посещаемость и материалы." {
            gateway = container "API Gateway" "Выдаёт и проверяет JWT, маршрутизирует запросы в сервисы и объединяет OpenAPI." "FastAPI"
            academic = container "Academic Service" "Управляет учебной структурой, специальностями, курсами, лекциями и материалами." "FastAPI"
            student = container "Student Service" "Управляет группами и студентами." "FastAPI"
            schedule = container "Schedule Service" "Управляет расписанием занятий." "FastAPI"
            attendance = container "Attendance Service" "Управляет отметками посещаемости." "FastAPI"
            roomReports = container "Room Report Service — ЛР2" "Рассчитывает вместимость и технические требования занятий курса." "FastAPI"
            reports = container "Report Service — ЛР1" "Формирует рейтинг посещаемости лекций по термину и периоду." "FastAPI"

            academicDb = container "academic_db" "Учебная структура и ссылки на материалы." "PostgreSQL" "Database"
            studentDb = container "student_db" "Группы и студенты." "PostgreSQL" "Database"
            scheduleDb = container "schedule_db" "Расписание занятий." "PostgreSQL" "Database"
            attendanceDb = container "attendance_db" "Отметки посещаемости." "PostgreSQL" "Database"
            mongo = container "MongoDB" "Содержимое материалов и метаданные." "MongoDB" "Database"
            search = container "Elasticsearch" "Полнотекстовый индекс описаний и материалов." "Elasticsearch" "Database"
            redis = container "Redis" "Кэш студентов по номеру билета." "Redis" "Database"
            neo = container "Neo4j" "Граф учебной структуры, групп, студентов и расписания." "Neo4j" "Database"
        }

        user -> gateway "Получает JWT и вызывает API с Bearer token" "HTTP/JSON"
        gateway -> academic "Передаёт запросы" "HTTP/JSON"
        gateway -> student "Передаёт запросы" "HTTP/JSON"
        gateway -> schedule "Передаёт запросы" "HTTP/JSON"
        gateway -> attendance "Передаёт запросы" "HTTP/JSON"
        gateway -> reports "Передаёт запрос отчёта после проверки JWT" "HTTP/JSON"

        gateway -> roomReports "Передаёт запрос ЛР2 после проверки JWT" "HTTP/JSON"
        roomReports -> academic "Получает курс, занятия и требования" "HTTP/JSON"
        roomReports -> student "Получает группы набора и активных студентов" "HTTP/JSON"

        reports -> academic "Ищет лекции по термину или фразе" "HTTP/JSON"
        reports -> student "Получает группы и студентов" "HTTP/JSON"
        reports -> schedule "Получает проведённые занятия" "HTTP/JSON"
        reports -> attendance "Получает отметки посещаемости" "HTTP/JSON"

        student -> academic "Проверяет кафедры и специальности" "HTTP/JSON"
        schedule -> academic "Проверяет лекции и курсы" "HTTP/JSON"
        schedule -> student "Проверяет группы" "HTTP/JSON"
        attendance -> schedule "Получает данные занятия" "HTTP/JSON"
        attendance -> student "Получает данные студента" "HTTP/JSON"

        academic -> academicDb "Читает и изменяет учебные данные" "SQL"
        student -> studentDb "Читает и изменяет студентов и группы" "SQL"
        schedule -> scheduleDb "Читает и изменяет расписание" "SQL"
        attendance -> attendanceDb "Читает и изменяет посещаемость" "SQL"
        academic -> mongo "Читает и изменяет содержимое материалов" "MongoDB protocol"
        academic -> search "Обновляет индекс и выполняет поиск" "HTTP"
        student -> redis "Читает и обновляет кэш" "Redis protocol"
        academic -> neo "Обновляет и читает учебную структуру" "Bolt"
        student -> neo "Обновляет и читает группы и студентов" "Bolt"
        schedule -> neo "Обновляет и читает расписание" "Bolt"
    }

    views {
        systemContext university "Context" {
            title "C4: контекст системы"
            include *
            autoLayout lr
        }

        container university "API-and-services" {
            title "C4: пользователь, API Gateway и сервисы"
            include user gateway reports roomReports academic student schedule attendance
            autoLayout lr
        }

        container university "Containers" {
            title "C4: сервисы и хранилища"
            include *
            autoLayout lr
        }

        styles {
            element "Person" {
                shape Person
                background #08427b
                color #ffffff
            }
            element "Software System" {
                background #1168bd
                color #ffffff
            }
            element "Container" {
                background #438dd5
                color #ffffff
            }
            element "Database" {
                shape Cylinder
                background #438dd5
                color #ffffff
            }
        }
    }
}
