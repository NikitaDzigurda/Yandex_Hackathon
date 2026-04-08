# Phase 7: Интеграция Deep Intake (Committee of Agents) и переход на Native Async

## Контекст
В папку `integrations/` добавлены файлы нового механизма оценки заявок (Deep Intake), который использует паттерн "Комитет Агентов" (Technical Analyst, Market Researcher, Innovator, Risk Assessor -> Moderator).
Также в Фазе 6 был интегрирован Deep Research, но он использует блокирующий `asyncio.to_thread`.

**Цель этой фазы:**
1. Перенести логику комитета агентов из `integrations/proposal_evaluator.py` в основной пайплайн `src/agents/intake.py`.
2. Избавиться от синхронных вызовов (`requests`, `ThreadPoolExecutor`, `asyncio.to_thread`).
3. Переписать `YandexResponsesClient`, `Deep Intake` и `Deep Research` на чистый нативный `async/await` с использованием `httpx.AsyncClient` и `asyncio.gather`.
4. Реализовать гибридный режим (Graceful Degradation) для Intake: если ключи комитета не заданы, использовать старый простой Intake.

Работай строго по шагам.

---

## ЗАДАЧА 1: Обновление конфигурации (src/core/config.py и .env.example)

1. В `src/core/config.py` добавь новые переменные с `default=""`:
```python
    eval_technical_analyst_id: str = ""
    eval_market_researcher_id: str = ""
    eval_innovator_id: str = ""
    eval_risk_assessor_id: str = ""
    eval_moderator_id: str = ""

Обнови .env.example, добавив эти же ключи в блок Yandex AI Studio.

ЗАДАЧА 2: Нативный Async Client (src/integrations/yandex_responses.py)

В Фазе 6 был создан YandexResponsesClient. Сейчас он, скорее всего, использует синхронный requests.
Перепиши его на httpx.AsyncClient.

import httpx
# Удали все упоминания синхронного requests

class YandexResponsesClient:
    def __init__(self, api_key: str, base_url: str, project_id: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.project_id = project_id
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def async_call(self, prompt_id: str, input_text: str, timeout_sec: int = 180, retries: int = 3) -> tuple[str, dict]:
        # Реализуй асинхронный вызов через httpx.AsyncClient
        # Добавь логику retry (через asyncio.sleep)
        # Формат возврата: (response_text, response_data_dict)
        # Удали старый синхронный метод call()
ЗАДАЧА 3: Нативный Async для Deep Research (src/agents/deep_research.py)

Удали использование asyncio.to_thread в src/agents/research.py.

Перепиши все функции внутри src/agents/deep_research.py так, чтобы они стали async def, и вызывай await client.async_call(...).

Там, где агенты могут работать параллельно, используй await asyncio.gather(...) вместо циклов for.

ЗАДАЧА 4: Интеграция Deep Intake (src/agents/intake.py)

Перенеси логику из integrations/proposal_evaluator.py в src/agents/intake.py.
Сделай класс IntakeAgent гибридным (по аналогии с ResearchAgent).

Добавь метод _check_deep_intake_available(self) -> bool, который проверяет наличие 5 eval_*_id в settings.

Обнови process(self, application_id: UUID):

async def process(self, application_id: UUID) -> IntakeResult:
        if self._check_deep_intake_available():
            return await self._run_deep_intake(application_id)
        else:
            return await self._run_simple_intake(application_id)

Перенеси логику из ProposalEvaluationSystem в _run_deep_intake.
ВАЖНО: Замени ThreadPoolExecutor на asyncio.gather.

async def _run_deep_intake(self, application_id: UUID) -> IntakeResult:
        # 1. Загрузка заявки
        # 2. Формирование prompt-ов для 4 экспертов
        
        # 3. Параллельный запуск экспертов:
        tasks =[
            self._call_expert("technical_analyst", settings.eval_technical_analyst_id, prompt),
            self._call_expert("market_researcher", settings.eval_market_researcher_id, prompt),
            self._call_expert("innovator", settings.eval_innovator_id, prompt),
            self._call_expert("risk_assessor", settings.eval_risk_assessor_id, prompt)
        ]
        tech_out, market_out, innov_out, risk_out = await asyncio.gather(*tasks)

        # 4. Запись промежуточных шагов в agent_logs (сохраняем trace для UI)
        
        # 5. Сборка промпта для Модератора и его запуск
        moderator_out = await self._call_expert("moderator", settings.eval_moderator_id, mod_prompt)

        # 6. Извлечение verdict (APPROVE/REJECT) и confidence.
        recommended_action = "approve" if "APPROVE" in verdict else "reject"

        # 7. Обновление БД, запись в Tracker и возврат IntakeResult

Вспомогательный метод _call_expert должен использовать await self.yandex_responses_client.async_call(...).

ЗАДАЧА 5: Адаптация формата и интерфейса

Поскольку UI (Секция 2 и Секция 7) ожидает массив scorecard из старого Intake, сгенерируй фейковый scorecard на основе confidence или заполни его заглушкой, чтобы фронтенд не сломался.
Или, еще лучше, запиши вывод moderator_out в поле summary заявки в БД.

Обязательно пиши каждый шаг (Технарь ответил, Маркетолог ответил и т.д.) в таблицу agent_logs, чтобы в Секции 7 "Журнал агентов" было видно, как комитет экспертов обсуждает заявку!

ЗАДАЧА 6: Очистка

Удали папку integrations/ со всем ее содержимым (proposal_evaluator.py, test_async_api.py и т.д.), так как мы полностью интегрировали и улучшили этот код в основном src/.

ИНСТРУКЦИЯ ДЛЯ CURSOR:
Выполни все 6 задач последовательно. Особое внимание удели отказу от to_thread и ThreadPoolExecutor в пользу asyncio.gather. Мы строим high-performance асинхронный пайплайн. Ждать подтверждения между шагами не нужно.