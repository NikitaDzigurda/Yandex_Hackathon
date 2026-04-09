# API Reference (полный справочник)

Полный перечень методов бэкенда из `app/main.py` и подключенных роутеров:

- `auth` (`/api/auth/*`)
- `projects` (`/api/projects/*`)
- `showcase` (`/api/showcase`)
- `integrations/admin` (`/api/admin/telegram-subscribers/*`)
- системный health-check (`/health`)

## 1) Общие правила

### Базовый URL

- Локально обычно: `http://localhost:8000`
- Все API-методы (кроме `/health`) идут под префиксом `/api`.

### Формат авторизации

- Используется Bearer JWT в заголовке:
  - `Authorization: Bearer <token>`
- Токен выдается методами:
  - `POST /api/auth/register`
  - `POST /api/auth/login`

### Роли

- `submitter`
- `reviewer`
- `admin`

### Правила доступа по ролям

- `get_current_user`: любой валидный JWT.
- `require_submitter`: `submitter` или `admin`.
- `require_reviewer`: `reviewer` или `admin`.
- `require_admin`: только `admin`.

### Общие ошибки авторизации

- `401 Not authenticated` — нет Bearer токена.
- `401 Invalid token` / `Invalid token subject` — токен невалидный.
- `401 User not found` — пользователь из токена не найден или `is_active=false`.
- `403 ... required` — роль недостаточна для вызова метода.

### Справочные enum значения

#### `UserRole`

- `submitter`
- `reviewer`
- `admin`

#### `ProjectStatus`

- `draft`
- `submitted`
- `under_review`
- `revision_requested`
- `rejected`
- `accepted_for_research`
- `deep_research_running`
- `deep_research_completed`
- `on_showcase`
- `archived`

#### `HumanDecision`

- `pending`
- `approve`
- `reject`
- `request_revision`

#### `RunType`

- `evaluation`
- `deep_research`

#### `RunStatus`

- `queued`
- `running`
- `completed`
- `failed`

---

## 2) Системный endpoint

### `GET /health`

**Кто может вызывать:** любой (без токена)  
**Назначение:** проверка живости сервиса.

**Response 200**

```json
{"ok": true}
```

---

## 3) Auth API

Префикс: `/api/auth`

### `POST /api/auth/register`

**Кто может вызывать:** любой (без токена)  
**Назначение:** регистрация пользователя и выдача JWT.

**Request body**

```json
{
  "email": "user@example.com",
  "password": "very-strong-password",
  "full_name": "Ivan Ivanov",
  "role": "submitter"
}
```

**Поля**

- `email`: валидный email.
- `password`: минимум 8 символов.
- `full_name`: строка.
- `role`: `submitter | reviewer | admin`.

**Response 200**

```json
{
  "ok": true,
  "access_token": "<jwt>",
  "token_type": "bearer"
}
```

**Ошибки**

- `409 Email already registered`
- `422` ошибки валидации тела запроса

---

### `POST /api/auth/login`

**Кто может вызывать:** любой (без токена)  
**Назначение:** вход по email/password и выдача JWT.

**Request body**

```json
{
  "email": "user@example.com",
  "password": "very-strong-password"
}
```

**Response 200**

```json
{
  "ok": true,
  "access_token": "<jwt>",
  "token_type": "bearer"
}
```

**Ошибки**

- `401 Invalid credentials`
- `403 Account disabled`
- `422` ошибки валидации тела

---

### `GET /api/auth/me`

**Кто может вызывать:** любой авторизованный пользователь  
**Назначение:** вернуть профиль текущего пользователя.

**Headers**

- `Authorization: Bearer <jwt>`

**Response 200**

```json
{
  "id": "uuid",
  "email": "user@example.com",
  "full_name": "Ivan Ivanov",
  "role": "submitter"
}
```

**Ошибки**

- `401` (см. общие ошибки авторизации)

---

## 4) Projects API

Префикс: `/api/projects`

### 4.1 Проекты (CRUD и workflow)

### `POST /api/projects`

**Кто может вызывать:** `submitter`, `admin`  
**Назначение:** создать проект в статусе `draft`.

**Request body**

```json
{
  "title": "My Project",
  "description": "Описание",
  "task": "Что нужно сделать",
  "stage": "MVP",
  "deadlines": "Q3"
}
```

**Response 200 (`ProjectOutEnvelope`)**

```json
{
  "ok": true,
  "result": {
    "id": "uuid",
    "submitter_id": "uuid",
    "reviewer_id": null,
    "title": "My Project",
    "description": "Описание",
    "task": "Что нужно сделать",
    "stage": "MVP",
    "deadlines": "Q3",
    "status": "draft",
    "human_decision": "pending",
    "reviewer_comment": null,
    "created_at": "2026-01-01T10:00:00Z",
    "updated_at": "2026-01-01T10:00:00Z"
  }
}
```

**Ошибки**

- `403 Submitter or admin required`
- `422` ошибки валидации

---

### `GET /api/projects/mine`

**Кто может вызывать:** `submitter`, `admin`  
**Назначение:** список проектов, где текущий пользователь — submitter.

**Response 200**

- Массив `ProjectOut[]`, сортировка `created_at desc`.

**Ошибки**

- `403 Submitter or admin required`

---

### `GET /api/projects/review-queue`

**Кто может вызывать:** `reviewer`, `admin`  
**Назначение:** очередь на ревью.

**Фильтр статусов**

- `submitted`
- `under_review`
- `revision_requested`

**Response 200**

- Массив `ProjectOut[]`, сортировка `created_at asc`.

**Ошибки**

- `403 Reviewer or admin required`

---

### `GET /api/projects/{project_id}`

**Кто может вызывать:**

- `reviewer`/`admin` — любой проект;
- `submitter` — только свой проект.

**Назначение:** получить карточку проекта.

**Response 200**

- `ProjectOutEnvelope`

**Ошибки**

- `404 Project not found`
- `403 Forbidden` (нет прав читать проект)

---

### `PATCH /api/projects/{project_id}`

**Кто может вызывать:** `submitter`, `admin`, но только владелец проекта (по `submitter_id`)  
**Назначение:** частичное обновление проекта.

**Разрешенные статусы для редактирования**

- `draft`
- `revision_requested` (после обновления автоматически переводится обратно в `draft`)

**Request body (любой поднабор полей)**

```json
{
  "title": "Updated title",
  "description": "Updated description",
  "task": "Updated task",
  "stage": "Pilot",
  "deadlines": "Q4"
}
```

**Response 200**

- `ProjectOutEnvelope`

**Ошибки**

- `404 Project not found`
- `403 Not your project`
- `400 Cannot edit in current status`

---

### `POST /api/projects/{project_id}/submit`

**Кто может вызывать:** `submitter`, `admin`, но только владелец проекта  
**Назначение:** отправить проект на рассмотрение.

**Условия**

- Разрешено только из статусов:
  - `draft`
  - `revision_requested`

**Побочные эффекты**

- `status -> submitted`
- `human_decision -> pending`
- выполняется `commit`
- запускается фоновая рассылка в Telegram (если настроена и есть подписчики)

**Response 200**

- `ProjectOutEnvelope`

**Ошибки**

- `404 Project not found`
- `403 Not your project`
- `400 Cannot submit from this status`

---

### `POST /api/projects/{project_id}/review`

**Кто может вызывать:** `reviewer`, `admin`  
**Назначение:** решение ревьюера по проекту.

**Допустимые текущие статусы проекта**

- `submitted`
- `under_review`
- `revision_requested`

**Request body**

```json
{
  "decision": "approve",
  "comment": "OK"
}
```

`decision`:

- `approve` -> `status = accepted_for_research`
- `reject` -> `status = rejected`
- `request_revision` -> `status = revision_requested`
- иначе (формально не должен прийти из schema) -> `under_review`

Также устанавливаются:

- `reviewer_id = current_user.id`
- `reviewer_comment = comment`
- `human_decision = decision`

**Response 200**

- `ReviewEnvelope` (`{ok, result: ProjectOut}`)

**Ошибки**

- `404 Project not found`
- `400 Project not in reviewable state`
- `403 Reviewer or admin required`

---

### 4.2 Запуски агентов (evaluation / deep research)

### `POST /api/projects/{project_id}/runs/evaluation`

**Кто может вызывать:** `reviewer`, `admin`  
**Назначение:** запустить evaluation pipeline (5 агентов).

**Разрешенные статусы проекта**

- `submitted`
- `under_review`
- `revision_requested`
- `accepted_for_research`

Если статус `submitted`, он переключается в `under_review`.

**Request body**

```json
{
  "evaluation_prompt": "опциональный системный контекст",
  "tracker_context": "",
  "source_craft_context": "",
  "continue_on_agent_error": false
}
```

**Что создается**

- запись `agent_runs` с:
  - `run_type = evaluation`
  - `status = queued`
  - `total_agents = 5`

После `commit` стартует background thread.

**Response 200**

- `AgentRunOut`

**Ошибки**

- `404 Project not found`
- `400 Wrong status for evaluation`
- `403 Reviewer or admin required`

---

### `POST /api/projects/{project_id}/runs/deep-research`

**Кто может вызывать:** `reviewer`, `admin`  
**Назначение:** запустить deep research pipeline (9 агентов).

**Условие**

- проект должен быть в `accepted_for_research`.

**Request body**

```json
{
  "tracker_context": "",
  "source_craft_context": "",
  "continue_on_agent_error": false
}
```

**Что создается**

- запись `agent_runs` с:
  - `run_type = deep_research`
  - `status = queued`
  - `total_agents = 9`
- статус проекта переключается в `deep_research_running`

После `commit` стартует background thread.

**Response 200**

- `AgentRunOut`

**Ошибки**

- `404 Project not found`
- `400 Project must be accepted for research first`
- `403 Reviewer or admin required`

---

### `GET /api/projects/{project_id}/runs`

**Кто может вызывать:**

- `reviewer`/`admin` — любой проект;
- `submitter` — только свой.

**Назначение:** список run-ов проекта.

**Response 200**

- `AgentRunOut[]`, сортировка `created_at desc`.
- Для активных job может возвращаться прогресс из in-memory `JOBS`.

**Ошибки**

- `404 Project not found`
- `403 Forbidden`

---

### `GET /api/projects/{project_id}/runs/{run_id}`

**Кто может вызывать:** как `GET project` (читатели проекта)  
**Назначение:** детали конкретного запуска.

**Response 200 (`AgentRunDetailOut`)**

```json
{
  "ok": true,
  "result": {
    "id": "uuid",
    "project_id": "uuid",
    "run_type": "deep_research",
    "status": "running",
    "current_agent": "research_agent_3",
    "completed_agents": 2,
    "total_agents": 9,
    "evaluation_prompt": null,
    "error_text": null,
    "started_at": "2026-01-01T10:00:00Z",
    "finished_at": null,
    "created_at": "2026-01-01T10:00:00Z"
  },
  "payload": {},
  "progress": {}
}
```

`payload`:

- итоговый `result_json` (обычно после `completed`).

`progress`:

- промежуточный прогресс во время выполнения.

**Ошибки**

- `404 Project not found`
- `404 Run not found`
- `403 Forbidden`

---

### `GET /api/projects/{project_id}/deep-research/latest`

**Кто может вызывать:** читатели проекта (`submitter`-owner, `reviewer`, `admin`)  
**Назначение:** получить последний завершенный deep research для проекта.

**Дополнительные условия**

- проект должен быть в одном из статусов:
  - `accepted_for_research`
  - `deep_research_running`
  - `deep_research_completed`
  - `on_showcase`
  - `archived`

Берется последний `agent_runs` с:

- `run_type = deep_research`
- `status = completed`

**Response 200 (`LatestDeepResearchOut`)**

```json
{
  "ok": true,
  "project_id": "uuid",
  "run_id": "uuid",
  "finished_at": "2026-01-01T11:30:00Z",
  "payload": {
    "executive_summary": "...",
    "roadmap": "...",
    "final_report": "..."
  }
}
```

**Ошибки**

- `404 Project not found`
- `403 Forbidden` (нет прав читать проект)
- `403 Deep research is available only after the project is accepted for research`
- `404 No completed deep research for this project`
- `404 Deep research run has no stored result yet`

---

### `POST /api/projects/{project_id}/runs/{run_id}/export/tracker`

**Кто может вызывать:** `reviewer`, `admin`  
**Назначение:** выгрузить задачи из завершенного deep research run в Yandex Tracker.

**Условия**

- `run_type == deep_research`
- `status == completed`
- в run есть `result_json`
- интеграция Tracker настроена (`yandex_tracker_*` env)

**Request body**

```json
{
  "queue": "TREK"
}
```

`queue` опционально; если `null`/не передано, используется `YANDEX_TRACKER_DEFAULT_QUEUE`.

**Response 200 (`ExportTasksOut`)**

```json
{
  "ok": true,
  "tasks_planned": 12,
  "created": [
    {"summary": "Task 1", "tracker": {"key": "TREK-123"}}
  ],
  "errors": [
    "Task 5: <error details>"
  ]
}
```

**Важно**

- Возможен частичный успех: часть задач в `created`, часть в `errors`.

**Ошибки**

- `404 Project not found`
- `403 Forbidden` (нечитабельный проект)
- `403 Reviewer or admin required`
- `404 Run not found`
- `400 Only a completed deep_research run can be exported`
- `400 Run has no result payload`
- `400 Task extraction failed: ...`
- `503 Yandex Tracker is not configured (yandex_tracker_* env)`

---

### `POST /api/projects/{project_id}/runs/{run_id}/export/source-craft`

**Кто может вызывать:** `reviewer`, `admin`  
**Назначение:** выгрузить задачи из завершенного deep research run в Source Craft (или совместимый REST endpoint).

**Условия**

- `run_type == deep_research`
- `status == completed`
- в run есть `result_json`
- интеграция настроена (`source_craft_api_url`)

**Request body**

- отсутствует (пустое тело)

**Response 200 (`ExportTasksOut`)**

```json
{
  "ok": true,
  "tasks_planned": 10,
  "created": [
    {"summary": "Task 1", "response": {"id": "123"}}
  ],
  "errors": []
}
```

**Ошибки**

- `404 Project not found`
- `403 Forbidden` (нечитабельный проект)
- `403 Reviewer or admin required`
- `404 Run not found`
- `400 Only a completed deep_research run can be exported`
- `400 Run has no result payload`
- `400 Task extraction failed: ...`
- `503 Source Craft is not configured (source_craft_api_url env)`

---

### `POST /api/projects/{project_id}/publish-showcase`

**Кто может вызывать:** `reviewer`, `admin`  
**Назначение:** опубликовать проект в витрину.

**Условие**

- статус проекта должен быть `deep_research_completed`.

**Эффект**

- `status -> on_showcase`

**Response 200**

- `ProjectOutEnvelope`

**Ошибки**

- `404 Project not found`
- `400 Complete deep research before publishing`
- `403 Reviewer or admin required`

---

### 4.3 Сообщения проекта

### `GET /api/projects/{project_id}/messages`

**Кто может вызывать:** читатели проекта (`submitter`-owner, `reviewer`, `admin`)  
**Назначение:** получить чат/историю сообщений проекта.

**Response 200**

- `MessageOut[]` (сортировка `created_at asc`)

`MessageOut`:

- `id`
- `project_id`
- `author_id`
- `body`
- `created_at`

**Ошибки**

- `404 Project not found`
- `403 Forbidden`

---

### `POST /api/projects/{project_id}/messages`

**Кто может вызывать:** читатели проекта (`submitter`-owner, `reviewer`, `admin`)  
**Назначение:** добавить сообщение в проект.

**Request body**

```json
{
  "body": "Текст сообщения"
}
```

**Response 200**

- `MessageOut`

**Ошибки**

- `404 Project not found`
- `403 Forbidden`
- `422` (`body` пустой)

---

## 5) Showcase API

Префикс: `/api/showcase`

### `GET /api/showcase`

**Кто может вызывать:** любой (без токена)  
**Назначение:** список проектов на витрине.

**Логика**

- Возвращаются проекты со статусом `on_showcase`.
- Сортировка: `created_at desc`.

**Response 200**

- `ProjectOut[]`

**Ошибки**

- стандартно не предполагаются, кроме системных (`500` и т.п.)

---

## 6) Integrations Admin API (Telegram subscribers)

Префикс: `/api/admin/telegram-subscribers`

### `GET /api/admin/telegram-subscribers`

**Кто может вызывать:** только `admin`  
**Назначение:** получить список chat ID для Telegram-рассылки.

**Response 200**

```json
{
  "ok": true,
  "result": [
    {
      "id": "uuid",
      "chat_id": "123456789",
      "label": "Admin chat",
      "created_at": "2026-01-01T10:00:00Z"
    }
  ]
}
```

**Ошибки**

- `403 Admin required`
- `401` при отсутствии/невалидности токена

---

### `POST /api/admin/telegram-subscribers`

**Кто может вызывать:** только `admin`  
**Назначение:** добавить chat ID в рассылку.

**Request body**

```json
{
  "chat_id": "123456789",
  "label": "Команда ревью"
}
```

Ограничения:

- `chat_id`: от 1 до 32 символов
- `label`: до 255 символов

**Response 201**

```json
{
  "id": "uuid",
  "chat_id": "123456789",
  "label": "Команда ревью",
  "created_at": "2026-01-01T10:00:00Z"
}
```

**Ошибки**

- `409 chat_id already registered`
- `403 Admin required`
- `422` ошибки валидации

---

### `DELETE /api/admin/telegram-subscribers/{subscriber_id}`

**Кто может вызывать:** только `admin`  
**Назначение:** удалить chat ID из рассылки.

**Response 204**

- тело пустое

**Ошибки**

- `404 Subscriber not found`
- `403 Admin required`
- `401` при проблеме с токеном

---

## 7) Telegram-рассылка: когда срабатывает

Рассылка в Telegram выполняется только в методе:

- `POST /api/projects/{project_id}/submit`

После успешного изменения статуса и `commit` ставится background task:

- `notify_new_project_submitted(project_id)`

Что отправляется:

- название проекта
- UUID проекта
- ссылка `PUBLIC_APP_URL/projects/{id}` (если `PUBLIC_APP_URL` задан)

Если `TELEGRAM_BOT_TOKEN` пуст или нет подписчиков, рассылка не выполняется.

---

## 8) Структуры ответов (кратко)

### `TokenResponse`

- `ok: bool`
- `access_token: str`
- `token_type: "bearer"`

### `ProjectOutEnvelope`

- `ok: bool`
- `result: ProjectOut`

### `ReviewEnvelope`

- `ok: bool`
- `result: ProjectOut`

### `AgentRunOut`

- `id`, `project_id`, `run_type`, `status`
- `current_agent`
- `completed_agents`, `total_agents`
- `evaluation_prompt`
- `error_text`
- `started_at`, `finished_at`, `created_at`

### `AgentRunDetailOut`

- `ok`
- `result: AgentRunOut`
- `payload: dict | null`
- `progress: dict | null`

### `LatestDeepResearchOut`

- `ok`
- `project_id`
- `run_id`
- `finished_at`
- `payload` (полный итог deep research)

### `ExportTasksOut`

- `ok`
- `tasks_planned: int`
- `created: list[dict]`
- `errors: list[str]`

### `TelegramSubscriberListEnvelope`

- `ok`
- `result: TelegramSubscriberOut[]`

---

## 9) Кто что может вызывать (сводная матрица)

- **Без токена**
  - `GET /health`
  - `POST /api/auth/register`
  - `POST /api/auth/login`
  - `GET /api/showcase`

- **Любой авторизованный**
  - `GET /api/auth/me`
  - `GET /api/projects/{id}` (если есть права на проект)
  - `GET /api/projects/{id}/runs`
  - `GET /api/projects/{id}/runs/{run_id}`
  - `GET /api/projects/{id}/deep-research/latest` (доп. условия по статусу)
  - `GET/POST /api/projects/{id}/messages` (если есть права на проект)

- **Submitter/Admin**
  - `POST /api/projects`
  - `GET /api/projects/mine`
  - `PATCH /api/projects/{id}` (только владелец)
  - `POST /api/projects/{id}/submit` (только владелец)

- **Reviewer/Admin**
  - `GET /api/projects/review-queue`
  - `POST /api/projects/{id}/review`
  - `POST /api/projects/{id}/runs/evaluation`
  - `POST /api/projects/{id}/runs/deep-research`
  - `POST /api/projects/{id}/runs/{run_id}/export/tracker`
  - `POST /api/projects/{id}/runs/{run_id}/export/source-craft`
  - `POST /api/projects/{id}/publish-showcase`

- **Admin only**
  - `GET /api/admin/telegram-subscribers`
  - `POST /api/admin/telegram-subscribers`
  - `DELETE /api/admin/telegram-subscribers/{subscriber_id}`

---

## 10) Практические примечания

- Для методов с UUID в path передавайте валидные UUID, иначе `422`.
- Для export методов run обязательно должен быть `deep_research + completed`.
- Для `export/tracker` проверяйте env:
  - `YANDEX_TRACKER_OAUTH_TOKEN`
  - `YANDEX_TRACKER_ORG_ID`
  - `YANDEX_TRACKER_DEFAULT_QUEUE`
- Для `export/source-craft` минимум:
  - `SOURCE_CRAFT_API_URL`
- Для Telegram:
  - `TELEGRAM_BOT_TOKEN`
  - хотя бы один subscriber в `telegram_subscribers`.

