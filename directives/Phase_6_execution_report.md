# Отчёт о выполнении: Фаза 6

## Контекст

Фаза 6 выполнена по требованиям `directives/Phase_6.md`.
Цель: интегрировать Deep Research реализацию из внешней папки `integrations/` в основной сервис, не ломая текущий pipeline `ResearchAgent.process()` и `Orchestrator`.

---

## 1) Перенос и адаптация Deep Research

### Что сделано

- Файл `integrations/deep_research.py` перенесён в `src/agents/deep_research.py`.
- Создан отдельный клиент `src/integrations/yandex_responses.py`:
  - `YandexResponsesClient.call(...) -> tuple[str, dict]`
  - `YandexResponsesClient.async_call(...)` через `asyncio.to_thread(...)`
  - кастомное исключение `YandexResponsesError`
  - авторизация через `YANDEX_API_KEY` и `YANDEX_PROJECT_ID` из настроек.

### Результат

- Логика Deep Research присутствует внутри основного `src/` контура.
- Появился выделенный интеграционный клиент под Responses API.

---

## 2) Обновление конфигурации

### Что сделано

В `src/core/config.py` добавлены новые поля:

- `yandex_api_key`
- `yandex_base_url`
- `yandex_project_id`
- `agent_project_analyst_id`
- `agent_research_strategist_id`
- `agent_technical_researcher_id`
- `agent_architect_id`
- `agent_roadmap_manager_id`
- `agent_hr_specialist_id`
- `agent_risk_analyst_id`
- `agent_quality_reviewer_id`
- `agent_synthesis_manager_id`

Все новые поля добавлены с `default=""` (или дефолтным URL), чтобы приложение поднималось без обязательной deep-конфигурации.

### Результат

- Конфиг готов к включению Deep Research через env без поломки fallback-режима.

---

## 3) Обновление `.env.example`

### Что сделано

Добавлена секция Yandex AI Studio:

- `YANDEX_API_KEY`
- `YANDEX_BASE_URL`
- `YANDEX_PROJECT_ID`
- 9 переменных `AGENT_*_ID` для prompt-id агентов.

### Результат

- Шаблон окружения теперь покрывает и Foundation Models путь, и Deep Research путь.

---

## 4) Гибридный `ResearchAgent` (deep + fallback)

### Что сделано

Файл: `src/agents/research.py`

Реализован гибридный режим:

- `_check_deep_research_available()` проверяет, что заполнены:
  - `YANDEX_PROJECT_ID`
  - все 9 `AGENT_*_ID`.
- `process(application_id)`:
  - читает `Application` как раньше;
  - собирает `tracker_context` из связанных задач проекта;
  - если deep-конфиг полон -> запускает `_run_deep_research(...)`;
  - иначе -> `_run_simple_research(...)` (старый путь через `YandexCloudAgentClient`).

Deep-путь:

- вызов `run_deep_research(...)` через `asyncio.to_thread(...)`;
- преобразование результата в единый формат отчёта:
  - `source=deep_research`, `decision`, `feasibility_score`, `quality_score`, `completeness_score`,
    `executive_summary`, `final_report`, `duration_sec`, `agents_completed`, `agents_total`;
- сохранение отчёта в `documents` (`doc_type="research_report"`);
- логирование каждого шага deep pipeline в `agent_logs` с `agent_name=deep_research/<agent>`;
- публикация summary в Tracker с decision/score/agents/executive summary.

Fallback-путь:

- сохранён прежний сценарий one-shot research через Foundation Models API;
- сохранены логирование и публикация комментария в Tracker.

### Результат

- Сигнатура `process(application_id: UUID) -> dict` не изменена.
- `Orchestrator` и существующий pipeline продолжают работать без изменений.
- Deep Research активируется только при наличии полной конфигурации.

---

## 5) Проверка миграции `documents.content`

### Что сделано

- Проверена ORM-модель `Document.content` в `src/db/models.py`: используется `Text`.
- Дополнительная Alembic миграция не потребовалась.

### Результат

- Поле уже подходит для хранения большого Markdown отчёта (`final_report`).

---

## 6) Обновление HTML интерфейса

### Что сделано

Файл: `src/static/index.html` (Секция 4 "Research отчёт")

Добавлено условное отображение для `source == "deep_research"`:

- `Decision` с цветовой подсветкой:
  - `GO` — зеленый
  - `GO WITH CONDITIONS` — желтый
  - остальные — красный
- три score-бара:
  - `Feasibility`
  - `Quality`
  - `Completeness`
- `Agents completed: N/9`
- отдельный блок `Executive Summary`
- кнопка "Показать полный отчёт" (toggle `final_report` в mono/pre-wrap).

Для fallback-отчёта сохранён прежний рендер.

### Результат

- UI поддерживает оба формата отчётов: старый и deep-research.

---

## 7) Удаление папки `integrations/`

### Что сделано

- После переноса удалена папка `integrations/` целиком.

### Результат

- В проекте остался единый кодовый контур в `src/`.

---

## Дополнительные изменения

- В `requirements.txt` добавлены зависимости для deep-модуля:
  - `requests`
  - `python-dotenv`
- В `src/schemas/application.py` модель `ResearchReport` расширена опциональными полями deep-формата, чтобы API мог возвращать оба вида отчётов без breaking changes.

---

## Проверки

Выполнено:

- `python3 -m compileall src` — успешно;
- `ReadLints` по изменённым файлам — ошибок не обнаружено.

---

## Итог Фазы 6

Фаза 6 завершена:

- Deep Research интегрирован в основной backend;
- `ResearchAgent` стал гибридным (deep/fallback) без нарушения текущего пайплайна;
- окружение и UI обновлены под новый формат отчёта;
- устаревшая внешняя папка `integrations/` удалена.
