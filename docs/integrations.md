# Интеграции платформы (MVP)

Документ описывает внешние интеграции, используемые FastAPI-бэкендом и агентами:
- Яндекс Трекер API
- Sourcecraft API
- Yandex Cloud Agents

Все секреты передаются только через переменные окружения (`.env`), без хардкода в коде.

---

## 1) Яндекс Трекер API

### Базовые настройки

- **Base URL:** `https://api.tracker.yandex.net`
- **Авторизация:** OAuth-токен из `TRACKER_TOKEN`
- **Обязательные заголовки:**
  - `Authorization: OAuth <TRACKER_TOKEN>`
  - `X-Org-ID: <TRACKER_ORG_ID>`
  - `Content-Type: application/json`

### Эндпоинты

#### 1. Создание задачи
- **Метод:** `POST`
- **Путь:** `/v3/issues/`
- **Назначение:** создать задачу по заявке/этапу проекта
- **Ключевые поля запроса:**
  - `queue` (string, например `TRACKER_QUEUE_KEY`)
  - `summary` (string)
  - `description` (string)
  - `type` (string)
- **Ключевые поля ответа:**
  - `id` (string, внутренний ID)
  - `key` (string, человекочитаемый ключ задачи)
  - `status` (object)

#### 2. Обновление статуса/полей задачи
- **Метод:** `PATCH`
- **Путь:** `/v3/issues/{issueId}`
- **Назначение:** обновить статус, описание, исполнителя и теги
- **Ключевые поля запроса:**
  - `status` (string/object, в зависимости от workflow)
  - `assignee` (string)
  - `description` (string)
- **Ключевые поля ответа:**
  - `id`, `key`, `status`, `updatedAt`

#### 3. Добавление комментария
- **Метод:** `POST`
- **Путь:** `/v3/issues/{issueId}/comments`
- **Назначение:** публиковать выводы агентов, уточняющие вопросы, статусные апдейты
- **Ключевые поля запроса:**
  - `text` (string)
- **Ключевые поля ответа:**
  - `id` (string)
  - `text` (string)
  - `createdBy`, `createdAt`

#### 4. Получение списка задач
- **Метод:** `GET`
- **Путь:** `/v3/issues`
- **Назначение:** получить набор задач по фильтру (очередь, статус, проект)
- **Ключевые query-параметры:**
  - `filter` (string)
  - `queue` (string)
  - `perPage` / `page`
- **Ключевые поля ответа:**
  - массив задач с `id`, `key`, `summary`, `status`, `assignee`

#### 5. Получение задачи по ID/ключу
- **Метод:** `GET`
- **Путь:** `/v3/issues/{issueId}`
- **Назначение:** синхронизировать актуальное состояние конкретной задачи
- **Ключевые поля ответа:**
  - `id`, `key`, `summary`, `description`, `status`, `assignee`, `updatedAt`

---

## 2) Sourcecraft API

> Примечание: точные пути могут зависеть от версии/конфигурации Sourcecraft в контуре. Ниже — целевая контрактная модель для интеграционного клиента.

### Базовые настройки

- **Base URL:** `SOURCECRAFT_BASE_URL` (из env)
- **Авторизация:** Bearer-токен из `SOURCECRAFT_TOKEN`
- **Заголовки:**
  - `Authorization: Bearer <SOURCECRAFT_TOKEN>`
  - `Content-Type: application/json`

### Эндпоинты

#### 1. Получение активности репозитория
- **Метод:** `GET`
- **Путь:** `/api/v1/repos/{repoId}/activity`
- **Назначение:** мониторинг текущего движения по проекту (commits, PR, события)
- **Ключевые query-параметры:**
  - `from`, `to` (ISO datetime)
  - `limit` (int)
- **Ключевые поля ответа:**
  - `events[]` с `type`, `author`, `timestamp`, `payload`

#### 2. Получение списка коммитов
- **Метод:** `GET`
- **Путь:** `/api/v1/repos/{repoId}/commits`
- **Назначение:** анализ темпа разработки и изменений
- **Ключевые query-параметры:**
  - `branch` (string)
  - `since` (ISO datetime)
  - `limit` (int)
- **Ключевые поля ответа:**
  - `commits[]` с `sha`, `message`, `author`, `committed_at`, `url`

#### 3. Получение статуса pull request
- **Метод:** `GET`
- **Путь:** `/api/v1/repos/{repoId}/pull-requests/{prId}`
- **Назначение:** проверка состояния review/merge для Monitor Agent
- **Ключевые поля ответа:**
  - `id`, `title`, `state`, `author`, `review_status`, `merge_status`, `updated_at`

---

## 3) Yandex Cloud Agents

### Конфигурация агента в Yandex Cloud (веб-консоль)

Для каждого агента (например, Intake и Research) в консоли задаются:
- модель (`YandexGPT Pro`, `YandexGPT 5 Pro`, `YandexGPT 5.1 Pro` и др. из доступных),
- системный промпт и policy-инструкции,
- подключённые MCP-инструменты,
- лимиты выполнения (таймауты, ограничения токенов, ретраи),
- параметры доступа (folder/project context).

Идентификаторы агента и folder передаются в API через env:
- `YC_FOLDER_ID`
- `YC_AGENT_ID_INTAKE`
- `YC_AGENT_ID_RESEARCH`
- `YC_API_KEY`

### Как FastAPI вызывает агента

Вариант MVP: асинхронный REST-вызов через `httpx.AsyncClient` к API Yandex Cloud Agents (или SDK, если принят в проекте).  
Оркестратор формирует payload, передаёт контекст задачи, получает структурированный ответ и пишет его в БД/Трекер.

---

## 4) Формат MCP-инструмента (`tool_definition`)

Ниже целевая структура описания инструмента, подключаемого к агенту:

```json
{
  "name": "tracker_create_issue",
  "description": "Create issue in Yandex Tracker for approved project application",
  "parameters": {
    "type": "object",
    "properties": {
      "queue": { "type": "string", "description": "Tracker queue key" },
      "summary": { "type": "string", "description": "Issue title" },
      "description": { "type": "string", "description": "Issue description" },
      "project_id": { "type": "string", "description": "Internal project UUID" }
    },
    "required": ["queue", "summary", "description", "project_id"],
    "additionalProperties": false
  }
}
```

---

## 5) Пример вызова агента с MCP-инструментом (Python, псевдокод)

```python
import httpx

async def run_intake_agent(payload: dict) -> dict:
    api_key = settings.YC_API_KEY
    agent_id = settings.YC_AGENT_ID_INTAKE

    request_body = {
        "agent_id": agent_id,
        "input": payload,
        "tools": [
            {
                "name": "tracker_create_issue",
                "description": "Create issue in Yandex Tracker",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "queue": {"type": "string"},
                        "summary": {"type": "string"},
                        "description": {"type": "string"},
                        "project_id": {"type": "string"}
                    },
                    "required": ["queue", "summary", "description", "project_id"]
                }
            }
        ]
    }

    headers = {
        "Authorization": f"Api-Key {api_key}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://<yc-agents-endpoint>/v1/agents/run",
            json=request_body,
            headers=headers
        )
        resp.raise_for_status()
        return resp.json()
```

---

## 6) Практика надёжности и безопасности

- Все токены (`TRACKER_TOKEN`, `SOURCECRAFT_TOKEN`, `YC_API_KEY`) хранятся только в `.env`/секрет-хранилище.
- Интеграционные клиенты работают асинхронно через `httpx` с таймаутами и retry-политикой.
- Каждый внешний вызов логируется в `agent_logs` через `correlation_id`.
- Ошибки внешних API нормализуются в единый `error_payload` и эскалируются через Orchestrator.
