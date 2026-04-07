"""Intake Agent implementation."""

import json
import logging
import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from db.models import AgentLog, AgentLogStatus, Application, ApplicationStatus, Task
from integrations.tracker import TrackerClient
from integrations.yandex_cloud import YandexCloudAgentClient
from schemas.application import IntakeResult, ScorecardItem

logger = logging.getLogger(__name__)

INTAKE_SYSTEM_PROMPT = """
Ты — эксперт по оценке проектных заявок для Центра технологий для Общества.
Центр реализует проекты на стыке медицины, экологии, науки, образования и ИИ.

Твоя задача: провести первичную экспертную оценку заявки по 5 критериям.

КРИТЕРИИ ОЦЕНКИ (каждый от 1 до 10):
1. Актуальность — насколько проблема релевантна для общества и науки
2. Реализуемость — техническая и организационная осуществимость
3. Инновационность — новизна подхода, отличие от существующих решений
4. Социальный эффект — потенциальная польза для общества
5. Ресурсная обоснованность — соответствие заявленных ресурсов масштабу задачи

ФОРМАТ ОТВЕТА (строго JSON, без markdown):
{
  "scorecard": [
    {
      "criterion": "Актуальность",
      "score": 8,
      "rationale": "..."
    }
  ],
  "clarifying_questions": [
    "Вопрос 1 если нужно уточнить",
    "Вопрос 2"
  ],
  "summary": "Краткое резюме заявки для руководителя проекта (3-5 предложений)",
  "recommended_action": "approve | reject | clarify",
  "overall_score": 7.4
}

Если суммарный балл >= 6.0 — рекомендуй approve.
Если суммарный балл < 4.0 — рекомендуй reject.
Иначе — clarify (нужны уточнения).
Отвечай только JSON, без вступлений и объяснений вне JSON.
""".strip()


class IntakeParseError(Exception):
    """Raised when model response cannot be parsed."""


class IntakeAgent:
    def __init__(self, yc_client: YandexCloudAgentClient, tracker_client: TrackerClient, db_session: AsyncSession):
        self.yc_client = yc_client
        self.tracker_client = tracker_client
        self.db_session = db_session

    async def process(self, application_id: UUID) -> IntakeResult:
        result = await self.db_session.execute(select(Application).where(Application.id == application_id))
        application = result.scalar_one_or_none()
        if application is None:
            raise ValueError(f"Application not found: {application_id}")

        user_message = await self._build_user_message(application)
        model_uri = self.yc_client.build_model_uri("yandexgpt-pro")
        raw = await self.yc_client.invoke_agent(
            model_uri=model_uri,
            system_prompt=INTAKE_SYSTEM_PROMPT,
            user_message=user_message,
        )
        parsed = await self._parse_response(raw)

        intake_result = IntakeResult(
            application_id=application.id,
            scorecard=[ScorecardItem(**item) for item in parsed.get("scorecard", [])],
            clarifying_questions=parsed.get("clarifying_questions", []),
            summary=parsed.get("summary", ""),
            recommended_action=parsed.get("recommended_action", "clarify"),
        )

        application.scorecard = {
            "items": [item.model_dump() for item in intake_result.scorecard],
            "overall_score": parsed.get("overall_score"),
        }
        application.summary = intake_result.summary
        application.status = ApplicationStatus.SCORING

        correlation_id = uuid.uuid4()
        self.db_session.add(
            AgentLog(
                project_id=application.project_id,
                correlation_id=correlation_id,
                agent_name="intake",
                stage="intake",
                action="process_application",
                input_payload={"application_id": str(application.id)},
                output_payload=intake_result.model_dump(mode="json"),
                status=AgentLogStatus.SUCCESS,
            )
        )

        issue = await self.tracker_client.create_issue(
            queue=settings.tracker_queue_key,
            summary=f"[Intake] {application.title}",
            description=self._build_tracker_description(application, intake_result),
            tags=["intake", "mvp"],
        )
        self.db_session.add(
            Task(
                project_id=application.project_id,
                tracker_issue_id=issue.get("key") or issue.get("id"),
                title=f"Intake review: {application.title}",
                description=intake_result.summary,
                status="created",
            )
        )

        await self.db_session.commit()
        await self.db_session.refresh(application)
        return intake_result

    async def _build_user_message(self, application: Application) -> str:
        attachments = ", ".join(application.attachments_url or [])
        return (
            f"Название: {application.title}\n"
            f"Домен: {application.domain}\n"
            f"Инициатор: {application.initiator_name} <{application.initiator_email}>\n"
            f"Вложения: {attachments if attachments else 'нет'}\n\n"
            f"Текст заявки:\n{application.text}"
        )

    async def _parse_response(self, raw: str) -> dict:
        candidate = raw.strip()
        if candidate.startswith("```"):
            candidate = candidate.strip("`")
            candidate = candidate.replace("json", "", 1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            logger.exception("Failed to parse intake response. Raw: %s", raw)
            raise IntakeParseError("Invalid JSON from intake model") from exc

    def _build_tracker_description(self, application: Application, result: IntakeResult) -> str:
        score_lines = "\n".join(
            f"- {item.criterion}: {item.score}/10 ({item.rationale})"
            for item in result.scorecard
        )
        questions = "\n".join(f"- {q}" for q in result.clarifying_questions) or "- Нет"
        return (
            f"Резюме:\n{result.summary}\n\n"
            f"Оценка:\n{score_lines}\n\n"
            f"Уточняющие вопросы:\n{questions}\n\n"
            f"Рекомендация: {result.recommended_action}\n"
            f"Application ID: {application.id}"
        )
