---

## Фаза 2 — Реализация Intake Agent

Это самый важный этап для демо. Создай файл `directives/Phase_2.md` и вставь содержимое ниже:

```markdown
# Phase 2: Реализация Intake Agent (живая цепочка)

## Контекст
Фазы 0 и 1 завершены. Структура src/ создана с заглушками.
Задача Фазы 2: реализовать первый рабочий агент — Intake Agent —
с полной цепочкой от HTTP-запроса до записи в БД и задачи в Трекере.

Стек: Python 3.11+, FastAPI, SQLAlchemy, httpx, PostgreSQL, Redis.
Никаких фронтендов. Тестовая визуализация — только если нужна для проверки.

---

## ЗАДАЧА 1: ORM модели и миграции (src/db/)

### src/db/models.py
Реализуй SQLAlchemy ORM модели по docs/data-model.md:

```python
    Все модели через DeclarativeBase (SQLAlchemy 2.0 style)
    Типы: String, Text, DateTime, JSON (для JSONB), Enum, ForeignKey
    У каждой модели: __tablename__, все поля из data-model.md
    Связи через relationship() там где есть ForeignKey
    created_at / updated_at через server_default=func.now()
```

Модели: Project, Application, AgentLog, Task, Document.

Статусы через Python Enum:
- ApplicationStatus: draft, submitted, scoring, approved, rejected
- AgentLogStatus: pending, success, error

### src/db/base.py
Реализуй:
- engine через create_async_engine (asyncpg драйвер)
- AsyncSession через async_sessionmaker
- get_db() как async dependency для FastAPI
- Base = DeclarativeBase()

### Alembic
- Инициализируй alembic в src/ (alembic init migrations)
- Настрой migrations/env.py под async engine и наши модели
- Создай первую миграцию: alembic revision --autogenerate -m "init"

Добавь в requirements.txt (или pyproject.toml):
sqlalchemy[asyncio], asyncpg, alembic, pydantic-settings,
fastapi, uvicorn, httpx, redis, structlog, psycopg[binary]

---

## ЗАДАЧА 2: Pydantic схемы (src/schemas/)

### src/schemas/application.py
```python
class ApplicationCreate(BaseModel):
    initiator_name: str
    initiator_email: EmailStr
    title: str
    text: str
    domain: str  # медицина / экология / наука / образование / культура
    attachments_url: list[str] = []

class ApplicationResponse(BaseModel):
    id: UUID
    project_id: UUID
    status: ApplicationStatus
    scorecard: dict | None
    summary: str | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class ScorecardItem(BaseModel):
    criterion: str
    score: int  # 1-10
    rationale: str

class IntakeResult(BaseModel):
    application_id: UUID
    scorecard: list[ScorecardItem]
    clarifying_questions: list[str]
    summary: str
    recommended_action: Literal["approve", "reject", "clarify"]
```

### src/schemas/project.py
```python
class ProjectCreate(BaseModel):
    title: str
    description: str

class ProjectResponse(BaseModel):
    id: UUID
    title: str
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
```

---

## ЗАДАЧА 3: Клиент Яндекс Трекера (src/integrations/tracker.py)

Реализуй async клиент через httpx.AsyncClient:

```python
class TrackerClient:
    base_url = "https://api.tracker.yandex.net/v2"
    # Авторизация: заголовок Authorization: OAuth {TRACKER_TOKEN}
    # + заголовок X-Org-ID: {TRACKER_ORG_ID}

    async def create_issue(
        self,
        queue: str,      # TRACKER_QUEUE_KEY из env
        summary: str,
        description: str,
        tags: list[str] = []
    ) -> dict:
        # POST /issues
        # Возвращает: {"id": str, "key": str, "status": str}

    async def update_issue(
        self,
        issue_key: str,
        status: str | None = None,
        comment: str | None = None
    ) -> dict:
        # PATCH /issues/{issue_key}

    async def add_comment(
        self,
        issue_key: str,
        text: str
    ) -> dict:
        # POST /issues/{issue_key}/comments

    async def get_issue(self, issue_key: str) -> dict:
        # GET /issues/{issue_key}

    async def list_issues(self, queue: str, status: str | None = None) -> list[dict]:
        # GET /issues/_search (POST с фильтром)
```

Требования:
- Все методы async
- Timeout: 30 секунд
- При HTTP ошибке: логировать и поднимать кастомный TrackerAPIError
- Токен и org_id берутся из core/config.py (не хардкодить)

---

## ЗАДАЧА 4: Клиент Yandex Cloud Agents (src/integrations/yandex_cloud.py)

Реализуй клиент для вызова агентов через Yandex Cloud Foundation Models API:

```python
class YandexCloudAgentClient:
    # Базовый URL: https://llm.api.cloud.yandex.net/foundationModels/v1/completion
    # Авторизация: Authorization: Api-Key {YC_API_KEY}
    # folder_id берётся из env

    async def invoke_agent(
        self,
        model_uri: str,       # например: gpt://folder_id/yandexgpt/latest
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
        max_tokens: int = 4000
    ) -> str:
        # POST к completion endpoint
        # Возвращает текст ответа модели (alternatives[0].message.text)
        # При ошибке: логировать, поднимать YCAgentError

    def build_model_uri(self, model_name: str) -> str:
        # Строит URI вида: gpt://{YC_FOLDER_ID}/{model_name}/latest
```

Формат тела запроса к Yandex Cloud:
```json
{
  "modelUri": "gpt://{folder_id}/yandexgpt-pro/latest",
  "completionOptions": {
    "stream": false,
    "temperature": 0.3,
    "maxTokens": 4000
  },
  "messages": [
    {"role": "system", "text": "..."},
    {"role": "user", "text": "..."}
  ]
}
```

---

## ЗАДАЧА 5: Intake Agent логика (src/agents/intake.py)

Это главный файл фазы. Реализуй полную логику агента:

```python
INTAKE_SYSTEM_PROMPT = """
Ты — эксперт по оценке проектных заявок для Центра технологий для Общества.
Центр реализует проекты на стыке медицины, экологии, науки, образования и ИИ.

Твоя задача: провести первичную экспертную оценку заявки по 5 критериям.

КРИТЕРИИ ОЦЕНКИ (каждый от 1 до 10):
1. Актуальность — насколько проблема релевантна для общества и науки
2. Реализуемость — техническая и организационная осуществимость
3. Инновационность — новизна подхода, отличие от существующих решений
4. Социальный эффект — потенциальная польза для общества
5. Ресурсная обоснованность — соответствие заявленных ресурсов масштабу задачи

ФОРМАТ ОТВЕТА (строго JSON, без markdown):
{
  "scorecard": [
    {
      "criterion": "Актуальность",
      "score": 8,
      "rationale": "..."
    }
  ],
  "clarifying_questions": [
    "Вопрос 1 если нужно уточнить",
    "Вопрос 2"
  ],
  "summary": "Краткое резюме заявки для руководителя проекта (3-5 предложений)",
  "recommended_action": "approve | reject | clarify",
  "overall_score": 7.4
}

Если суммарный балл >= 6.0 — рекомендуй approve.
Если суммарный балл < 4.0 — рекомендуй reject.
Иначе — clarify (нужны уточнения).
Отвечай только JSON, без вступлений и объяснений вне JSON.
"""

class IntakeAgent:
    def __init__(self, yc_client, tracker_client, db_session):
        ...

    async def process(self, application_id: UUID) -> IntakeResult:
        # 1. Читаем заявку из БД
        # 2. Формируем user_message с текстом заявки
        # 3. Вызываем YC агента с INTAKE_SYSTEM_PROMPT
        # 4. Парсим JSON ответ → IntakeResult
        # 5. Обновляем application в БД (scorecard, summary, status=scoring)
        # 6. Пишем в agent_logs
        # 7. Создаём задачу в Трекере с резюме и scorecard
        # 8. Возвращаем IntakeResult

    async def _build_user_message(self, application) -> str:
        # Формирует текст заявки для подачи агенту
        # Включает: название, домен, текст, инициатор

    async def _parse_response(self, raw: str) -> dict:
        # Парсит JSON из ответа модели
        # При ошибке парсинга: логировать raw и поднимать IntakeParseError
```

---

## ЗАДАЧА 6: FastAPI эндпоинты (src/api/)

### src/api/applications.py

```python
# POST /applications
# Принимает ApplicationCreate
# Создаёт Project + Application в БД (status=submitted)
# Ставит задачу в Redis очередь для Orchestrator
# Возвращает ApplicationResponse с id

# GET /applications/{id}
# Возвращает текущее состояние заявки включая scorecard и summary

# POST /applications/{id}/trigger-intake
# Запускает IntakeAgent для заявки (для тестирования в MVP)
# Возвращает IntakeResult
```

### src/api/projects.py

```python
# GET /projects
# Список всех проектов с пагинацией (limit/offset)

# GET /projects/{id}
# Детали проекта включая связанные applications
```

### src/main.py
Добавь:
- GET /health → {"status": "ok", "version": "0.1.0"}
- Подключение роутеров applications и projects
- CORS middleware (для тестовой визуализации)
- Startup event: проверка подключения к БД

---

## ЗАДАЧА 7: Конфигурация (src/core/config.py)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    database_url: str

    # Redis
    redis_url: str

    # Yandex Cloud
    yc_api_key: str
    yc_folder_id: str
    yc_agent_id_intake: str
    yc_agent_id_research: str

    # Tracker
    tracker_token: str
    tracker_org_id: str
    tracker_queue_key: str

    # Sourcecraft
    sourcecraft_token: str
    sourcecraft_base_url: str

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
```

---

## ЗАДАЧА 8: Минимальная тестовая страница (опционально)

Если нужна визуальная проверка — создай `src/static/index.html`:
- Простая HTML форма для отправки заявки (POST /applications)
- Поле для ввода ID и кнопка запуска intake (POST /applications/{id}/trigger-intake)
- Отображение scorecard из ответа в читаемом виде
- Никаких фреймворков — чистый HTML + fetch()

FastAPI должен раздавать эту страницу через StaticFiles.

---

## ПОРЯДОК ВЫПОЛНЕНИЯ

1. src/db/models.py + src/db/base.py
2. Alembic init + первая миграция
3. src/schemas/ (оба файла)
4. src/integrations/tracker.py
5. src/integrations/yandex_cloud.py
6. src/agents/intake.py
7. src/api/ (applications.py, projects.py, main.py)
8. src/core/config.py
9. Тестовая HTML страница (опционально)

После каждого пункта жди подтверждения перед следующим.
При любых архитектурных решениях отступающих от ТЗ — спрашивай,
не додумывай самостоятельно.
```

---

Сообщение для Cursor остаётся прежним:

```
Прочитай файл directives/Phase_2.md и выполняй задачи 
строго по порядку, после каждого пункта жди подтверждения. 
Начни с Задачи 1: src/db/models.py и src/db/base.py
```