В папке integrations/ находится файл deep_research.py — реализация 
Deep Research системы от коллеги. Твоя задача: проанализировать его 
и интегрировать в наш сервис. В конце работы папку integrations/ удалить.

---

## ЧТО ДЕЛАЕТ КОД КОЛЛЕГИ (обязательно прочитай перед работой)

deep_research.py реализует мультиагентную систему из 9 последовательных 
агентов через Yandex AI Studio Responses API (/v1/responses с prompt ID).

Агенты запускаются по цепочке:
project_analyst → research_strategist → technical_researcher → 
architect → roadmap_manager → hr_specialist → risk_analyst → 
quality_reviewer → synthesis_manager

Входные данные функции run_deep_research():
- project_description: str  — описание проекта
- tracker_context: str      — данные из Трекера (у нас есть!)
- source_craft_context: str — данные из Sourcecraft (у нас есть!)
- artifact_dir: str         — папка для сохранения файлов

Выходные данные (dict):
- project_name: str
- decision: "GO" | "GO WITH CONDITIONS" | "NO-GO" | "NEEDS REVISION"
- feasibility_score: float
- quality_score: float  
- completeness_score: float
- executive_summary: str
- final_report: str (полный Markdown отчёт)
- agent_runs: list (лог каждого агента)
- duration_sec: float

Использует ДРУГОЙ Yandex API чем наш текущий:
- Endpoint: https://ai.api.cloud.yandex.net/v1/responses
- Авторизация: Api-Key + заголовок OpenAI-Project: {project_id}
- Тело: {"prompt": {"id": prompt_id}, "input": "текст"}
- Переменные: YANDEX_API_KEY, YANDEX_BASE_URL, YANDEX_PROJECT_ID
- На каждого агента отдельный env var: AGENT_PROJECT_ANALYST_ID,
  AGENT_RESEARCH_STRATEGIST_ID, AGENT_TECHNICAL_RESEARCHER_ID,
  AGENT_ARCHITECT_ID, AGENT_ROADMAP_MANAGER_ID, AGENT_HR_SPECIALIST_ID,
  AGENT_RISK_ANALYST_ID, AGENT_QUALITY_REVIEWER_ID, AGENT_SYNTHESIS_MANAGER_ID

---

## ЧТО СДЕЛАНО У НАС (не ломать)

src/agents/research.py содержит ResearchAgent который:
- Использует Foundation Models API (YandexCloudAgentClient)
- Один агент с одним промптом
- Сохраняет отчёт в таблицу documents (doc_type="research_report")
- Пишет в agent_logs
- Добавляет комментарий в Трекер

Наш подход проще но уже встроен в пайплайн Orchestrator.

---

## ЗАДАЧА 1: Перенос и адаптация deep_research.py

1. Скопируй integrations/deep_research.py в src/agents/deep_research.py
   без изменений в основной логике YandexResponsesClient и агентов.

2. Создай src/integrations/yandex_responses.py — выдели из deep_research.py
   только класс YandexResponsesClient как отдельный клиент:
   - Метод call(prompt_id, input_text, timeout_sec, retries) -> Tuple[str, dict]
   - Кастомное исключение YandexResponsesError
   - Авторизация через YANDEX_API_KEY и YANDEX_PROJECT_ID из core/config.py
   - Async обёртка: сделай async_call() через asyncio.to_thread(self.call, ...)
     так как оригинал синхронный через requests

---

## ЗАДАЧА 2: Обновить src/core/config.py

Добавь новые переменные окружения к существующим Settings:

```python
# Yandex AI Studio (Responses API) — для Deep Research агентов
yandex_api_key: str = ""
yandex_base_url: str = "https://ai.api.cloud.yandex.net/v1"
yandex_project_id: str = ""

# Agent prompt IDs (Yandex AI Studio)
agent_project_analyst_id: str = ""
agent_research_strategist_id: str = ""
agent_technical_researcher_id: str = ""
agent_architect_id: str = ""
agent_roadmap_manager_id: str = ""
agent_hr_specialist_id: str = ""
agent_risk_analyst_id: str = ""
agent_quality_reviewer_id: str = ""
agent_synthesis_manager_id: str = ""
```

Все поля с default="" чтобы сервис стартовал даже без этих ключей.

---

## ЗАДАЧА 3: Обновить .env.example

Добавь секцию:
```
# ── Yandex AI Studio (Deep Research Agents) ──────────────────────────
YANDEX_API_KEY=
YANDEX_BASE_URL=https://ai.api.cloud.yandex.net/v1
YANDEX_PROJECT_ID=

# Agent Prompt IDs (настраиваются в Yandex AI Studio)
AGENT_PROJECT_ANALYST_ID=
AGENT_RESEARCH_STRATEGIST_ID=
AGENT_TECHNICAL_RESEARCHER_ID=
AGENT_ARCHITECT_ID=
AGENT_ROADMAP_MANAGER_ID=
AGENT_HR_SPECIALIST_ID=
AGENT_RISK_ANALYST_ID=
AGENT_QUALITY_REVIEWER_ID=
AGENT_SYNTHESIS_MANAGER_ID=
```

---

## ЗАДАЧА 4: Обновить src/agents/research.py

Сделай ResearchAgent гибридным — использует deep research если 
agent IDs настроены, иначе fallback на старый YandexCloudAgentClient:

```python
class ResearchAgent:
    def __init__(self, yc_client, tracker_client, db_session):
        self.yc_client = yc_client          # старый клиент (fallback)
        self.tracker_client = tracker_client
        self.db = db_session
        self._use_deep_research = self._check_deep_research_available()

    def _check_deep_research_available(self) -> bool:
        # Возвращает True если все 9 AGENT_*_ID заданы в settings
        # и YANDEX_PROJECT_ID не пустой
        required = [
            settings.agent_project_analyst_id,
            settings.agent_research_strategist_id,
            # ... все 9
        ]
        return all(required)

    async def process(self, application_id: UUID) -> dict:
        # 1. Читаем Application из БД
        # 2. Собираем tracker_context через TrackerClient.list_issues()
        #    для задач связанных с этим проектом
        # 3. Собираем source_craft_context = "" (пока пустой, Sourcecraft опционален)
        # 4. Формируем project_description из application данных

        if self._use_deep_research:
            return await self._run_deep_research(application, tracker_context)
        else:
            return await self._run_simple_research(application)

    async def _run_deep_research(self, application, tracker_context: str) -> dict:
        # Запускаем через asyncio.to_thread так как deep_research синхронный
        from agents.deep_research import run_deep_research

        project_description = self._build_project_description(application)

        result = await asyncio.to_thread(
            run_deep_research,
            project_description=project_description,
            tracker_context=tracker_context,
            source_craft_context="",
            artifact_dir=None,        # не сохраняем в файлы
            print_agent_outputs=False,
            continue_on_agent_error=True,  # не падаем при ошибке агента
        )

        # Преобразуем в наш формат и сохраняем
        report_data = {
            "source": "deep_research",
            "project_name": result.get("project_name"),
            "decision": result.get("decision"),
            "feasibility_score": result.get("feasibility_score"),
            "quality_score": result.get("quality_score"),
            "completeness_score": result.get("completeness_score"),
            "executive_summary": result.get("executive_summary"),
            "final_report": result.get("final_report"),
            "duration_sec": result.get("duration_sec"),
            "agents_completed": len([r for r in result.get("agent_runs", []) if r.get("success")]),
            "agents_total": len(result.get("agent_runs", [])),
        }

        # Сохраняем в documents (как делали раньше)
        await self._save_report(application, report_data)
        
        # Логируем каждый agent_run из deep research в наш agent_logs
        await self._log_agent_runs(application, result.get("agent_runs", []))
        
        # Публикуем в Трекер
        await self._post_to_tracker(application, report_data)

        return report_data

    async def _log_agent_runs(self, application, agent_runs: list):
        # Для каждого AgentRun из deep_research пишем запись в agent_logs:
        # agent_name = "deep_research/{agent_name}"
        # action = "deep_research_step"  
        # input_payload = {"input_text": run.input_text[:500]}
        # output_payload = {"output_text": run.output_text[:1000], 
        #                   "duration_sec": run.duration_sec,
        #                   "success": run.success}
        # status = "success" если run.success else "error"

    async def _post_to_tracker(self, application, report_data: dict):
        # Находим tracker_issue_id из tasks таблицы для этой заявки
        # Публикуем комментарий с:
        # - Decision: GO/NO-GO
        # - Feasibility: X, Quality: Y, Completeness: Z  
        # - Agents completed: N/9
        # - Executive Summary (первые 500 символов)
        # - Статус: "Deep Research завершён, ожидает review РП"
```

---

## ЗАДАЧА 5: Добавить новую Alembic миграцию

В таблицу documents поле content может быть очень большим 
(full markdown report). Убедись что тип TEXT (не VARCHAR).
Если нужно — создай миграцию:
alembic revision -m "ensure_documents_content_text"

---

## ЗАДАЧА 6: Обновить HTML страницу (src/static/index.html)

В Секцию 4 (Research отчёт) добавь отображение полей deep research:
- Decision с цветовой подсветкой:
  GO → зелёный, GO WITH CONDITIONS → жёлтый, NO-GO → красный
- Три score-бара: Feasibility / Quality / Completeness (число из 100)
- Поле "Agents completed: N/9"  
- Executive Summary в отдельном блоке
- Кнопка "Показать полный отчёт" которая разворачивает final_report
  в блоке с моноширинным шрифтом (pre-wrap)

Эти поля показывать только если response содержит поле "source": "deep_research".
Для fallback (старый research) — прежний отображение.

---

## ЗАДАЧА 7: Удалить папку integrations/

После успешного выполнения всех задач:
- Убедись что integrations/deep_research.py скопирован в src/agents/
- Убедись что integrations/_env данные учтены в .env.example
- Удали папку integrations/ полностью (rm -rf integrations/)

---

## ВАЖНЫЕ ОГРАНИЧЕНИЯ

1. НЕ ломать существующий пайплайн Orchestrator — он продолжает 
   вызывать ResearchAgent.process() как раньше
2. НЕ менять сигнатуру process(application_id: UUID) -> dict
3. Fallback на старый research должен работать если agent IDs не заданы
4. deep_research.py использует синхронный requests — 
   оборачивай в asyncio.to_thread везде где вызываешь
5. Не хардкодить YANDEX_API_KEY — только через settings

---

## ПОРЯДОК ВЫПОЛНЕНИЯ

1. Прочитай integrations/deep_research.py полностью
2. Задача 1 (перенос файла и выделение клиента)
3. Задача 2 + 3 (config и env)
4. Задача 4 (обновление ResearchAgent)
5. Задача 5 (миграция если нужна)
6. Задача 6 (HTML)
7. Задача 7 (удаление папки integrations/)
