"""Research Agent implementation."""

from __future__ import annotations

import json
import logging
import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.intake import IntakeParseError
from core.config import settings
from db.models import AgentLog, AgentLogStatus, Application, ApplicationStatus, Document, Task
from integrations.tracker import TrackerAPIError, TrackerClient
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
        self.db = db_session
        self._use_deep_research = self._check_deep_research_available()

    def _check_deep_research_available(self) -> bool:
        required = [
            settings.yandex_api_key,
            settings.yandex_project_id,
            settings.agent_project_analyst_id,
            settings.agent_research_strategist_id,
            settings.agent_technical_researcher_id,
            settings.agent_architect_id,
            settings.agent_roadmap_manager_id,
            settings.agent_hr_specialist_id,
            settings.agent_risk_analyst_id,
            settings.agent_quality_reviewer_id,
            settings.agent_synthesis_manager_id,
        ]
        return all(value and value.strip() for value in required)

    async def process(self, application_id: UUID) -> dict:
        result = await self.db.execute(select(Application).where(Application.id == application_id))
        application = result.scalar_one_or_none()
        if application is None:
            raise ValueError(f"Application not found: {application_id}")
        if application.status not in {ApplicationStatus.SCORING, ApplicationStatus.APPROVED}:
            raise ValueError("Application must be in scoring or approved status for research")

        tracker_context = await self._build_tracker_context(application.project_id)
        if self._use_deep_research:
            return await self._run_deep_research(application, tracker_context)
        return await self._run_simple_research(application)

    async def _run_simple_research(self, application: Application) -> dict:
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
        await self._save_report(application, report_dict)

        self.db.add(
            AgentLog(
                project_id=application.project_id,
                correlation_id=uuid.uuid4(),
                agent_name="research",
                stage="research",
                action="process_application",
                input_payload={"application_id": str(application.id)},
                output_payload=report_dict,
                status=AgentLogStatus.SUCCESS,
            )
        )

        task_result = await self.db.execute(
            select(Task)
            .where(Task.project_id == application.project_id, Task.tracker_issue_id.is_not(None))
            .order_by(Task.created_at.desc())
            .limit(1)
        )
        tracker_task = task_result.scalar_one_or_none()
        if tracker_task and tracker_task.tracker_issue_id:
            try:
                await self._save_to_tracker(tracker_task.tracker_issue_id, report_dict)
            except TrackerAPIError as exc:
                logger.warning("tracker_unavailable_research_simple", extra={"error": str(exc)})

        await self.db.commit()
        return report_dict

    async def _run_deep_research(self, application: Application, tracker_context: str) -> dict:
        from agents.deep_research import run_deep_research_async

        result = await run_deep_research_async(
            project_description=self._build_project_description(application),
            tracker_context=tracker_context,
            source_craft_context="",
            artifact_dir=None,
            print_agent_outputs=settings.print_full_agent_outputs,
            continue_on_agent_error=True,
        )

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
            "agents_completed": len([item for item in result.get("agent_runs", []) if item.get("success")]),
            "agents_total": len(result.get("agent_runs", [])),
        }

        await self._save_report(application, report_data)
        await self._log_agent_runs(application, result.get("agent_runs", []))
        try:
            await self._post_to_tracker(application, report_data)
        except TrackerAPIError as exc:
            logger.warning("tracker_unavailable_research_deep", extra={"error": str(exc)})
        await self.db.commit()
        return report_data

    async def _build_user_message(self, application: Application) -> str:
        return (
            f"Домен проекта: {application.domain}\n"
            f"Название: {application.title}\n"
            f"Описание:\n{application.text}\n\n"
            f"Summary от Intake:\n{application.summary or 'Не заполнено'}\n\n"
            "Сформируй структурированный research report строго в JSON."
        )

    def _build_project_description(self, application: Application) -> str:
        return (
            f"{application.title}\n\n"
            f"Домен: {application.domain}\n"
            f"Инициатор: {application.initiator_name}\n\n"
            f"Описание:\n{application.text}\n\n"
            f"Summary от intake:\n{application.summary or 'Не заполнено'}"
        )

    async def _build_tracker_context(self, project_id: UUID) -> str:
        task_result = await self.db.execute(
            select(Task).where(Task.project_id == project_id, Task.tracker_issue_id.is_not(None))
        )
        issue_keys = [item.tracker_issue_id for item in task_result.scalars().all() if item.tracker_issue_id]
        if not issue_keys:
            return ""
        issues = await self.tracker_client.list_issues(settings.tracker_queue_key)
        selected = [item for item in issues if item.get("key") in issue_keys]
        return json.dumps(selected, ensure_ascii=False, indent=2)

    async def _save_report(self, application: Application, report_data: dict) -> None:
        self.db.add(
            Document(
                project_id=application.project_id,
                agent_name="research",
                doc_type="research_report",
                title=f"Research report for {application.title}",
                content=json.dumps(report_data, ensure_ascii=False),
                version=1,
            )
        )

    async def _log_agent_runs(self, application: Application, agent_runs: list[dict]) -> None:
        for run in agent_runs:
            status = AgentLogStatus.SUCCESS if run.get("success") else AgentLogStatus.ERROR
            self.db.add(
                AgentLog(
                    project_id=application.project_id,
                    correlation_id=uuid.uuid4(),
                    agent_name=f"deep_research/{run.get('agent_name', 'unknown')}",
                    stage="deep_research",
                    action="deep_research_step",
                    input_payload={"input_text": (run.get("input_text") or "")[:500]},
                    output_payload={
                        "output_text": (run.get("output_text") or "")[:1000],
                        "duration_sec": run.get("duration_sec"),
                        "success": run.get("success"),
                    },
                    status=status,
                )
            )

    async def _post_to_tracker(self, application: Application, report_data: dict) -> None:
        task_result = await self.db.execute(
            select(Task)
            .where(Task.project_id == application.project_id, Task.tracker_issue_id.is_not(None))
            .order_by(Task.created_at.desc())
            .limit(1)
        )
        tracker_task = task_result.scalar_one_or_none()
        if not tracker_task or not tracker_task.tracker_issue_id:
            return
        summary = (report_data.get("executive_summary") or "")[:500]
        text = (
            "Deep Research завершён, ожидает review РП.\n\n"
            f"Decision: {report_data.get('decision', 'n/a')}\n"
            f"Feasibility: {report_data.get('feasibility_score', 'n/a')}\n"
            f"Quality: {report_data.get('quality_score', 'n/a')}\n"
            f"Completeness: {report_data.get('completeness_score', 'n/a')}\n"
            f"Agents completed: {report_data.get('agents_completed', 0)}/{report_data.get('agents_total', 9)}\n\n"
            f"Executive Summary:\n{summary}"
        )
        await self.tracker_client.add_comment(tracker_task.tracker_issue_id, text)

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
