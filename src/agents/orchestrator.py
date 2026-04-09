"""Redis-based orchestrator for intake and research queues."""

import asyncio
import logging
import uuid
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.intake import IntakeAgent
from agents.monitor import MonitorAgent
from agents.research import ResearchAgent
from core.config import settings
from db.base import AsyncSessionLocal
from db.models import AgentLog, AgentLogStatus, Application, Project, Task
from integrations.sourcecraft import SourcecraftClient
from integrations.tracker import TrackerClient
from integrations.yandex_cloud import YandexCloudAgentClient

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Reads events from Redis queues and routes them to agents.
    Runs as a background async task.
    """

    QUEUE_INTAKE = "orchestrator:intake"
    QUEUE_RESEARCH = "orchestrator:research"
    MONITOR_INTERVAL_SECONDS = 1800

    def __init__(self) -> None:
        self.redis = Redis.from_url(settings.redis_url, decode_responses=True)
        self._last_monitor_run: float = 0.0

    async def run(self):
        while True:
            try:
                await self._process_intake_queue()
                await self._process_research_queue()
                await self._run_monitor_if_needed()
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"orchestrator_loop_error: {exc}")
                await asyncio.sleep(5)

    async def close(self):
        await self.redis.close()

    async def _process_intake_queue(self):
        item = await self.redis.blpop(self.QUEUE_INTAKE, timeout=5)
        if not item:
            return
        _, project_id_str = item
        async with AsyncSessionLocal() as db:
            try:
                project_id = UUID(project_id_str)
                project = await self._get_project(db, project_id)
                if project is None:
                    return
                await self._update_project_status(db, project_id, "under_review")
                agent = IntakeAgent(
                    yc_client=YandexCloudAgentClient(),
                    tracker_client=TrackerClient(),
                    db_session=db,
                )
                await agent.process(project_id)
                await self.redis.rpush(self.QUEUE_RESEARCH, str(project_id))
            except Exception as exc:
                await self._log_error(db, project_id, "intake", "queue_process", str(exc))
                await db.commit()

    async def _process_research_queue(self):
        item = await self.redis.blpop(self.QUEUE_RESEARCH, timeout=5)
        if not item:
            return
        _, project_id_str = item
        async with AsyncSessionLocal() as db:
            try:
                project_id = UUID(project_id_str)
                project = await self._get_project(db, project_id)
                if project is None:
                    return
                agent = ResearchAgent(
                    yc_client=YandexCloudAgentClient(),
                    tracker_client=TrackerClient(),
                    db_session=db,
                )
                report = await agent.process(project_id)
                await self._update_project_status(db, project_id, "deep_research_completed")
                tracker = TrackerClient()
                issue = await tracker.create_issue(
                    queue=settings.tracker_queue_key,
                    summary=f"[Approval Required] {project.title}",
                    description=(
                        "Research завершён, требуется решение РП.\n\n"
                        f"Confidence score: {report.get('confidence_score', 'n/a')}"
                    ),
                    tags=["research", "approval"],
                )
                db.add(
                    Task(
                        project_id=project.id,
                        tracker_issue_id=issue.get("key") or issue.get("id"),
                        title=f"Требует решения РП: {project.title}",
                        description="Research completed, awaiting PM approval",
                        status="created",
                    )
                )
                await db.commit()
            except Exception as exc:
                await self._log_error(db, project_id, "research", "queue_process", str(exc))
                await db.commit()

    async def _run_monitor_if_needed(self):
        now = asyncio.get_running_loop().time()
        if now - self._last_monitor_run < self.MONITOR_INTERVAL_SECONDS:
            return
        self._last_monitor_run = now
        async with AsyncSessionLocal() as db:
            monitor = MonitorAgent(
                tracker_client=TrackerClient(),
                sourcecraft_client=SourcecraftClient(),
                db_session=db,
            )
            projects = await monitor.list_active_projects()
            for project in projects:
                try:
                    await monitor.run_project_check(project.id)
                except Exception as exc:
                    logger.error("monitor_project_check_failed", extra={"project_id": str(project.id), "error": str(exc)})

    async def _update_project_status(self, db: AsyncSession, project_id: UUID, status: str):
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if project is not None:
            project.status = status
            await db.commit()

    async def _get_project(self, db: AsyncSession, project_id: UUID) -> Project | None:
        result = await db.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()

    async def _log_error(self, db: AsyncSession, project_id: UUID, stage: str, action: str, message: str):
        db.add(
            AgentLog(
                project_id=project_id,
                correlation_id=uuid.uuid4(),
                agent_name="orchestrator",
                stage=stage,
                action=action,
                input_payload={"project_id": str(project_id)},
                output_payload={"error": message},
                status=AgentLogStatus.ERROR,
            )
        )
