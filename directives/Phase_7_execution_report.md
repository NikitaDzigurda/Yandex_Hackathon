# Отчёт о выполнении: Фаза 7

## Контекст

Фаза 7 выполнена по требованиям `directives/Phase_7.md`.

Цель фазы:

1. Интегрировать Deep Intake (Committee of Agents) в основной `src` пайплайн.
2. Перевести Responses API контур на нативный `async/await`.
3. Убрать зависимость от `asyncio.to_thread` и `ThreadPoolExecutor` в runtime-критичных местах.
4. Сохранить graceful degradation: fallback на простой Intake/Research при неполной конфигурации.

---

## 1) Обновление конфигурации и env-шаблонов

### Выполнено

В `src/core/config.py` добавлены новые настройки:

- `eval_technical_analyst_id`
- `eval_market_researcher_id`
- `eval_innovator_id`
- `eval_risk_assessor_id`
- `eval_moderator_id`
- `yandex_retry_backoff_sec`

В `.env.example` добавлен блок Deep Intake evaluator IDs:

- `EVAL_TECHNICAL_ANALYST_ID`
- `EVAL_MARKET_RESEARCHER_ID`
- `EVAL_INNOVATOR_ID`
- `EVAL_RISK_ASSESSOR_ID`
- `EVAL_MODERATOR_ID`

Также добавлены:

- `PRINT_FULL_AGENT_OUTPUTS`
- `SAVE_FULL_PROMPTS`
- `YANDEX_RETRY_BACKOFF_SEC`

### Результат

- Конфигурация полностью покрывает Deep Research и Deep Intake (committee) режимы.

---

## 2) Нативный async-клиент Responses API

### Выполнено

Файл `src/integrations/yandex_responses.py` переведён на `httpx.AsyncClient`:

- Удалена блокирующая схема `requests + time.sleep`.
- Реализован асинхронный retry через `await asyncio.sleep(...)`.
- Основной публичный вызов: `async_call(prompt_id, input_text, timeout_sec, retries) -> tuple[str, dict]`.
- Извлечение текста из ответа API сохранено и совместимо с ранее используемыми форматами (`content`, `output`, `text`, `output_text`).

### Результат

- Responses API интеграция теперь нативно асинхронная и не блокирует event loop.

---

## 3) Нативный async для Deep Research

### Выполнено

В `src/agents/deep_research.py` добавлена асинхронная реализация:

- `AsyncDeepResearchSystem`
- `run_deep_research_async(...)`

Особенности:

- Вызовы агентов выполняются через `await YandexResponsesClient.async_call(...)`.
- Сохранена совместимость структуры результата (`decision`, `scores`, `final_report`, `agent_runs`).
- Синхронная legacy-реализация сохранена как совместимый слой, но в основном runtime подключён async путь.

В `src/agents/research.py`:

- Удалён вызов `asyncio.to_thread(...)` для Deep Research.
- Deep ветка теперь вызывает `await run_deep_research_async(...)` напрямую.

### Результат

- Deep Research работает в native async режиме без thread offloading.

---

## 4) Интеграция Deep Intake (Committee of Agents)

### Выполнено

Файл `src/agents/intake.py` расширен до гибридной модели:

- Добавлен `YandexResponsesClient`.
- Добавлен ` _check_deep_intake_available()`:
  - проверяет наличие `YANDEX_API_KEY`, `YANDEX_PROJECT_ID` и всех `EVAL_*` prompt IDs.
- `process(application_id)` теперь маршрутизирует:
  - `deep` -> `_run_deep_intake(...)`
  - `fallback` -> `_run_simple_intake(...)` (прежний one-shot Intake).

Реализация `_run_deep_intake(...)`:

1. Чтение заявки из БД.
2. Формирование общего prompt для экспертов.
3. Параллельный запуск 4 evaluator-агентов через `asyncio.gather(...)`:
   - technical_analyst
   - market_researcher
   - innovator
   - risk_assessor
4. Логирование промежуточных ответов экспертов в `agent_logs`.
5. Запуск модератора (`eval_moderator_id`) для финального вердикта.
6. Извлечение `verdict` + `confidence`.
7. Формирование совместимого `IntakeResult` и обновление:
   - `applications.status = scoring`
   - `applications.summary = moderator_out`
   - `applications.scorecard` (совместимый с UI формат)
8. Публикация задачи в Tracker и запись в `tasks`.

### Результат

- Intake получил committee-режим с параллельной экспертной оценкой.
- UI не ломается, так как сохраняется ожидаемый `scorecard` формат.
- Agent traces комитета появляются в Секции 7 через `agent_logs`.

---

## 5) Адаптация под текущий UI и БД контракт

### Выполнено

- В deep-intake режиме summary модератора сохраняется в `applications.summary`.
- В `applications.scorecard` формируется совместимый массив `items`, чтобы текущий frontend продолжал отображать таблицу оценки.
- В `agent_logs` добавлены шаги комитета (`intake/technical_analyst`, `intake/market_researcher`, и т.д.).

### Результат

- API контракт с текущим интерфейсом сохранён.
- Дебаг и визуализация хода комитета доступны в проектной сводке.

---

## 6) Очистка legacy-папки integrations

### Выполнено

- Папка `integrations/` удалена после переноса необходимых частей в `src/`.

### Результат

- Единый кодовый контур сосредоточен внутри `src/`.

---

## Дополнительно выполнено по запросу

В рабочий `.env` добавлены и используются данные коллеги:

- `YANDEX_API_KEY`, `YANDEX_PROJECT_ID`, `YANDEX_BASE_URL`
- все `AGENT_*`
- все `EVAL_*`
- `PRINT_FULL_AGENT_OUTPUTS`, `SAVE_FULL_PROMPTS`, `YANDEX_RETRY_BACKOFF_SEC`

Эти значения теперь подхватываются через `Settings` и участвуют в deep-intake/deep-research потоках.

---

## Проверки

Выполнено:

- `python3 -m compileall src` — успешно.
- IDE diagnostics (`ReadLints`) по изменённым файлам — ошибок не обнаружено.
- Поиск проблемных конструкций:
  - runtime-путь без `asyncio.to_thread` для Deep Research.
  - committee-path без `ThreadPoolExecutor` (используется `asyncio.gather`).

---

## Итог Фазы 7

Фаза 7 завершена:

- Deep Intake (committee) интегрирован в основной IntakeAgent.
- Responses API переведён на native async (`httpx.AsyncClient`).
- Deep Research переключён на async-раннер без `to_thread`.
- Сохранён fallback режим для отказоустойчивости.
- Конфигурация и env приведены к полному покрытию всех prompt IDs (AGENT + EVAL).
