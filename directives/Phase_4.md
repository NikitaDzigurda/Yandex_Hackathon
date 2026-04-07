Фаза выполнена качественно. Все 6 пунктов закрыты, критические исправления из Фазы 2 применены.

**Одна новая проблема:**
Orchestrator запускается как `asyncio.create_task()` внутри FastAPI процесса. Это работает, но нестабильно под нагрузкой — если main process упадёт, воркер умрёт вместе с ним. Для MVP приемлемо, но зафиксируем.

**Потенциальный риск на демо:**
`StaticFiles` смонтирован на `"/"` — это перекрывает все API роуты если порядок неправильный. Нужно убедиться что роутеры подключены ДО mount StaticFiles.

---

## Фаза 4: Интеграция, стабилизация и демо-готовность

Создай файл `directives/Phase_4.md`:

````markdown
# Phase 4: Интеграция Sourcecraft, мониторинг, стабилизация и демо-готовность

## Контекст
Фазы 0-3 завершены. Intake + Research Agent работают, Orchestrator запущен.
Задача Фазы 4:
1. Исправить риск StaticFiles vs API роуты
2. Реализовать клиент Sourcecraft и Monitor Agent (базовый)
3. Добавить эндпоинты для РП (апрув/отклонение заявок)
4. Добавить endpoint /projects/{id}/status — сводка по проекту
5. Реализовать структурированное логирование и health-check расширенный
6. Подготовить тестовые фикстуры для демо
7. Финальная проверка docker-compose сборки

---

## ЗАДАЧА 1: Исправление StaticFiles (src/main.py)

Проблема: StaticFiles на "/" перекрывает API роуты если подключён неправильно.

Исправь порядок в main.py:
```python
# ПРАВИЛЬНЫЙ порядок:
app = FastAPI()

# 1. Сначала все middleware
app.add_middleware(CORSMiddleware, ...)

# 2. Потом все API роуты
app.include_router(api_router, prefix="/api/v1")

# 3. Health check как отдельный роут (не через роутер)
@app.get("/health")
async def health(): ...

# 4. StaticFiles ПОСЛЕДНИМ
app.mount("/", StaticFiles(directory="static", html=True), name="static")
```

Также обнови HTML страницу — все fetch вызовы должны использовать
префикс `/api/v1/`:
- `/applications` → `/api/v1/applications`
- `/applications/{id}` → `/api/v1/applications/{id}`
- и т.д.

---

## ЗАДАЧА 2: Sourcecraft клиент (src/integrations/sourcecraft.py)

Реализуй полноценный async клиент:

```python
class SourcecraftClient:
    # base_url из env: SOURCECRAFT_BASE_URL
    # Авторизация: Authorization: Bearer {SOURCECRAFT_TOKEN}
    # Timeout: 30 секунд

    async def get_repo_activity(
        self,
        repo_id: str,
        days: int = 7
    ) -> dict:
        # GET /repos/{repo_id}/activity?since={date}
        # Возвращает: {"commits": int, "prs": int, "contributors": list}

    async def get_commits(
        self,
        repo_id: str,
        limit: int = 20
    ) -> list[dict]:
        # GET /repos/{repo_id}/commits?limit={limit}
        # Возвращает список: [{"sha", "message", "author", "date"}]

    async def get_pr_status(
        self,
        repo_id: str
    ) -> list[dict]:
        # GET /repos/{repo_id}/pulls
        # Возвращает: [{"id", "title", "state", "created_at", "updated_at"}]

    async def list_repos(self, project_name: str | None = None) -> list[dict]:
        # GET /repos
        # Опционально фильтр по имени проекта
```

Кастомное исключение: `SourcecraftAPIError`.
Логирование ошибок аналогично TrackerClient.

---

## ЗАДАЧА 3: Monitor Agent базовый (src/agents/monitor.py)

Реализуй Monitor Agent для выявления зависших задач:

```python
class MonitorAgent:
    """
    Запускается по расписанию (каждые 30 минут через Orchestrator).
    Проверяет задачи в Трекере и активность в Sourcecraft.
    """

    STALE_TASK_DAYS = 3  # задача считается зависшей если нет активности N дней

    async def check_stale_tasks(self, project_id: UUID) -> list[dict]:
        # 1. Получить все задачи проекта из Трекера (list_issues)
        # 2. Для каждой задачи в статусе "in_progress":
        #    - проверить дату последнего обновления
        #    - если > STALE_TASK_DAYS дней → пометить как stale
        # 3. Записать в agent_logs
        # 4. Вернуть список stale задач с деталями

    async def check_repo_activity(self, repo_id: str) -> dict:
        # 1. Получить активность репозитория за последние 7 дней
        # 2. Если commits == 0 за 3+ дня → флаг "no_activity"
        # 3. Вернуть сводку: {"repo_id", "commits_7d", "open_prs", "alert": bool}

    async def run_project_check(self, project_id: UUID, repo_id: str | None = None) -> dict:
        # Сводный чек проекта:
        # - stale_tasks от check_stale_tasks
        # - repo_summary от check_repo_activity (если repo_id передан)
        # - Если есть алерты → добавить комментарий в Трекер
        # - Вернуть: {"project_id", "stale_tasks", "repo_summary", "alerts_sent": bool}
```

Добавь в Orchestrator периодический запуск Monitor:
```python
# В run() loop Orchestrator добавь счётчик итераций
# Каждые 1800 секунд (30 минут) запускать monitor.run_project_check()
# для всех активных проектов из БД
```

---

## ЗАДАЧА 4: Эндпоинты для РП (src/api/applications.py)

Добавь HITL эндпоинты — решения руководителя проекта:

```python
class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str  # обязательный комментарий РП

# POST /api/v1/applications/{id}/decision
# Принимает ApprovalDecision
# Проверяет что статус == "scoring" (иначе 409)
# Обновляет application.status → "approved" или "rejected"
# Добавляет комментарий в Трекер задачу
# Если approve → кладёт в Redis очередь orchestrator:research
# Если reject → обновляет статус проекта → "rejected"
# Записывает в agent_logs
# Возвращает обновлённый ApplicationResponse

# GET /api/v1/applications/pending
# Список заявок в статусе "scoring" ожидающих решения РП
# Для дашборда РП
```

---

## ЗАДАЧА 5: Сводка проекта (src/api/projects.py)

Добавь эндпоинт сводки:

```python
class ProjectStatusResponse(BaseModel):
    project_id: UUID
    title: str
    status: str
    application: dict | None       # последняя заявка с scorecard
    research_report: dict | None   # отчёт если есть
    tracker_tasks: list[dict]      # задачи из Трекера
    recent_agent_logs: list[dict]  # последние 5 действий агентов
    created_at: datetime

# GET /api/v1/projects/{id}/status
# Агрегирует данные из:
# - БД (project + application + documents + agent_logs)
# - Трекер API (list_issues для этого проекта)
# Возвращает ProjectStatusResponse
# Timeout на Tracker запрос: 10 секунд, при ошибке → tracker_tasks: []
```

---

## ЗАДАЧА 6: Расширенный health-check

Замени простой /health на информативный:

```python
# GET /health
# Проверяет доступность всех зависимостей:
{
  "status": "ok" | "degraded" | "error",
  "version": "0.1.0",
  "checks": {
    "database": "ok" | "error",
    "redis": "ok" | "error",
    "yandex_cloud": "ok" | "error",
    "tracker": "ok" | "error"
  },
  "timestamp": "2026-04-07T..."
}
# Статус "degraded" если tracker/yc недоступны но db+redis OK
# Статус "error" если db или redis недоступны
# Никогда не возвращать 500 — всегда 200 с полем status
```

---

## ЗАДАЧА 7: Тестовые фикстуры для демо (src/fixtures/)

Создай файл `src/fixtures/demo_data.py` и эндпоинт для его запуска:

```python
# Три тестовые заявки разного качества:

DEMO_APPLICATIONS = [
    {
        "initiator_name": "Анна Соколова",
        "initiator_email": "sokolova@example.com",
        "title": "ИИ-диагностика ранних стадий диабета по данным носимых устройств",
        "domain": "медицина",
        "text": """
        Предлагаем разработать систему ранней диагностики диабета 2 типа
        на основе анализа данных с носимых устройств (ЧСС, активность, сон).
        Планируется использование ML-моделей на данных 10 000 пациентов.
        Партнёр: НМИЦ эндокринологии. Срок: 18 месяцев. Бюджет: 4.5 млн руб.
        """
    },
    {
        "initiator_name": "Пётр Волков",
        "initiator_email": "volkov@example.com",
        "title": "Мониторинг качества воздуха в школах",
        "domain": "экология",
        "text": """
        Хотим поставить датчики в школах и смотреть на воздух.
        Это важно для детей. Нужны деньги на датчики и сервер.
        """
    },
    {
        "initiator_name": "Мария Новикова",
        "initiator_email": "novikova@example.com",
        "title": "Адаптивная образовательная платформа для детей с дислексией",
        "domain": "образование",
        "text": """
        Разработка платформы с использованием NLP и компьютерного зрения
        для адаптации учебных материалов под детей с дислексией.
        Научная база: исследования НИУ ВШЭ. Пилот в 5 школах Москвы.
        Срок: 12 месяцев. Команда: 6 человек. Бюджет: 3.2 млн руб.
        """
    }
]

# POST /api/v1/demo/seed
# Создаёт все три заявки в БД
# Возвращает список созданных application_id
# Только для демо — добавить проверку что это не prod окружение
```

---

## ЗАДАЧА 8: Обновить HTML страницу (src/static/index.html)

Добавь в существующую страницу:

**Секция 5 — Решение РП:**
- Поле ID заявки
- Радио кнопки: Одобрить / Отклонить
- Поле для комментария РП (обязательное)
- Кнопка "Принять решение" → POST /api/v1/applications/{id}/decision

**Секция 6 — Демо данные:**
- Кнопка "Загрузить демо заявки" → POST /api/v1/demo/seed
- После нажатия: показать ID всех трёх созданных заявок

**Секция 7 — Сводка проекта:**
- Поле ID проекта
- Кнопка "Получить сводку" → GET /api/v1/projects/{id}/status
- Отображение: статус, задачи в трекере, последние действия агентов

Исправь все URL с `/applications` на `/api/v1/applications`.

---

## ЗАДАЧА 9: Финальная проверка docker-compose

В docker-compose.yml добавь:

```yaml
services:
  api:
    # Добавить healthcheck:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  db:
    # Добавить healthcheck:
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    # Добавить healthcheck:
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  # api.depends_on обновить:
  # db: condition: service_healthy
  # redis: condition: service_healthy
```

---

## ПОРЯДОК ВЫПОЛНЕНИЯ

1. Задача 1 — исправление StaticFiles (обязательно первой)
2. Задача 2 — Sourcecraft клиент
3. Задача 3 — Monitor Agent
4. Задача 4 — эндпоинты решений РП
5. Задача 5 — сводка проекта
6. Задача 6 — расширенный health-check
7. Задача 7 — тестовые фикстуры
8. Задача 8 — обновление HTML страницы
9. Задача 9 — docker-compose healthchecks

После каждого пункта жди подтверждения перед следующим.
При любых отклонениях от ТЗ — спрашивай.
````