"""Runs API endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_current_user, require_reviewer
from db.base import get_db
from db.models import AgentRun, Project, ProjectStatus, RunStatus, RunType, User, Application, UserRole
from schemas.runs import (
    AgentRunDetailOut,
    AgentRunOut,
    DeepResearchRunRequest,
    EvaluationRunRequest,
    ExportRequest,
    ExportTasksOut,
    LatestDeepResearchOut,
)
from db.base import AsyncSessionLocal
from agents.intake import IntakeAgent
from agents.research import ResearchAgent
from integrations.yandex_cloud import YandexCloudAgentClient
from integrations.tracker import TrackerClient
from datetime import datetime
import hashlib

router = APIRouter()


def get_project_hash(project: Project, prompt: str | None = None) -> str:
    """Calculate a hash of the project's content to detect changes."""
    content = f"{project.title}|{project.domain}|{project.description}|{project.attachments_url}|{prompt or ''}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def run_evaluation_background(run_id: UUID, project_id: UUID):
    async with AsyncSessionLocal() as db:
        try:
            # 1. Update run status
            result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
            run = result.scalar_one_or_none()
            if not run:
                return
            
            run.status = RunStatus.running
            run.started_at = datetime.now()
            await db.commit()

            # 2. Get project
            proj_result = await db.execute(select(Project).where(Project.id == project_id))
            project = proj_result.scalar_one_or_none()
            if not project:
                run.status = RunStatus.failed
                run.error_text = "Project not found"
                await db.commit()
                return

            # 3. Run Agent
            agent = IntakeAgent(YandexCloudAgentClient(), TrackerClient(), db)
            intake_result = await agent.process(project.id, run_id=run_id)

            # 4. Finalize run
            run.status = RunStatus.completed
            run.finished_at = datetime.now()
            run.result_json = intake_result.model_dump(mode="json")
            await db.commit()

        except Exception as exc:
            run.status = RunStatus.failed
            run.error_text = str(exc)
            await db.commit()


async def run_deep_research_background(
    run_id: UUID, project_id: UUID, evaluation_prompt: str | None
):
    async with AsyncSessionLocal() as db:
        try:
            # 1. Update run status
            result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
            run = result.scalar_one_or_none()
            if not run:
                return
            
            run.status = RunStatus.running
            run.started_at = datetime.now()
            await db.commit()

            # 2. Get project
            proj_result = await db.execute(select(Project).where(Project.id == project_id))
            project = proj_result.scalar_one_or_none()
            if not project:
                run.status = RunStatus.failed
                run.error_text = "Project not found"
                await db.commit()
                return

            # 3. Run Agent
            agent = ResearchAgent(YandexCloudAgentClient(), TrackerClient(), db)
            research_result = await agent.process(project.id, run_id=run_id)

            # 4. Finalize run
            run.status = RunStatus.completed
            run.finished_at = datetime.now()
            run.result_json = research_result
            
            # Also update project status if successful
            proj_result = await db.execute(select(Project).where(Project.id == project_id))
            project = proj_result.scalar_one_or_none()
            if project:
                project.status = ProjectStatus.deep_research_completed.value
            await db.commit()

        except Exception as exc:
            run.status = RunStatus.failed
            run.error_text = str(exc)
            await db.commit()


@router.post("/{project_id}/runs/evaluation", response_model=AgentRunOut)
async def trigger_evaluation(
    project_id: UUID,
    req: EvaluationRunRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    valid_statuses = [
        ProjectStatus.submitted.value,
        ProjectStatus.under_review.value,
        ProjectStatus.revision_requested.value,
        ProjectStatus.accepted_for_research.value,
    ]
    if project.status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Wrong status for evaluation")

    if project.status == ProjectStatus.submitted.value:
        project.status = ProjectStatus.under_review.value

    # --- Idempotency Check ---
    content_hash = get_project_hash(project, req.evaluation_prompt)
    existing_run = await db.execute(
        select(AgentRun)
        .where(
            AgentRun.project_id == project.id,
            AgentRun.run_type == RunType.evaluation,
            AgentRun.status == RunStatus.completed,
            AgentRun.content_hash == content_hash,
        )
        .order_by(AgentRun.created_at.desc())
    )
    last_run = existing_run.scalar_one_or_none()
    if last_run:
        return last_run
    # -------------------------

    run = AgentRun(
        project_id=project.id,
        run_type=RunType.evaluation,
        status=RunStatus.queued,
        total_agents=5,
        evaluation_prompt=req.evaluation_prompt,
        content_hash=content_hash,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    background_tasks.add_task(run_evaluation_background, run.id, project.id)

    return run


@router.post("/{project_id}/runs/deep-research", response_model=AgentRunOut)
async def trigger_deep_research(
    project_id: UUID,
    req: DeepResearchRunRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Allow admins to bypass the check
    is_admin = current_user.role == UserRole.admin
    if not is_admin and project.status != ProjectStatus.accepted_for_research.value:
        raise HTTPException(status_code=400, detail="Project must be accepted for research first")

    # --- Idempotency Check ---
    content_hash = get_project_hash(project, None)
    existing_run = await db.execute(
        select(AgentRun)
        .where(
            AgentRun.project_id == project.id,
            AgentRun.run_type == RunType.deep_research,
            AgentRun.status == RunStatus.completed,
            AgentRun.content_hash == content_hash,
        )
        .order_by(AgentRun.created_at.desc())
    )
    last_run = existing_run.scalar_one_or_none()
    if last_run:
        return last_run
    # -------------------------

    if project.status != ProjectStatus.deep_research_running.value:
        project.status = ProjectStatus.deep_research_running.value

    run = AgentRun(
        project_id=project.id,
        run_type=RunType.deep_research,
        status=RunStatus.queued,
        total_agents=9,
        content_hash=content_hash,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    background_tasks.add_task(run_deep_research_background, run.id, project.id, None)

    return run


@router.get("/{project_id}/runs", response_model=List[AgentRunOut])
async def list_runs(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Access control: readers only
    if current_user.role == "submitter" and project.submitter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    run_result = await db.execute(
        select(AgentRun).where(AgentRun.project_id == project_id).order_by(AgentRun.created_at.desc())
    )
    return run_result.scalars().all()


@router.get("/{project_id}/runs/{run_id}", response_model=AgentRunDetailOut)
async def get_run(
    project_id: UUID,
    run_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.role == "submitter" and project.submitter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    run_result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    run = run_result.scalar_one_or_none()
    
    if not run or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="Run not found")

    return {
        "ok": True,
        "result": run,
        "payload": run.result_json,
        "progress": run.progress_json,
    }


@router.get("/{project_id}/deep-research/latest", response_model=LatestDeepResearchOut)
async def get_latest_deep_research(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.role == "submitter" and project.submitter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    valid_statuses = [
        ProjectStatus.accepted_for_research.value,
        ProjectStatus.deep_research_running.value,
        ProjectStatus.deep_research_completed.value,
        ProjectStatus.on_showcase.value,
        ProjectStatus.archived.value,
    ]
    if project.status not in valid_statuses:
        raise HTTPException(
            status_code=403,
            detail="Deep research is available only after the project is accepted for research",
        )

    run_result = await db.execute(
        select(AgentRun)
        .where(
            AgentRun.project_id == project_id,
            AgentRun.run_type == RunType.deep_research,
            AgentRun.status == RunStatus.completed,
        )
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )
    run = run_result.scalar_one_or_none()
    
    if not run:
        raise HTTPException(status_code=404, detail="No completed deep research for this project")
        
    if not run.result_json:
        raise HTTPException(status_code=404, detail="Deep research run has no stored result yet")

    return {
        "ok": True,
        "project_id": project_id,
        "run_id": run.id,
        "finished_at": run.finished_at,
        "payload": run.result_json,
    }


@router.post("/{project_id}/runs/{run_id}/export/tracker", response_model=ExportTasksOut)
async def export_to_tracker(
    project_id: UUID,
    run_id: UUID,
    req: ExportRequest,
    current_user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    # Basic validation logic for now
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    run_result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    run = run_result.scalar_one_or_none()
    if not run or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.run_type != RunType.deep_research or run.status != RunStatus.completed:
        raise HTTPException(status_code=400, detail="Only a completed deep_research run can be exported")
        
    if not run.result_json:
        raise HTTPException(status_code=400, detail="Run has no result payload")
        
    # Return dummy successful response
    return {"ok": True, "tasks_planned": 0, "created": [], "errors": []}


@router.post("/{project_id}/runs/{run_id}/export/source-craft", response_model=ExportTasksOut)
async def export_to_source_craft(
    project_id: UUID,
    run_id: UUID,
    current_user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    run_result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    run = run_result.scalar_one_or_none()
    if not run or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.run_type != RunType.deep_research or run.status != RunStatus.completed:
        raise HTTPException(status_code=400, detail="Only a completed deep_research run can be exported")
        
    if not run.result_json:
        raise HTTPException(status_code=400, detail="Run has no result payload")
        
    # Return dummy successful response
    return {"ok": True, "tasks_planned": 0, "created": [], "errors": []}
