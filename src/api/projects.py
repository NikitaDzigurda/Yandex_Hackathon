"""Projects API endpoints."""

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.config import settings
from db.base import get_db
from db.models import AgentLog, Application, Document, Project, Task
from integrations.tracker import TrackerClient
from schemas.project import ProjectDetailResponse, ProjectResponse, ProjectStatusResponse

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectResponse]:
    result = await db.execute(select(Project).limit(limit).offset(offset).order_by(Project.created_at.desc()))
    projects = result.scalars().all()
    return [ProjectResponse.model_validate(project) for project in projects]


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(project_id: UUID, db: AsyncSession = Depends(get_db)) -> ProjectDetailResponse:
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(selectinload(Project.applications))
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return ProjectDetailResponse.model_validate(project)


@router.get("/{project_id}/status", response_model=ProjectStatusResponse)
async def get_project_status(project_id: UUID, db: AsyncSession = Depends(get_db)) -> ProjectStatusResponse:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    app_result = await db.execute(
        select(Application).where(Application.project_id == project_id).order_by(Application.created_at.desc()).limit(1)
    )
    application = app_result.scalar_one_or_none()

    doc_result = await db.execute(
        select(Document)
        .where(Document.project_id == project_id, Document.doc_type == "research_report")
        .order_by(Document.created_at.desc())
        .limit(1)
    )
    report_doc = doc_result.scalar_one_or_none()
    research_report = json.loads(report_doc.content) if report_doc and report_doc.content else None

    logs_result = await db.execute(
        select(AgentLog).where(AgentLog.project_id == project_id).order_by(AgentLog.created_at.desc()).limit(5)
    )
    recent_logs = logs_result.scalars().all()

    tracker_tasks: list[dict] = []
    task_result = await db.execute(select(Task).where(Task.project_id == project_id, Task.tracker_issue_id.is_not(None)))
    task_keys = [item.tracker_issue_id for item in task_result.scalars().all() if item.tracker_issue_id]
    if task_keys:
        tracker = TrackerClient()
        try:
            queue_issues = await asyncio.wait_for(
                tracker.list_issues(settings.tracker_queue_key),
                timeout=10.0,
            )
            tracker_tasks = [issue for issue in queue_issues if issue.get("key") in task_keys]
        except Exception:
            tracker_tasks = []

    return ProjectStatusResponse(
        project_id=project.id,
        title=project.title,
        status=project.status,
        application={
            "id": str(application.id),
            "status": application.status.value,
            "scorecard": application.scorecard,
            "summary": application.summary,
        }
        if application
        else None,
        research_report=research_report,
        tracker_tasks=tracker_tasks,
        recent_agent_logs=[
            {
                "agent_name": log.agent_name,
                "stage": log.stage,
                "action": log.action,
                "status": log.status.value,
                "created_at": log.created_at.isoformat(),
            }
            for log in recent_logs
        ],
        created_at=project.created_at,
    )
