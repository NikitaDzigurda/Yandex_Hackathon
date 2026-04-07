"""Basic monitor agent for stale tasks and repo activity."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AgentLog, AgentLogStatus, Project, Task
from integrations.sourcecraft import SourcecraftClient
from integrations.tracker import TrackerClient

logger = logging.getLogger(__name__)


class MonitorAgent:
    """
    Runs periodic checks and reports stale project activity.
    """

    STALE_TASK_DAYS = 3

    def __init__(self, tracker_client: TrackerClient, sourcecraft_client: SourcecraftClient, db_session: AsyncSession):
        self.tracker_client = tracker_client
        self.sourcecraft_client = sourcecraft_client
        self.db_session = db_session

    async def check_stale_tasks(self, project_id: UUID) -> list[dict]:
        result = await self.db_session.execute(
            select(Task).where(Task.project_id == project_id, Task.tracker_issue_id.is_not(None))
        )
        tasks = result.scalars().all()
        stale: list[dict] = []
        threshold = datetime.now(timezone.utc) - timedelta(days=self.STALE_TASK_DAYS)

        for task in tasks:
            if not task.tracker_issue_id:
                continue
            issue = await self.tracker_client.get_issue(task.tracker_issue_id)
            status_key = (issue.get("status") or {}).get("key", "")
            if status_key not in {"inProgress", "in_progress", "in-progress"}:
                continue
            updated = issue.get("updatedAt") or issue.get("updated_at")
            if not updated:
                continue
            updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            if updated_dt < threshold:
                stale.append(
                    {
                        "issue_key": task.tracker_issue_id,
                        "title": task.title,
                        "updated_at": updated,
                        "days_without_update": (datetime.now(timezone.utc) - updated_dt).days,
                    }
                )

        self.db_session.add(
            AgentLog(
                project_id=project_id,
                correlation_id=uuid.uuid4(),
                agent_name="monitor",
                stage="monitor",
                action="check_stale_tasks",
                input_payload={"project_id": str(project_id)},
                output_payload={"stale_tasks_count": len(stale)},
                status=AgentLogStatus.SUCCESS,
            )
        )
        await self.db_session.commit()
        return stale

    async def check_repo_activity(self, repo_id: str) -> dict:
        activity = await self.sourcecraft_client.get_repo_activity(repo_id=repo_id, days=7)
        prs = await self.sourcecraft_client.get_pr_status(repo_id=repo_id)
        alert = activity.get("commits", 0) == 0
        return {
            "repo_id": repo_id,
            "commits_7d": activity.get("commits", 0),
            "open_prs": len([pr for pr in prs if pr.get("state") == "open"]),
            "alert": alert,
        }

    async def run_project_check(self, project_id: UUID, repo_id: str | None = None) -> dict:
        stale_tasks = await self.check_stale_tasks(project_id)
        repo_summary = None
        if repo_id:
            repo_summary = await self.check_repo_activity(repo_id)

        alerts_sent = bool(stale_tasks or (repo_summary and repo_summary.get("alert")))
        if alerts_sent:
            result = await self.db_session.execute(
                select(Task)
                .where(Task.project_id == project_id, Task.tracker_issue_id.is_not(None))
                .order_by(Task.created_at.desc())
                .limit(1)
            )
            tracker_task = result.scalar_one_or_none()
            if tracker_task and tracker_task.tracker_issue_id:
                text = (
                    f"Monitor alert: stale_tasks={len(stale_tasks)}, "
                    f"repo_alert={bool(repo_summary and repo_summary.get('alert'))}"
                )
                await self.tracker_client.add_comment(tracker_task.tracker_issue_id, text)

        return {
            "project_id": str(project_id),
            "stale_tasks": stale_tasks,
            "repo_summary": repo_summary,
            "alerts_sent": alerts_sent,
        }

    async def list_active_projects(self) -> list[Project]:
        result = await self.db_session.execute(
            select(Project).where(Project.status.notin_(["rejected", "closed_rejected"]))
        )
        return result.scalars().all()
