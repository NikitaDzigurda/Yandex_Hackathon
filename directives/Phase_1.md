Фаза 0 завершена: файлы docs/architecture.md и docs/agents.md готовы.
Переходим к Фазе 1 — инфраструктурный скелет и оставшаяся документация.

Работаем строго в рамках стека:
- Python 3.11+, FastAPI, SQLAlchemy + Alembic, httpx, Redis
- PostgreSQL как основная БД
- docker-compose для запуска всего окружения
- Никаких захардкоженных секретов — только через .env

---

## ЗАДАЧА 1: Оставшаяся документация (docs/)

Создай три документа:

### docs/scenarios.md
Два сквозных сценария автоматизации:

Сценарий 1 — "Путь заявки": от подачи инициатором до задачи в Яндекс Трекере.
Каждый шаг должен содержать:
- Кто действует: агент или человек
- Что происходит технически
- Какой статус фиксируется в БД
- Точки HITL (human-in-the-loop) явно выделены

Сценарий 2 — "Глубокий ресёрч": от резюме заявки до структурированного отчёта.
Аналогичный формат пошагового описания.

### docs/data-model.md
Схема PostgreSQL со следующими таблицами:

projects:
  id, title, description, status, created_by, created_at, updated_at

applications:
  id, project_id, initiator_name, initiator_email, text, attachments_url,
  status (draft/submitted/scoring/approved/rejected),
  scorecard (JSONB — оценки по 5 критериям),
  summary (text — резюме для РП),
  created_at, updated_at

agent_logs:
  id, project_id, correlation_id, agent_name, stage, action,
  input_payload (JSONB), output_payload (JSONB),
  status (success/error/pending), created_at

tasks:
  id, project_id, tracker_issue_id, title, description,
  assigned_to, status, due_date, created_at, updated_at

documents:
  id, project_id, agent_name, doc_type, title,
  content (text), storage_url, version, created_at

Для каждой таблицы: описание назначения, типы полей, связи между таблицами.

### docs/integrations.md
Описание трёх интеграций:

Яндекс Трекер API:
- Базовый URL и авторизация (OAuth токен через env)
- Эндпоинты: создание задачи, обновление статуса, добавление комментария,
  получение списка задач, получение задачи по ID
- Для каждого: HTTP метод, путь, ключевые поля запроса/ответа

Sourcecraft API:
- Авторизация и базовый URL
- Эндпоинты: получение активности репозитория, список коммитов,
  статус pull request
- Для каждого: метод, путь, ключевые поля

Yandex Cloud Agents:
- Как агент конфигурируется через веб-консоль Yandex Cloud
- Как FastAPI вызывает агента (через REST API или SDK)
- Формат MCP-инструмента: структура tool_definition с name,
  description, parameters (JSON Schema)
- Пример вызова агента с MCP-инструментом из Python (псевдокод)

---

## ЗАДАЧА 2: Структура src/

Создай следующую структуру папок с файлами.
В каждом файле — только комментарии и заглушки, без реализации.

src/
├── main.py                        # Точка входа FastAPI, подключение роутеров
├── core/
│   ├── __init__.py
│   ├── config.py                  # Pydantic Settings, загрузка .env
│   └── logging.py                 # Настройка structlog с JSON форматом
├── db/
│   ├── __init__.py
│   ├── base.py                    # SQLAlchemy Base, engine, session
│   ├── models.py                  # ORM модели по data-model.md
│   └── migrations/                # Папка для Alembic
│       └── env.py                 # Стандартный Alembic env
├── api/
│   ├── __init__.py
│   ├── router.py                  # Подключение всех роутеров
│   ├── applications.py            # POST /applications, GET /applications/{id}
│   └── projects.py                # GET /projects, GET /projects/{id}
├── agents/
│   ├── __init__.py
│   ├── orchestrator.py            # Логика Orchestrator: маршрутизация, статусы
│   ├── intake.py                  # Intake Agent: промпт, вызов YC, парсинг ответа
│   └── research.py                # Research Agent: промпт, вызов YC, парсинг ответа
├── integrations/
│   ├── __init__.py
│   ├── tracker.py                 # Клиент Яндекс Трекера (httpx, async)
│   ├── sourcecraft.py             # Клиент Sourcecraft (httpx, async)
│   └── yandex_cloud.py            # Клиент Yandex Cloud Agents API (httpx, async)
└── schemas/
    ├── __init__.py
    ├── application.py             # Pydantic схемы для заявок
    └── project.py                 # Pydantic схемы для проектов

---

## ЗАДАЧА 3: docker-compose.yml

Создай рабочий docker-compose.yml с тремя сервисами:

api:
  - Билдится из ./src (Dockerfile нужно создать)
  - Порт: 8000
  - Зависит от db и redis
  - Переменные окружения из .env файла
  - Команда: uvicorn main:app --host 0.0.0.0 --port 8000 --reload

db:
  - Образ: postgres:16-alpine
  - База данных, пользователь, пароль — из переменных окружения
  - Volume для персистентности данных
  - Порт: 5432

redis:
  - Образ: redis:7-alpine
  - Порт: 6379

Также создай:
- .env.example с переменными (без реальных значений):
  DATABASE_URL, REDIS_URL,
  YC_API_KEY, YC_FOLDER_ID, YC_AGENT_ID_INTAKE, YC_AGENT_ID_RESEARCH,
  TRACKER_TOKEN, TRACKER_ORG_ID, TRACKER_QUEUE_KEY,
  SOURCECRAFT_TOKEN, SOURCECRAFT_BASE_URL
- src/Dockerfile (Python 3.11-slim, pip install, uvicorn запуск)

---

## ЗАДАЧА 4: DEPLOY.md

Создай DEPLOY.md с воспроизводимыми инструкциями:

1. Клонирование репозитория
2. Копирование .env.example в .env и заполнение значений
3. Запуск через docker compose up --build
4. Проверка что api доступен: curl http://localhost:8000/health
5. Запуск миграций: docker compose exec api alembic upgrade head
6. Как остановить: docker compose down

Никаких шагов типа "откройте IDE" — только shell команды.

---

## ПОРЯДОК ВЫПОЛНЕНИЯ

1. docs/scenarios.md
2. docs/data-model.md
3. docs/integrations.md
4. src/ структура (все файлы с заглушками)
5. docker-compose.yml + .env.example + Dockerfile
6. DEPLOY.md

После каждого пункта жди подтверждения перед следующим.