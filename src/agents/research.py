"""Research Agent implementation."""

import json
import logging
import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.intake import IntakeParseError
from db.models import AgentLog, AgentLogStatus, Application, ApplicationStatus, Document, Task
from integrations.tracker import TrackerClient
from integrations.yandex_cloud import YandexCloudAgentClient
from schemas.application import ResearchReport

logger = logging.getLogger(__name__)

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
""".strip()


class ResearchAgent:
    def __init__(self, yc_client: YandexCloudAgentClient, tracker_client: TrackerClient, db_session: AsyncSession):
        self.yc_client = yc_client
        self.tracker_client = tracker_client
        self.db_session = db_session

    async def process(self, application_id: UUID) -> dict:
        result = await self.db_session.execute(select(Application).where(Application.id == application_id))
        application = result.scalar_one_or_none()
        if application is None:
            raise ValueError(f"Application not found: {application_id}")
        if application.status not in {ApplicationStatus.SCORING, ApplicationStatus.APPROVED}:
            raise ValueError("Application must be in scoring or approved status for research")

        user_message = await self._build_user_message(application)
        model_uri = self.yc_client.build_model_uri("yandexgpt-pro")
        raw = await self.yc_client.invoke_agent(
            model_uri=model_uri,
            system_prompt=RESEARCH_SYSTEM_PROMPT,
            user_message=user_message,
        )
        parsed = self._parse_response(raw)
        report = ResearchReport.model_validate(parsed)
        report_dict = report.model_dump(mode="json")

        self.db_session.add(
            Document(
                project_id=application.project_id,
                agent_name="research",
                doc_type="research_report",
                title=f"Research report for {application.title}",
                content=json.dumps(report_dict, ensure_ascii=False),
                version=1,
            )
        )

        self.db_session.add(
            AgentLog(
                project_id=application.project_id,
                correlation_id=uuid.uuid4(),
                agent_name="research",
                stage="research",
                action="process_application",
                input_payload={"application_id": str(application_id)},
                output_payload=report_dict,
                status=AgentLogStatus.SUCCESS,
            )
        )

        task_result = await self.db_session.execute(
            select(Task)
            .where(Task.project_id == application.project_id, Task.tracker_issue_id.is_not(None))
            .order_by(Task.created_at.desc())
            .limit(1)
        )
        tracker_task = task_result.scalar_one_or_none()
        if tracker_task and tracker_task.tracker_issue_id:
            await self._save_to_tracker(tracker_task.tracker_issue_id, report_dict)

        await self.db_session.commit()
        return report_dict

    async def _build_user_message(self, application: Application) -> str:
        return (
            f"Домен проекта: {application.domain}\n"
            f"Название: {application.title}\n"
            f"Описание:\n{application.text}\n\n"
            f"Summary от Intake:\n{application.summary or 'Не заполнено'}\n\n"
            "Сформируй структурированный research report строго в JSON."
        )

    async def _save_to_tracker(self, tracker_issue_id: str, report: dict):
        hypotheses_count = len(report.get("hypotheses", []))
        risks = report.get("risks", [])[:3]
        top_risks = "\n".join(
            f"- {risk.get('category', 'unknown')}: {risk.get('description', '')}"
            for risk in risks
        ) or "- Нет данных"
        text = (
            "Research завершён, ожидает review РП.\n\n"
            f"Количество гипотез: {hypotheses_count}\n"
            f"Top-3 риска:\n{top_risks}\n\n"
            f"Confidence score: {report.get('confidence_score', 'n/a')}"
        )
        await self.tracker_client.add_comment(tracker_issue_id, text)

    def _clean_json(self, raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            if len(lines) >= 3:
                raw = "\n".join(lines[1:-1])
            else:
                raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        return raw.strip()

    def _parse_response(self, raw: str) -> dict:
        candidate = self._clean_json(raw)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            logger.exception("Failed to parse research response. Raw: %s", raw)
            raise IntakeParseError("Invalid JSON from research model") from exc
