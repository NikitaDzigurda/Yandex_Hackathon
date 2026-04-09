## ТЗ: Фаза 9 — Полная интеграция API коллеги

# Phase 9: Интеграция полного API коллеги в наш сервис

## Контекст
Коллега разработал отдельный backend с более зрелой архитектурой.
Его API задокументирован в API_REFERENCE.md.
Наш текущий сервис находится в src/.

ЦЕЛЬ: перенести ВСЮ логику из API_REFERENCE.md в наш сервис,
сохранив всё что уже работает (агенты, deep research, orchestrator).

ПРИНЦИП: не переписывать с нуля — адаптировать поверх существующего.

---

## ЗАДАЧА 1: JWT Аутентификация (src/api/auth.py + src/db/models.py)

### 1а. Модель User (src/db/models.py)
Добавь новую таблицу:

```python
class UserRole(str, Enum):
    submitter = "submitter"
    reviewer = "reviewer"
    admin = "admin"

class User(Base):
    __tablename__ = "users"
    id: UUID (PK, default uuid4)
    email: str (unique, not null, indexed)
    full_name: str (not null)
    hashed_password: str (not null)
    role: UserRole (not null, default="submitter")
    is_active: bool (default=True)
    created_at: datetime (server_default now)
```

### 1б. Добавить в таблицу projects поле submitter_id и reviewer_id:
```python
# В модели Project добавить:
submitter_id: UUID (FK users.id, nullable=True)
reviewer_id: UUID (FK users.id, nullable=True)
reviewer_comment: str (Text, nullable=True)
human_decision: str (default="pending")
# human_decision enum: pending | approve | reject | request_revision
```

### 1в. Создать src/core/security.py:
```python
# Зависимости для FastAPI:
# - get_password_hash(password: str) -> str  (bcrypt)
# - verify_password(plain, hashed) -> bool
# - create_access_token(subject: str) -> str  (JWT, exp = 24h)
# - get_current_user(token: Bearer) -> User   (async dependency)
# - require_submitter(user) -> User  (role check)
# - require_reviewer(user) -> User   (role check)
# - require_admin(user) -> User      (role check)

# Env vars: JWT_SECRET_KEY, JWT_ALGORITHM=HS256, JWT_EXPIRE_HOURS=24
```

Добавить в .env.example и config.py:
```
JWT_SECRET_KEY=
JWT_ALGORITHM=HS256
JWT_EXPIRE_HOURS=24
```

### 1г. Создать src/api/auth.py:
```python
# POST /api/auth/register
# Body: {email, password (min 8), full_name, role}
# 409 если email уже есть
# Returns: {ok: true, access_token, token_type: "bearer"}

# POST /api/auth/login
# Body: {email, password}
# 401 если неверные данные
# 403 если is_active=False
# Returns: {ok: true, access_token, token_type: "bearer"}

# GET /api/auth/me
# Requires: Bearer token
# Returns: {id, email, full_name, role}
```

Добавить в requirements.txt: python-jose[cryptography], passlib[bcrypt]

---

## ЗАДАЧА 2: Полный статусный автомат проектов

### 2а. Обновить ProjectStatus enum (src/db/models.py):
```python
class ProjectStatus(str, Enum):
    draft = "draft"
    submitted = "submitted"
    under_review = "under_review"
    revision_requested = "revision_requested"
    rejected = "rejected"
    accepted_for_research = "accepted_for_research"
    deep_research_running = "deep_research_running"
    deep_research_completed = "deep_research_completed"
    on_showcase = "on_showcase"
    archived = "archived"
```

### 2б. Обновить модель Project (src/db/models.py):
```python
# Добавить поля которых нет:
task: str (Text, nullable=True)       # что нужно сделать
stage: str (nullable=True)            # MVP / Pilot / etc
deadlines: str (nullable=True)        # Q3 / 18 месяцев
human_decision: str (default="pending")
reviewer_id: UUID (FK users.id, nullable=True)
reviewer_comment: str (nullable=True)
submitter_id: UUID (FK users.id, nullable=True)
```

### 2в. Alembic миграция:
```
alembic revision -m "add_users_and_project_fields"
```
Если autogenerate недоступен — написать вручную:
- CREATE TABLE users
- ALTER TABLE projects ADD COLUMNS (task, stage, deadlines, 
  human_decision, reviewer_id, reviewer_comment, submitter_id)
- ALTER TYPE projectstatus ADD VALUE ... (для каждого нового статуса)

---

## ЗАДАЧА 3: AgentRun модель и таблица

Коллега хранит запуски агентов в отдельной таблице.
Наш agent_logs — это лог шагов. AgentRun — это сущность запуска.

### Добавить в src/db/models.py:
```python
class RunType(str, Enum):
    evaluation = "evaluation"
    deep_research = "deep_research"

class RunStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"

class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: UUID (PK)
    project_id: UUID (FK projects.id)
    run_type: RunType
    status: RunStatus (default="queued")
    current_agent: str (nullable)      # имя текущего агента
    completed_agents: int (default=0)
    total_agents: int (default=0)
    evaluation_prompt: str (Text, nullable) # кастомный промпт если передан
    result_json: JSONB (nullable)       # финальный результат
    progress_json: JSONB (nullable)     # промежуточный прогресс
    error_text: str (nullable)
    started_at: datetime (nullable)
    finished_at: datetime (nullable)
    created_at: datetime (server_default now)
```

Добавь в миграцию выше.

---

## ЗАДАЧА 4: Обновить src/api/projects.py

Полностью перепиши роуты под новую архитектуру с auth.
Все роуты под префикс /api/projects.

```python
# POST /api/projects
# require_submitter
# Создаёт project: status=draft, submitter_id=current_user.id
# Body: {title, description, task, stage, deadlines}
# Returns: ProjectOutEnvelope

# GET /api/projects/mine
# require_submitter
# Список проектов где submitter_id=current_user.id
# Сортировка created_at desc

# GET /api/projects/review-queue
# require_reviewer
# Статусы: submitted, under_review, revision_requested
# Сортировка created_at asc

# GET /api/projects/{project_id}
# reviewer/admin — любой проект
# submitter — только свой (по submitter_id)
# 403 Forbidden если нет прав
# 404 если не найден

# PATCH /api/projects/{project_id}
# require_submitter, только владелец (submitter_id)
# Разрешено только из: draft, revision_requested
# После update из revision_requested → статус обратно в draft
# Body: любой поднабор {title, description, task, stage, deadlines}

# POST /api/projects/{project_id}/submit
# require_submitter, только владелец
# Разрешено из: draft, revision_requested
# status → submitted, human_decision → pending
# Background task: Telegram уведомление

# POST /api/projects/{project_id}/review
# require_reviewer
# Разрешено из: submitted, under_review, revision_requested
# Body: {decision: approve|reject|request_revision, comment: str}
# approve → status=accepted_for_research
# reject → status=rejected
# request_revision → status=revision_requested
# Устанавливает reviewer_id, reviewer_comment, human_decision

# POST /api/projects/{project_id}/publish-showcase
# require_reviewer
# Условие: status==deep_research_completed
# status → on_showcase
```

---

## ЗАДАЧА 5: Runs API (src/api/runs.py)

Создай новый роутер для управления запусками агентов.

```python
# POST /api/projects/{project_id}/runs/evaluation
# require_reviewer
# Разрешено из: submitted, under_review, revision_requested
# Создаёт AgentRun(run_type=evaluation, status=queued)
# Запускает IntakeAgent через background task
# project.status → under_review
# Returns: AgentRunOut

# POST /api/projects/{project_id}/runs/deep-research
# require_reviewer
# Разрешено из: accepted_for_research
# Body (опционально): {evaluation_prompt: str}
# Создаёт AgentRun(run_type=deep_research, status=queued)
# Запускает ResearchAgent через background task
# project.status → deep_research_running
# Returns: AgentRunOut

# GET /api/projects/{project_id}/runs
# Любой авторизованный с правом читать проект
# Список всех runs проекта, сортировка created_at desc
# Returns: AgentRunOut[]

# GET /api/projects/{project_id}/runs/{run_id}
# Returns: AgentRunDetailOut {ok, result: AgentRunOut, payload, progress}

# GET /api/projects/{project_id}/deep-research/latest
# Условие: project.status в (accepted_for_research, 
#   deep_research_running, deep_research_completed, on_showcase)
# Возвращает последний completed deep_research run
# Returns: LatestDeepResearchOut

# POST /api/projects/{project_id}/runs/{run_id}/export/tracker
# require_reviewer
# Условие: run_type=deep_research, status=completed, result_json не null
# Body: {queue: str | null}  — если null берём YANDEX_TRACKER_DEFAULT_QUEUE
# Извлекает задачи из result_json (поле roadmap/tasks)
# Создаёт задачи в Трекере через TrackerClient
# Returns: ExportTasksOut {ok, tasks_planned, created, errors}
# 503 если TRACKER_TOKEN не задан

# POST /api/projects/{project_id}/runs/{run_id}/export/source-craft
# require_reviewer
# Условие: аналогично export/tracker
# Создаёт задачи в Sourcecraft через SourcecraftClient
# Returns: ExportTasksOut
# 503 если SOURCECRAFT_BASE_URL не задан
```

### Background task логика для runs:

```python
async def run_evaluation_background(run_id: UUID, project_id: UUID, db):
    # 1. Обновить run: status=running, started_at=now, total_agents=5
    # 2. Запустить IntakeAgent.process() передавая project_id
    # 3. По мере выполнения обновлять run.current_agent и completed_agents
    # 4. При успехе: run.status=completed, result_json=результат, 
    #    finished_at=now, project.status=under_review (если не изменён)
    # 5. При ошибке: run.status=failed, error_text=str(e)

async def run_deep_research_background(run_id: UUID, project_id: UUID, 
                                        evaluation_prompt: str | None, db):
    # 1. run.status=running, started_at=now, total_agents=9
    # 2. Запустить ResearchAgent.process()
    # 3. При успехе: run.status=completed, result_json=отчёт,
    #    project.status=deep_research_completed
    # 4. При ошибке: run.status=failed, project.status=accepted_for_research
```

---

## ЗАДАЧА 6: Messages API (src/api/messages.py)

```python
class Message(Base):
    __tablename__ = "messages"
    id: UUID (PK)
    project_id: UUID (FK projects.id)
    author_id: UUID (FK users.id)
    body: str (Text, not null)
    created_at: datetime (server_default now)

# GET /api/projects/{project_id}/messages
# Любой авторизованный читатель проекта
# Returns: MessageOut[] сортировка created_at asc

# POST /api/projects/{project_id}/messages
# Любой авторизованный читатель проекта
# Body: {body: str}  422 если body пустой
# Returns: MessageOut
```

Добавить Message в миграцию.

---

## ЗАДАЧА 7: Showcase API (src/api/showcase.py)

```python
# GET /api/showcase
# Без токена
# Проекты со status=on_showcase
# Сортировка created_at desc
# Returns: ProjectOut[]
```

---

## ЗАДАЧА 8: Telegram Admin API (src/api/telegram_admin.py)

```python
class TelegramSubscriber(Base):
    __tablename__ = "telegram_subscribers"
    id: UUID (PK)
    chat_id: str (unique, max 32 chars)
    label: str (max 255, nullable)
    created_at: datetime (server_default now)

# GET /api/admin/telegram-subscribers
# require_admin
# Returns: {ok, result: TelegramSubscriberOut[]}

# POST /api/admin/telegram-subscribers
# require_admin
# Body: {chat_id: str, label: str}
# 409 если chat_id уже есть
# Returns: TelegramSubscriberOut (201)

# DELETE /api/admin/telegram-subscribers/{subscriber_id}
# require_admin
# 404 если не найден
# Returns: 204 No Content
```

### Telegram уведомление при submit:
```python
async def notify_new_project_submitted(project_id: UUID, db):
    # Получить проект из БД
    # Получить всех subscribers из telegram_subscribers
    # Если TELEGRAM_BOT_TOKEN пуст или нет subscribers — выйти тихо
    # Для каждого subscriber отправить:
    # POST https://api.telegram.org/bot{token}/sendMessage
    # {chat_id, text: "Новый проект: {title}\nID: {id}\n{PUBLIC_APP_URL}/projects/{id}"}
    # Ошибки одного subscriber не должны прерывать остальные
```

Добавить в .env.example и config.py:
```
TELEGRAM_BOT_TOKEN=
PUBLIC_APP_URL=http://localhost:8000
```

---

## ЗАДАЧА 9: Обновить src/main.py и src/api/router.py

```python
# Подключить все новые роутеры:
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(projects_router, prefix="/api/projects", tags=["projects"])
app.include_router(runs_router, prefix="/api/projects", tags=["runs"])
app.include_router(messages_router, prefix="/api/projects", tags=["messages"])
app.include_router(showcase_router, prefix="/api", tags=["showcase"])
app.include_router(telegram_admin_router, prefix="/api/admin", tags=["admin"])

# УБРАТЬ старые роуты которые заменяются:
# - старый /api/v1/applications/* → заменяется на /api/projects/*
# - старый /api/v1/demo/seed → оставить для демо

# StaticFiles остаётся последним как обычно
```

---

## ЗАДАЧА 10: Обновить HTML страницу (src/static/index.html)

Добавь в начало страницы Секцию 0 — Авторизация:
- Форма регистрации: email, password, full_name, role (select)
- Форма входа: email, password
- После входа: сохранить токен в localStorage, показать имя пользователя
- Все последующие fetch запросы должны добавлять:
  Authorization: Bearer {token}

Обнови существующие секции:
- Вместо POST /api/v1/applications → POST /api/projects (submitter)
- Вместо GET /api/v1/applications/{id} → GET /api/projects/{id}
- Вместо trigger-intake → POST /api/projects/{id}/runs/evaluation
- Вместо trigger-research → POST /api/projects/{id}/runs/deep-research
- Добавить polling статуса run: каждые 3 секунды GET /runs/{run_id}
  пока status != completed | failed

---

## ЗАДАЧА 11: Финальная миграция и проверка

Создай итоговую миграцию на все изменения если не создавалась ранее:
```
alembic revision -m "phase9_full_schema"
```

Проверь что приложение:
1. Стартует через docker compose up --build
2. GET /health возвращает 200
3. POST /api/auth/register работает
4. POST /api/projects работает с токеном

---

## ПОРЯДОК ВЫПОЛНЕНИЯ

1. Задача 1 (auth: модель User, security.py, auth.py)
2. Задача 2 (статусный автомат ProjectStatus)
3. Задача 3 (AgentRun модель)
4. Задача 11 — миграция сразу после 1-3 (пока всё свежо)
5. Задача 4 (обновить projects.py с auth)
6. Задача 5 (runs.py — главная задача фазы)
7. Задача 6 (messages.py)
8. Задача 7 (showcase.py)
9. Задача 8 (telegram_admin.py + уведомления)
10. Задача 9 (обновить main.py и router.py)
11. Задача 10 (HTML страница)

При любых конфликтах с существующим кодом — спрашивай, не ломай агентов.