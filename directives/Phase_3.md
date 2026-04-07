
---

### 🔴 Критические проблемы

**1. Alembic миграция написана вручную, не через autogenerate**
Агент признал это сам. Риск: расхождение между ORM моделями и реальной схемой БД. При запуске `alembic upgrade head` таблицы могут создаться неправильно или упасть с ошибкой.

**2. `DATABASE_URL` для async, но Alembic требует sync URL**
Async engine (`postgresql+asyncpg://`) не работает напрямую в `alembic/env.py` без специальной настройки через `run_sync`. Если это не учтено — миграции не применятся.

**3. Redis очередь без воркера**
`POST /applications` кладёт `application_id` в Redis очередь `orchestrator:intake`, но воркер который читает эту очередь и вызывает IntakeAgent — не реализован. Очередь заполняется в никуда. Сейчас intake работает только через ручной триггер `/trigger-intake`.

---

### 🟡 Средние риски

**4. `trigger-intake` эндпоинт создаёт AgentLog и Task без проверки на дубли**
Если вызвать дважды — получим два AgentLog и две задачи в Трекере для одной заявки.

**5. `_parse_response` — нет защиты от markdown-обёртки**
YandexGPT иногда оборачивает JSON в ```json ... ```. Если это не обработано — `json.loads()` упадёт.

**6. HTML страница не сделана**
Для демо судьям важно показать живую цепочку визуально. Без неё придётся демонстрировать через curl или Swagger.

---

### ✅ Что сделано хорошо

- Async SQLAlchemy 2.0 style — правильный выбор
- `_request()` helper в TrackerClient — чистая архитектура
- lifespan startup check через `SELECT 1` — профессионально
- `ProjectDetailResponse` с вложенными applications — хорошая инициатива
- `email-validator` добавлен в requirements — предусмотрительно

---

## Фаза 3: Research Agent + Orchestrator + исправления

Создай файл `directives/Phase_3.md`:

````markdown
# Phase 3: Research Agent, Orchestrator, исправления Фазы 2

## Контекст
Фазы 0, 1, 2 завершены. Intake Agent реализован.
Задача Фазы 3:
1. Исправить критические проблемы Фазы 2
2. Реализовать Research Agent
3. Реализовать Orchestrator с Redis воркером
4. Собрать сквозную демо-цепочку с HTML страницей

---

## ЗАДАЧА 1: Исправления из Фазы 2 (делать первым)

### 1а. Alembic async настройка (src/migrations/env.py)

Перепиши env.py для корректной работы с async engine:

```python
# env.py должен использовать run_sync паттерн:
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
import asyncio

# Импортируй все модели чтобы autogenerate их видел:
from db.models import Base

config = context.config

def run_migrations_offline():
    # Sync URL для offline режима
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

В alembic.ini добавь:
```
sqlalchemy.url = postgresql+asyncpg://%(POSTGRES_USER)s:%(POSTGRES_PASSWORD)s@db:5432/%(POSTGRES_DB)s
```

### 1б. Защита от дублей в trigger-intake (src/api/applications.py)

В эндпоинте `POST /applications/{id}/trigger-intake` добавь проверку:
```python
# Перед запуском агента:
# Если application.status уже == "scoring" или "approved" или "rejected"
# → вернуть 409 Conflict с сообщением "Intake already processed for this application"
```

### 1в. Защита от markdown в _parse_response (src/agents/intake.py)

В методе `_parse_response` добавь очистку перед json.loads:
```python
def _clean_json(self, raw: str) -> str:
    # Убрать ```json ... ``` обёртку если есть
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1])
    return raw.strip()
```

---

## ЗАДАЧА 2: Research Agent (src/agents/research.py)

Реализуй полную логику Research Agent:

```python
RESEARCH_SYSTEM_PROMPT = """
Ты — эксперт-аналитик для Центра технологий для Общества.
Центр реализует проекты на стыке медицины, экологии, науки, образования и ИИ.

Тебе передаётся резюме одобренной проектной заявки.
Твоя задача: провести глубокий доменный анализ и сформировать
структурированный исследовательский отчёт.

СТРУКТУРА ОТЧЁТА (строго JSON, без markdown):
{
  "domain_overview": "Обзор предметной области (3-5 предложений)",
  "key_sources": [
    {
      "title": "Название источника / направления",
      "relevance": "Почему релевантен для проекта",
      "source_type": "academic | industry | opensource | regulation"
    }
  ],
  "hypotheses": [
    {
      "id": 1,
      "statement": "Формулировка гипотезы",
      "rationale": "Обоснование",
      "risk": "low | medium | high",
      "priority": 1
    }
  ],
  "risks": [
    {
      "category": "technical | organizational | ethical | regulatory",
      "description": "Описание риска",
      "mitigation": "Рекомендация по снижению"
    }
  ],
  "recommendations": "Итоговые рекомендации для команды проекта (3-5 предложений)",
  "confidence_score": 0.75
}

Гипотезы сортируй по приоритету (1 = наивысший).
confidence_score — твоя оценка полноты анализа (0.0 до 1.0).
Отвечай только JSON без вступлений.
"""

class ResearchAgent:
    def __init__(self, yc_client, tracker_client, db_session):
        ...

    async def process(self, application_id: UUID) -> dict:
        # 1. Читаем Application из БД (должна быть в статусе scoring/approved)
        # 2. Формируем user_message из summary + текста заявки + домена
        # 3. Вызываем YC агента с RESEARCH_SYSTEM_PROMPT
        #    Используем модель: yandexgpt-pro (или из env YC_AGENT_ID_RESEARCH)
        # 4. Парсим JSON ответ (та же защита от markdown что в IntakeAgent)
        # 5. Сохраняем отчёт в таблицу documents:
        #    doc_type="research_report", content=json.dumps(result)
        # 6. Пишем в agent_logs
        # 7. Добавляем комментарий в задачу Трекера с кратким summary отчёта
        # 8. Возвращаем распарсенный отчёт как dict

    async def _build_user_message(self, application) -> str:
        # Формирует запрос для агента из данных заявки:
        # - Домен проекта
        # - Название и описание
        # - Summary от Intake Agent
        # - Ключевые исследовательские вопросы из текста заявки

    async def _save_to_tracker(self, tracker_issue_id: str, report: dict):
        # Публикует в Трекер краткое резюме отчёта:
        # - количество гипотез
        # - топ-3 риска
        # - confidence_score
        # - статус: "Research завершён, ожидает review РП"
```

Добавь в src/schemas/application.py:
```python
class ResearchReport(BaseModel):
    domain_overview: str
    key_sources: list[dict]
    hypotheses: list[dict]
    risks: list[dict]
    recommendations: str
    confidence_score: float
```

---

## ЗАДАЧА 3: Orchestrator воркер (src/agents/orchestrator.py)

Реализуй Orchestrator как Redis воркер:

```python
class Orchestrator:
    """
    Читает события из Redis очереди и маршрутизирует их к агентам.
    Запускается как отдельный async loop (не FastAPI эндпоинт).
    """

    QUEUE_INTAKE = "orchestrator:intake"
    QUEUE_RESEARCH = "orchestrator:research"

    async def run(self):
        # Infinite loop: читаем из Redis, обрабатываем
        # BLPOP с timeout=5 секунд (неблокирующий)
        while True:
            try:
                await self._process_intake_queue()
                await self._process_research_queue()
                await asyncio.sleep(1)
            except Exception as e:
                logger.error("orchestrator_loop_error", error=str(e))
                await asyncio.sleep(5)

    async def _process_intake_queue(self):
        # LPOP из QUEUE_INTAKE
        # Если есть application_id:
        #   → обновить статус проекта в БД
        #   → запустить IntakeAgent.process(application_id)
        #   → при успехе: положить application_id в QUEUE_RESEARCH
        #   → при ошибке: записать в agent_logs status=error, не падать

    async def _process_research_queue(self):
        # LPOP из QUEUE_RESEARCH
        # Если есть application_id:
        #   → запустить ResearchAgent.process(application_id)
        #   → при успехе: обновить статус проекта → "awaiting_approval"
        #   → создать задачу в Трекере с типом "Требует решения РП"
        #   → при ошибке: записать в agent_logs status=error

    async def _update_project_status(self, project_id: UUID, status: str):
        # Обновляет статус проекта в БД
```

Добавь запуск Orchestrator в src/main.py через lifespan:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup:
    # - проверка БД (SELECT 1)
    # - запуск orchestrator.run() как asyncio.create_task()
    yield
    # shutdown:
    # - отмена task orchestrator
```

---

## ЗАДАЧА 4: Research эндпоинт (src/api/applications.py)

Добавь к существующим эндпоинтам:

```python
    POST /applications/{id}/trigger-research
    Запускает ResearchAgent вручную (для тестирования)
    Проверяет что application существует
    Возвращает ResearchReport

    GET /applications/{id}/report
    Возвращает research report из таблицы documents
    Если отчёт не готов → 404 с сообщением "Research report not available yet"
```

---

## ЗАДАЧА 5: Тестовая HTML страница (src/static/index.html)

Это обязательно для демо. Создай одностраничный интерфейс:

**Секция 1 — Подать заявку:**
- Поля: Имя инициатора, Email, Название проекта, Домен (select), Текст заявки
- Кнопка "Подать заявку" → POST /applications
- После успеха: показать ID заявки

**Секция 2 — Статус заявки:**
- Поле ввода ID заявки
- Кнопка "Проверить статус" → GET /applications/{id}
- Отображение: статус, scorecard таблицей (критерий / балл / обоснование)

**Секция 3 — Запустить агентов:**
- Кнопка "Запустить Intake" → POST /applications/{id}/trigger-intake
- Кнопка "Запустить Research" → POST /applications/{id}/trigger-research
- Результат отображается в блоке ниже в читаемом виде

**Секция 4 — Research отчёт:**
- Кнопка "Получить отчёт" → GET /applications/{id}/report
- Отображение: домен, гипотезы списком с приоритетом и риском, рекомендации

Технические требования:
- Чистый HTML + JavaScript (fetch API), никаких фреймворков
- Минимальный CSS для читаемости (не для красоты)
- Все ошибки API отображать в интерфейсе, не в консоли
- FastAPI раздаёт через StaticFiles mount на "/"

---

## ЗАДАЧА 6: Обновить DEPLOY.md

Добавь секцию тестирования сквозного сценария:

```markdown
## Тестирование сквозного сценария

# 1. Открыть тестовый интерфейс:
open http://localhost:8000

# 2. Или через curl — подать заявку:
curl -X POST http://localhost:8000/applications \
  -H "Content-Type: application/json" \
  -d '{
    "initiator_name": "Иван Петров",
    "initiator_email": "ivan@example.com",
    "title": "ИИ-диагностика ранних стадий диабета",
    "text": "Предлагаем разработать систему ранней диагностики...",
    "domain": "медицина"
  }'

# 3. Запустить Intake (подставить реальный ID):
curl -X POST http://localhost:8000/applications/{id}/trigger-intake

# 4. Запустить Research:
curl -X POST http://localhost:8000/applications/{id}/trigger-research

# 5. Получить отчёт:
curl http://localhost:8000/applications/{id}/report
```

---

## ПОРЯДОК ВЫПОЛНЕНИЯ

1. Задача 1 (исправления Фазы 2) — обязательно первой
2. src/agents/research.py
3. src/agents/orchestrator.py + обновление main.py
4. Новые эндпоинты в src/api/applications.py
5. src/static/index.html + StaticFiles в main.py
6. Обновить DEPLOY.md

После каждого пункта жди подтверждения перед следующим.
При любых отклонениях от ТЗ — спрашивай.
````