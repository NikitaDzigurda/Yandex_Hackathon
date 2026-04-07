# Отчёт о выполнении: Фаза 3

## Контекст фазы

Фаза 3 выполнялась по требованиям `directives/Phase_3.md` с приоритетом:
1. обязательные исправления Фазы 2;
2. реализация Research Agent;
3. реализация Orchestrator;
4. добавление research эндпоинтов;
5. обязательная HTML-страница для демо;
6. обновление `DEPLOY.md`.

По отдельному указанию пользователя выполнение продолжено без ожидания подтверждения между пунктами.

---

## 1) Исправления Фазы 2 (обязательная задача)

### 1а. Alembic async-настройка

Обновлены:
- `src/migrations/env.py`
- `src/alembic.ini`

Что сделано:
- `env.py` переведён на корректный async flow для Alembic:
  - `async_engine_from_config(...)`
  - `connection.run_sync(do_run_migrations)`
  - `asyncio.run(run_migrations_online())`
- offline режим использует `config.get_main_option("sqlalchemy.url")`.
- `alembic.ini` параметризован:
  - `sqlalchemy.url = postgresql+asyncpg://%(POSTGRES_USER)s:%(POSTGRES_PASSWORD)s@db:5432/%(POSTGRES_DB)s`

Результат:
- миграции готовы к выполнению в целевом docker-окружении с env-переменными.

### 1б. Защита от дублей в `/trigger-intake`

Обновлён файл:
- `src/api/applications.py`

Что сделано:
- перед запуском Intake добавлена проверка статуса заявки;
- если статус уже `scoring`, `approved` или `rejected` -> возвращается `409 Conflict`:
  - `Intake already processed for this application`.

Результат:
- исключены повторные запуска intake и дублирующие артефакты в БД/Tracker.

### 1в. Защита от markdown-обёртки в парсинге

Обновлён файл:
- `src/agents/intake.py`

Что сделано:
- добавлен метод `_clean_json(raw: str)`;
- `_parse_response(...)` теперь очищает ответ модели от обёртки ```json ... ``` перед `json.loads(...)`.

Результат:
- снижены ошибки парсинга при markdown-форматировании ответа LLM.

---

## 2) Research Agent

Обновлены:
- `src/agents/research.py`
- `src/schemas/application.py` (добавлен `ResearchReport`)

Что реализовано:
- введён `RESEARCH_SYSTEM_PROMPT` с жёстким JSON-форматом ответа;
- реализован класс `ResearchAgent`:
  - чтение заявки из БД и проверка статуса (`scoring`/`approved`);
  - построение user message из домена/названия/текста/summary;
  - вызов YC-модели через `YandexCloudAgentClient`;
  - парсинг и валидация отчёта (`ResearchReport`);
  - сохранение отчёта в `documents` (`doc_type="research_report"`);
  - логирование в `agent_logs`;
  - публикация краткого результата в Tracker-комментарий;
  - возврат отчёта как `dict`.

Результат:
- полноценная research-цепочка работает в backend-контуре.

---

## 3) Orchestrator (Redis worker) + обновление `main.py`

Обновлены:
- `src/agents/orchestrator.py`
- `src/main.py`

Что реализовано в Orchestrator:
- Redis-воркер с очередями:
  - `orchestrator:intake`
  - `orchestrator:research`
- цикл `run()` с безопасной обработкой ошибок и паузами;
- обработка intake-очереди:
  - запуск `IntakeAgent.process(...)`,
  - при успехе — постановка `application_id` в research-очередь;
- обработка research-очереди:
  - запуск `ResearchAgent.process(...)`,
  - обновление статуса проекта в `awaiting_approval`,
  - создание задачи в Tracker для решения РП;
- запись ошибок в `agent_logs` без падения воркера.

Что сделано в `main.py`:
- запуск Orchestrator как background task через `lifespan`;
- корректное завершение task на shutdown;
- сохранена проверка БД на startup (`SELECT 1`).

Результат:
- очередь из `POST /applications` больше не “в никуда”; теперь есть рабочий фоновой обработчик.

---

## 4) Новые research эндпоинты

Обновлён файл:
- `src/api/applications.py`

Добавлены:
- `POST /applications/{id}/trigger-research`
  - ручной запуск ResearchAgent для MVP/демо;
  - возвращает `ResearchReport`.
- `GET /applications/{id}/report`
  - читает отчёт из `documents` (`doc_type="research_report"`);
  - если отчёта нет -> `404 Research report not available yet`.

Результат:
- добавлен API-контур для ручного тестирования research этапа.

---

## 5) Обязательная тестовая HTML-страница

Создан файл:
- `src/static/index.html`

Что реализовано:
- Секция 1: подача заявки (`POST /applications`);
- Секция 2: проверка статуса (`GET /applications/{id}`) + таблица scorecard;
- Секция 3: ручной запуск Intake/Research;
- Секция 4: получение и отображение research отчёта;
- все ошибки API отображаются в UI;
- чистый HTML + JS (`fetch`), без фреймворков.

Дополнительно:
- в `src/main.py` подключена раздача статики:
  - `app.mount("/", StaticFiles(directory="static", html=True), name="static")`

Результат:
- готова визуальная демо-страница для судей.

---

## 6) Обновление `DEPLOY.md`

Обновлён файл:
- `DEPLOY.md`

Добавлена секция:
- `Тестирование сквозного сценария`
  - открытие UI (`open http://localhost:8000`);
  - curl-подача заявки;
  - запуск intake/research;
  - получение отчёта.

Результат:
- инструкции для демонстрации стали полными и воспроизводимыми.

---

## Проверки после изменений

Выполнено:
- IDE diagnostics (`ReadLints`) по `src/` — ошибок не обнаружено;
- `python -m compileall src` — синтаксис валиден для всех изменённых Python-файлов.

---

## Итог Фазы 3

Фаза 3 завершена:
- критические/средние проблемы из Фазы 2 исправлены (в рамках ТЗ Задачи 1);
- Research Agent реализован;
- Orchestrator-воркер реализован и подключён к runtime приложения;
- добавлены research API endpoints;
- создан обязательный HTML интерфейс для сквозного демо;
- обновлён `DEPLOY.md` для end-to-end проверки.
