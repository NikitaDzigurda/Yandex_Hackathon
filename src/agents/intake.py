"""Intake Agent implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from db.models import AgentLog, AgentLogStatus, Application, ApplicationStatus, Task
from integrations.tracker import TrackerAPIError, TrackerClient
from integrations.yandex_cloud import YandexCloudAgentClient
from integrations.yandex_responses import YandexResponsesClient
from schemas.application import IntakeResult, ScorecardItem

logger = logging.getLogger(__name__)

INTAKE_SYSTEM_PROMPT = """
Ты — эксперт по оценке проектных заявок для Центра технологий для Общества.
Центр реализует проекты на стыке медицины, экологии, науки, образования и ИИ.

Твоя задача: провести первичную экспертную оценку заявки по 5 критериям.

КРИТЕРИИ ОЦЕНКИ (каждый от 1 до 10):
1. Актуальность — насколько проблема релевантна для общества и науки.
2. Реализуемость — техническая и организационная осуществимость.
3. Инновационность и ИТ-составляющая — СТРОГИЙ КРИТЕРИЙ: Если проект не является ИТ-продуктом (например, производство еды, физические тренировки) — ставь 1-2 балла. Высокий балл только для глубоких ИТ/ИИ решений.
4. Социальный эффект — потенциальная польза для общества.
5. Ресурсная обоснованность — СТРОГИЙ КРИТЕРИЙ: Насколько проекту реально нужны облачные мощности, GPU и ИИ от Yandex Cloud. Если это притянуто за уши — ставь 1-2 балла.

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

Если суммарный балл >= 6.0 — рекомендуй "approve".
Если суммарный балл < 4.0 — рекомендуй "reject".
Иначе — "clarify".
Отвечай строго в формате JSON.
""".strip()


class IntakeParseError(Exception):
    """Raised when model response cannot be parsed."""


class IntakeAgent:
    def __init__(self, yc_client: YandexCloudAgentClient, tracker_client: TrackerClient, db_session: AsyncSession):
        self.yc_client = yc_client
        self.tracker_client = tracker_client
        self.db_session = db_session
        self.yandex_responses_client = YandexResponsesClient()

    def _check_deep_intake_available(self) -> bool:
        required = [
            settings.yandex_api_key,
            settings.yandex_project_id,
            settings.eval_technical_analyst_id,
            settings.eval_market_researcher_id,
            settings.eval_innovator_id,
            settings.eval_risk_assessor_id,
            settings.eval_moderator_id,
        ]
        return all(value and str(value).strip() for value in required)

    async def process(self, application_id: UUID) -> IntakeResult:
        if self._check_deep_intake_available():
            return await self._run_deep_intake(application_id)
        return await self._run_simple_intake(application_id)

    async def _run_simple_intake(self, application_id: UUID) -> IntakeResult:
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

        try:
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
        except TrackerAPIError as exc:
            logger.warning("tracker_unavailable_intake_simple", extra={"error": str(exc)})
            self.db_session.add(
                AgentLog(
                    project_id=application.project_id,
                    correlation_id=uuid.uuid4(),
                    agent_name="intake",
                    stage="intake",
                    action="tracker_create_issue_failed",
                    input_payload={"application_id": str(application.id)},
                    output_payload={"error": str(exc)},
                    status=AgentLogStatus.ERROR,
                )
            )

        await self.db_session.commit()
        await self.db_session.refresh(application)
        return intake_result

    async def _run_deep_intake(self, application_id: UUID) -> IntakeResult:
        result = await self.db_session.execute(select(Application).where(Application.id == application_id))
        application = result.scalar_one_or_none()
        if application is None:
            raise ValueError(f"Application not found: {application_id}")

        proposal_text = await self._build_user_message(application)
        common_prompt = self._build_deep_common_prompt(proposal_text)

        tasks = [
            self._call_expert("technical_analyst", settings.eval_technical_analyst_id, common_prompt),
            self._call_expert("market_researcher", settings.eval_market_researcher_id, common_prompt),
            self._call_expert("innovator", settings.eval_innovator_id, common_prompt),
            self._call_expert("risk_assessor", settings.eval_risk_assessor_id, common_prompt),
        ]
        tech_out, market_out, innov_out, risk_out = await asyncio.gather(*tasks)

        expert_outputs = {
            "technical_analyst": tech_out,
            "market_researcher": market_out,
            "innovator": innov_out,
            "risk_assessor": risk_out,
        }
        await self._log_committee_steps(application, expert_outputs)

        moderator_prompt = self._build_moderator_prompt(proposal_text, expert_outputs)
        moderator_out, _ = await self._call_expert("moderator", settings.eval_moderator_id, moderator_prompt)

        verdict = self._extract_verdict(moderator_out)
        confidence = self._extract_confidence(moderator_out)
        recommended_action = "approve" if verdict == "APPROVE" else "reject"

        synthetic_score = int(round((confidence or 60.0) / 10))
        synthetic_score = max(1, min(10, synthetic_score))
        scorecard_items = [
            ScorecardItem(criterion="Committee confidence", score=synthetic_score, rationale="Deep Intake moderator confidence"),
            ScorecardItem(criterion="Technical feasibility", score=synthetic_score, rationale="Technical analyst conclusion"),
            ScorecardItem(criterion="Market relevance", score=synthetic_score, rationale="Market researcher conclusion"),
            ScorecardItem(criterion="Innovation", score=synthetic_score, rationale="Innovator conclusion"),
            ScorecardItem(criterion="Risk profile", score=synthetic_score, rationale="Risk assessor conclusion"),
        ]

        intake_result = IntakeResult(
            application_id=application.id,
            scorecard=scorecard_items,
            clarifying_questions=[],
            summary=moderator_out,
            recommended_action=recommended_action,
        )

        application.scorecard = {
            "items": [item.model_dump() for item in intake_result.scorecard],
            "overall_score": confidence,
            "source": "deep_intake_committee",
            "verdict": verdict,
        }
        application.summary = moderator_out
        application.status = ApplicationStatus.SCORING

        self.db_session.add(
            AgentLog(
                project_id=application.project_id,
                correlation_id=uuid.uuid4(),
                agent_name="intake/moderator",
                stage="intake",
                action="committee_verdict",
                input_payload={"application_id": str(application.id)},
                output_payload={"verdict": verdict, "confidence": confidence},
                status=AgentLogStatus.SUCCESS,
            )
        )

        try:
            issue = await self.tracker_client.create_issue(
                queue=settings.tracker_queue_key,
                summary=f"[Intake Committee] {application.title}",
                description=self._build_tracker_description(application, intake_result),
                tags=["intake", "committee", "mvp"],
            )
            self.db_session.add(
                Task(
                    project_id=application.project_id,
                    tracker_issue_id=issue.get("key") or issue.get("id"),
                    title=f"Intake review: {application.title}",
                    description=intake_result.summary[:1000],
                    status="created",
                )
            )
        except TrackerAPIError as exc:
            logger.warning("tracker_unavailable_intake_deep", extra={"error": str(exc)})
            self.db_session.add(
                AgentLog(
                    project_id=application.project_id,
                    correlation_id=uuid.uuid4(),
                    agent_name="intake",
                    stage="intake",
                    action="tracker_create_issue_failed",
                    input_payload={"application_id": str(application.id)},
                    output_payload={"error": str(exc)},
                    status=AgentLogStatus.ERROR,
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
        candidate = self._clean_json(raw)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            logger.exception("Failed to parse intake response. Raw: %s", raw)
            raise IntakeParseError("Invalid JSON from intake model") from exc

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

    def _build_deep_common_prompt(self, proposal_text: str) -> str:
        return (
            "Оцени проектную заявку строго по фактам, не выдумывай данные.\n"
            "Если данных не хватает, явно укажи риски и вопросы.\n\n"
            f"Заявка:\n{proposal_text}"
        )

    def _build_moderator_prompt(self, proposal_text: str, outputs: dict[str, tuple[str, dict]]) -> str:
        return (
            "Ты moderator комитета экспертов. Синтезируй оценки и вынеси итог: APPROVE или REJECT.\n"
            "Также укажи confidence (0-100).\n\n"
            f"Заявка:\n{proposal_text}\n\n"
            f"technical_analyst:\n{outputs['technical_analyst'][0]}\n\n"
            f"market_researcher:\n{outputs['market_researcher'][0]}\n\n"
            f"innovator:\n{outputs['innovator'][0]}\n\n"
            f"risk_assessor:\n{outputs['risk_assessor'][0]}"
        )

    async def _call_expert(self, expert_name: str, prompt_id: str, prompt: str) -> tuple[str, dict]:
        timeout = 300 if expert_name in {"innovator", "moderator"} else 180
        text, payload = await self.yandex_responses_client.async_call(
            prompt_id=prompt_id,
            input_text=prompt,
            timeout_sec=timeout,
            retries=3,
        )
        return text, payload

    async def _log_committee_steps(self, application: Application, outputs: dict[str, tuple[str, dict]]) -> None:
        for name, (text, payload) in outputs.items():
            self.db_session.add(
                AgentLog(
                    project_id=application.project_id,
                    correlation_id=uuid.uuid4(),
                    agent_name=f"intake/{name}",
                    stage="intake",
                    action="committee_step",
                    input_payload={"application_id": str(application.id)},
                    output_payload={
                        "output_text": text[:1000],
                        "response_id": payload.get("id"),
                        "status": payload.get("status"),
                    },
                    status=AgentLogStatus.SUCCESS,
                )
            )

    def _extract_verdict(self, text: str) -> str:
        upper = (text or "").upper()
        if "APPROVE" in upper or "УТВЕРД" in upper:
            return "APPROVE"
        if "REJECT" in upper or "ОТКЛОН" in upper or "ОТКАЗ" in upper:
            return "REJECT"
        return "REJECT"

    def _extract_confidence(self, text: str) -> float | None:
        import re

        match = re.search(r"(?i)(confidence|уверенность)\s*[:=]?\s*(\d{1,3})", text or "")
        if not match:
            return None
        return max(0.0, min(100.0, float(match.group(2))))
