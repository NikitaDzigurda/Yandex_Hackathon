# Отчёт о выполнении: Фаза 2

## Контекст

Фаза 2 выполнялась по ТЗ из `directives/Phase_2.md`.  
Цель: реализовать рабочую цепочку Intake Agent от HTTP-запроса до записи в БД и интеграции с Яндекс Трекером.

Отдельное указание пользователя: выполнять шаги подряд, без ожидания подтверждения после каждого пункта.  
Именно в этом режиме фаза и была выполнена.

---

## Что реализовано по пунктам

## 1) ORM и база данных (`src/db/models.py`, `src/db/base.py`)

Реализованы полноценные ORM модели SQLAlchemy 2.0 style:
- `Project`
- `Application`
- `AgentLog`
- `Task`
- `Document`

Добавлено:
- базовый `DeclarativeBase` через `Base`;
- связи `relationship()` между сущностями;
- поля `created_at`/`updated_at` с `server_default=func.now()`;
- enums:
  - `ApplicationStatus` (`draft`, `submitted`, `scoring`, `approved`, `rejected`);
  - `AgentLogStatus` (`pending`, `success`, `error`);
- типы PostgreSQL (`UUID`, `JSONB`) для структурированных полей.

В `src/db/base.py` реализовано:
- `create_async_engine` (через asyncpg URL),
- `async_sessionmaker`,
- dependency `get_db()` для FastAPI.

---

## 2) Alembic init и первая миграция

Сделано:
- инициализирован Alembic внутри `src/`:
  - `src/alembic.ini`
  - `src/migrations/env.py`
  - `src/migrations/versions/...`
- `src/migrations/env.py` настроен под async engine, подключены `Base.metadata` и модели;
- создана первая ревизия `init`:
  - `src/migrations/versions/c6f8afc3b4a3_init.py`
  - содержит создание таблиц `projects`, `applications`, `agent_logs`, `tasks`, `documents`;
  - содержит создание enum-типов `application_status` и `agent_log_status`;
  - реализован корректный `downgrade()`.

Важно:
- автогенерация через `--autogenerate` не выполнилась из-за недоступности локального Docker daemon/БД в текущем окружении;
- в результате ревизия создана и заполнена вручную на основе актуальных моделей и `docs/data-model.md`.

---

## 3) Pydantic-схемы (`src/schemas/`)

### `src/schemas/application.py`
Реализованы:
- `ApplicationCreate`
- `ApplicationResponse`
- `ScorecardItem`
- `IntakeResult`

Ключевые моменты:
- `EmailStr` для email;
- `attachments_url` через `default_factory`;
- `score` ограничен `1..10`;
- `ApplicationResponse` и `IntakeResult` соответствуют ТЗ.

### `src/schemas/project.py`
Реализованы:
- `ProjectCreate`
- `ProjectResponse`
- `ProjectDetailResponse` (расширение с вложенными applications).

---

## 4) Клиент Яндекс Трекера (`src/integrations/tracker.py`)

Реализован `TrackerClient` на `httpx.AsyncClient`:
- `create_issue()`
- `update_issue()`
- `add_comment()`
- `get_issue()`
- `list_issues()`

Также добавлено:
- timeout 30 секунд;
- центральный `_request()` helper;
- кастомное исключение `TrackerAPIError`;
- логирование и проброс ошибок при HTTP/transport fail;
- заголовки авторизации через `core.config.settings` (`TRACKER_TOKEN`, `TRACKER_ORG_ID`).

---

## 5) Клиент Yandex Cloud (`src/integrations/yandex_cloud.py`)

Реализован `YandexCloudAgentClient`:
- `build_model_uri(model_name)` -> `gpt://{folder}/{model}/latest`;
- `invoke_agent(...)` -> запрос в Foundation Models completion endpoint;
- возврат текста `alternatives[0].message.text`.

Добавлено:
- кастомная ошибка `YCAgentError`;
- логирование проблем вызова;
- авторизация через `Api-Key` из env.

---

## 6) Логика Intake Agent (`src/agents/intake.py`)

Реализован рабочий `IntakeAgent` с полным процессом:
1. загрузка `Application` из БД;
2. сбор `user_message` из данных заявки;
3. вызов YC-модели через `YandexCloudAgentClient`;
4. парсинг JSON-ответа (`_parse_response`) с обработкой ошибок (`IntakeParseError`);
5. обновление заявки (`scorecard`, `summary`, `status=scoring`);
6. запись действия в `agent_logs`;
7. создание задачи в Трекере через `TrackerClient`;
8. создание записи в `tasks`;
9. commit и возврат `IntakeResult`.

Также добавлен детальный `INTAKE_SYSTEM_PROMPT` из ТЗ.

---

## 7) FastAPI эндпоинты (`src/api/`, `src/main.py`)

### `src/api/applications.py`
Реализованы:
- `POST /applications`
  - создаёт `Project` + `Application` (`submitted`);
  - кладёт `application_id` в Redis очередь `orchestrator:intake`;
  - возвращает `ApplicationResponse`.
- `GET /applications/{id}`
  - возвращает текущую заявку.
- `POST /applications/{id}/trigger-intake`
  - запускает `IntakeAgent` (MVP trigger);
  - возвращает `IntakeResult`.

### `src/api/projects.py`
Реализованы:
- `GET /projects` с `limit/offset`;
- `GET /projects/{id}` с загрузкой связанных `applications`.

### `src/api/router.py`
- подключены роутеры applications/projects через единый `api_router`.

### `src/main.py`
Добавлено:
- `GET /health` -> `{"status": "ok", "version": "0.1.0"}`;
- подключение роутеров;
- CORS middleware;
- startup-проверка подключения к БД через lifespan (`SELECT 1`).

---

## 8) Конфигурация (`src/core/config.py`)

Реализован `Settings` на `pydantic-settings` с полями:
- `database_url`
- `redis_url`
- `yc_api_key`, `yc_folder_id`, `yc_agent_id_intake`, `yc_agent_id_research`
- `tracker_token`, `tracker_org_id`, `tracker_queue_key`
- `sourcecraft_token`, `sourcecraft_base_url`

Инициализация:
- `model_config = SettingsConfigDict(env_file=".env")`
- `settings = Settings()`

---

## 9) Опциональная HTML-страница

Пункт был помечен в ТЗ как опциональный и не добавлялся в этой итерации, чтобы не размывать фокус на backend-цепочке Intake.

---

## Дополнительные изменения

- Добавлен `requirements.txt` с зависимостями фазы:
  - `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `pydantic-settings`,
  - `fastapi`, `uvicorn`, `httpx`, `redis`, `structlog`, `psycopg[binary]`,
  - `email-validator`.

- Обновлён `src/Dockerfile`:
  - добавлены зависимости, необходимые для async SQLAlchemy/Alembic/Pydantic Email.

- Обновлён `.env.example`:
  - `DATABASE_URL` приведён к `postgresql+asyncpg://...` для async engine.

---

## Проверки

Выполнено:
- проверка синтаксиса всех Python-файлов:
  - `python -m compileall src` — успешно.
- проверка линтер-диагностик через IDE:
  - критичных ошибок не обнаружено.

---

## Итог Фазы 2

Фаза 2 закрыта по обязательным пунктам:
- intake-цепочка реализована от API до БД и Tracker;
- асинхронные клиенты интеграций добавлены;
- ORM + миграционная база подготовлены;
- конфигурация и health-check готовы для запуска.

Система готова к следующему этапу: подключение Orchestrator-воркфлоу, полноценные ретраи/очереди и расширение lifecycle-логики проекта.
