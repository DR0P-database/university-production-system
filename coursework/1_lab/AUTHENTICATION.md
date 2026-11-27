# Аутентификация

В Swagger используйте Authorize с логином и паролем. Gateway выдаёт
USER JWT, подписанный RS256 отдельным пользовательским ключом, на 900 секунд.
Пароль проверяется по PBKDF2-SHA256: случайная соль, 600 000 итераций.
Пароль в токен не входит. Публичный ключ позволяет проверить подпись.

Для вызова отчёта Gateway получает другой токен — SERVICE JWT на 60 секунд:

1. Подписывает короткий client assertion своим identity-ключом
   `gateway_client_private.pem`.
2. Передаёт assertion в `POST /auth/service-token` внутри Gateway.
3. Обработчик проверяет подпись по `clients.json`, client_id, audience,
   scope, срок и уникальность jti. Повтор assertion отклоняется через SQLite.
4. Выпускает SERVICE JWT ключом `service_issuer_private.pem`.

Сервисный токен кэшируется в памяти, обновляется при следующем обращении
за пять секунд до истечения срока. Приватные ключи по сети не передаются.

| Токен | Кто | Проверки |
|---|---|---|
| USER JWT | Пользователь | Подпись пользовательского издателя, `iss=lab1-user-issuer`, `aud=lab1-users`, `token_use=user`, срок и `lab1:read` |
| SERVICE JWT | Клиент-приложение | Подпись сервисного издателя, `iss=lab1-service-issuer`, точная аудитория, `token_use=service`, client_id, срок и scope |
| Client assertion | Клиент, получающий SERVICE JWT | Собственная identity-подпись, `iss=sub=client_id`, `aud=urn:lab1:service-token`, TTL≤60, одноразовый jti |

Вызов Gateway → Report содержит:

```http
Authorization: Bearer <SERVICE JWT>
X-User-Token: <USER JWT>
```

Отчёт проверяет оба токена. Пользовательский токен не проходит вместо сервисного.
Scope сервиса привязан к зарегистрированному клиенту и аудитории:

| Клиент | Аудитория | Scope |
|---|---|---|
| gateway | report-service, rooms-service, hours-service | lab1:read |
| generator | gateway-internal | dataset:state:read, dataset:state:update |
| generator | report-service | lab1:verify |

Генератор получает токены тем же способом, подписывая assertion собственным
`generator_client_private.pem`. С ними читает/публикует состояние загрузки
в Gateway и вызывает пробный отчёт. У генератора и Report нет приватных
ключей издателей. Report получает только публичные ключи проверки.

RSA-ключи — 3072 бит; приватные файлы и учётные данные — 0600, каталог secrets —
0700. Нужные файлы монтируются по одному read-only. SQLite Gateway хранится
на постоянном отдельном томе; replay-защита переживает рестарт.
Ошибки не отражают введённые пароли/токены, ответы имеют `Cache-Control: no-store`.

Внешний порт доступен только на localhost. Это учебный HTTP-стенд;
пользовательский password flow выбран для Swagger.
