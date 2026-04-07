# Отчёт о выполнении: Фаза 4

## Контекст

Фаза 4 выполнена по `directives/Phase_4.md`:
1. исправление риска `StaticFiles` vs API;
2. Sourcecraft клиент;
3. базовый Monitor Agent + периодический запуск;
4. HITL эндпоинты решения РП;
5. сводка проекта `/projects/{id}/status`;
6. расширенный `/health`;
7. демо-фикстуры и endpoint seed;
8. обновление HTML интерфейса;
9. healthchecks в `docker-compose`.

Работа выполнена последовательно, без ожидания промежуточных подтверждений (по запросу пользователя).

---

## 1) Исправление StaticFiles и API префикса

Обновлены:
- `src/main.py`
- `src/static/index.html`

Сделано:
- API роутер подключён до статики и с префиксом `"/api/v1"`;
- `StaticFiles` остаётся смонтирован последним на `"/"`;
- все вызовы в HTML переведены на `"/api/v1/..."`.

Результат:
- исключён риск перекрытия API статикой.

---

## 2) Sourcecraft клиент

Обновлён:
- `src/integrations/sourcecraft.py`

Реализовано:
- `SourcecraftClient` c `httpx.AsyncClient`, timeout 30s;
- авторизация через `Bearer SOURCECRAFT_TOKEN`;
- методы:
  - `get_repo_activity(repo_id, days=7)`
  - `get_commits(repo_id, limit=20)`
  - `get_pr_status(repo_id)`
  - `list_repos(project_name=None)`
- централизованный `_request(...)`;
- кастомная ошибка `SourcecraftAPIError`;
- логирование ошибок по аналогии с Tracker client.

---

## 3) Monitor Agent (базовый)

Создан:
- `src/agents/monitor.py`

Реализовано:
- `MonitorAgent` с `STALE_TASK_DAYS = 3`;
- методы:
  - `check_stale_tasks(project_id)` — проверка stale задач через Tracker;
  - `check_repo_activity(repo_id)` — активность за 7 дней + open PRs;
  - `run_project_check(project_id, repo_id=None)` — агрегированный мониторинг + комментарий в Tracker при алертах;
  - `list_active_projects()` — выборка активных проектов.

Интеграция в Orchestrator:
- обновлён `src/agents/orchestrator.py`;
- добавлен периодический запуск мониторинга каждые 1800 секунд.

---

## 4) Эндпоинты решений РП (HITL)

Обновлён:
- `src/api/applications.py`

Добавлено:
- модель `ApprovalDecision`:
  - `decision: "approve" | "reject"`
  - `comment: str` (обязательный)
- `POST /api/v1/applications/{id}/decision`
  - допускается только при `status == scoring`;
  - обновляет статус заявки (`approved`/`rejected`);
  - пишет комментарий в Tracker;
  - при `approve` пушит заявку в очередь `orchestrator:research`;
  - при `reject` переводит статус проекта в `rejected`;
  - пишет событие в `agent_logs`.
- `GET /api/v1/applications/pending`
  - выдаёт заявки в `scoring` для дашборда РП.

---

## 5) Сводка проекта `/projects/{id}/status`

Обновлены:
- `src/api/projects.py`
- `src/schemas/project.py`

Добавлено:
- схема `ProjectStatusResponse`;
- endpoint `GET /api/v1/projects/{id}/status`:
  - агрегирует проект, последнюю заявку, research report, последние 5 agent logs;
  - подтягивает задачи из Tracker (через локальные `tracker_issue_id`);
  - оборачивает запрос к Tracker в timeout 10 секунд;
  - при ошибке Tracker возвращает `tracker_tasks: []`.

---

## 6) Расширенный `/health`

Обновлён:
- `src/main.py`

Реализовано:
- `/health` всегда возвращает HTTP 200;
- формат:
  - `status: ok | degraded | error`
  - `checks: database | redis | yandex_cloud | tracker`
  - `version`, `timestamp`
- логика статуса:
  - `error` если БД или Redis недоступны;
  - `degraded` если БД+Redis OK, но Tracker/YC недоступны;
  - `ok` если все проверки OK.

---

## 7) Тестовые фикстуры для демо

Созданы:
- `src/fixtures/demo_data.py`
- `src/api/demo.py`
- обновлён `src/api/router.py` (подключён demo router)

Реализовано:
- `DEMO_APPLICATIONS` с 3 тестовыми заявками;
- `POST /api/v1/demo/seed`:
  - создаёт три заявки и проекты;
  - возвращает список `application_ids`;
  - запрещён в `prod` через проверку `APP_ENV`.

Дополнительно:
- в `src/core/config.py` добавлено поле `app_env: str = "dev"`;
- в `.env.example` добавлено `APP_ENV=dev`.

---

## 8) Обновление HTML страницы

Обновлён:
- `src/static/index.html`

Добавлены:
- Секция 5: решение РП (`/api/v1/applications/{id}/decision`);
- Секция 6: загрузка демо-данных (`/api/v1/demo/seed`);
- Секция 7: сводка проекта (`/api/v1/projects/{id}/status`).

Также:
- сохранены исходные 4 секции;
- все API ошибки продолжают отображаться в UI.

---

## 9) Docker Compose healthchecks

Обновлён:
- `docker-compose.yml`

Добавлено:
- healthcheck для `api` (`curl -f /health`);
- healthcheck для `db` (`pg_isready`);
- healthcheck для `redis` (`redis-cli ping`);
- `depends_on` в `api` переведён на условия `service_healthy` для `db` и `redis`.

---

## Дополнительная синхронизация документации

Обновлён:
- `DEPLOY.md`

Сделано:
- в разделе сквозного тестирования URL приведены к новому префиксу `/api/v1/...`.

---

## Проверки

Проведено:
- IDE diagnostics по `src/` — ошибок не выявлено;
- `python -m compileall src` — успешная компиляция всех изменённых модулей.

---

## Итог

Фаза 4 закрыта полностью:
- интеграции и мониторинг добавлены;
- HITL и проектная сводка реализованы;
- demo UX расширен;
- контейнерная стабильность усилена healthcheck-ами;
- архитектура API стабилизирована с `"/api/v1"` + безопасным `StaticFiles` порядком.
