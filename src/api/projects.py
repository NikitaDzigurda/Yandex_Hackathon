"""Projects API endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_current_user, require_reviewer, require_submitter
from db.base import get_db
from db.models import Project, ProjectStatus, User, UserRole
from api.telegram_admin import notify_new_project_submitted
from schemas.project import (
    ProjectCreate,
    ProjectOut,
    ProjectOutEnvelope,
    ProjectUpdate,
    ReviewEnvelope,
    ReviewRequest,
)

router = APIRouter()


@router.post("", response_model=ProjectOutEnvelope)
async def create_project(
    req: ProjectCreate,
    current_user: User = Depends(require_submitter),
    db: AsyncSession = Depends(get_db),
):
    project = Project(
        title=req.title,
        domain=req.domain,
        description=req.description,
        attachments_url=req.attachments_url,
        task=req.task,
        stage=req.stage,
        deadlines=req.deadlines,
        status=ProjectStatus.draft.value,
        human_decision="pending",
        submitter_id=current_user.id,
        created_by=current_user.email,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return {"ok": True, "result": project}


@router.get("/mine", response_model=List[ProjectOut])
async def get_my_projects(
    current_user: User = Depends(require_submitter),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project)
        .where(Project.submitter_id == current_user.id)
        .order_by(Project.created_at.desc())
    )
    return result.scalars().all()


@router.get("/review-queue", response_model=List[ProjectOut])
async def get_review_queue(
    current_user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project)
        .where(
            Project.status.in_(
                [
                    ProjectStatus.submitted.value,
                    ProjectStatus.under_review.value,
                    ProjectStatus.revision_requested.value,
                ]
            )
        )
        .order_by(Project.created_at.asc())
    )
    return result.scalars().all()


@router.get("/{project_id}", response_model=ProjectOutEnvelope)
async def get_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.role == UserRole.submitter and project.submitter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    return {"ok": True, "result": project}


@router.patch("/{project_id}", response_model=ProjectOutEnvelope)
async def update_project(
    project_id: UUID,
    req: ProjectUpdate,
    current_user: User = Depends(require_submitter),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.submitter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your project")

    if project.status not in (ProjectStatus.draft.value, ProjectStatus.revision_requested.value):
        raise HTTPException(status_code=400, detail="Cannot edit in current status")

    update_data = req.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(project, key, value)
    
    if project.status == ProjectStatus.revision_requested.value:
        project.status = ProjectStatus.draft.value

    await db.commit()
    await db.refresh(project)
    return {"ok": True, "result": project}


@router.post("/{project_id}/submit", response_model=ProjectOutEnvelope)
async def submit_project(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_submitter),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.submitter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your project")

    if project.status not in (ProjectStatus.draft.value, ProjectStatus.revision_requested.value):
        raise HTTPException(status_code=400, detail="Cannot submit from this status")

    project.status = ProjectStatus.submitted.value
    project.human_decision = "pending"
    await db.commit()
    await db.refresh(project)

    background_tasks.add_task(notify_new_project_submitted, project.id, db)

    return {"ok": True, "result": project}


@router.post("/{project_id}/review", response_model=ReviewEnvelope)
async def review_project(
    project_id: UUID,
    req: ReviewRequest,
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
        ProjectStatus.deep_research_running.value,
        ProjectStatus.deep_research_completed.value,
    ]
    if project.status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Project not in reviewable state")

    if req.decision == "approve":
        project.status = ProjectStatus.accepted_for_research.value
    elif req.decision == "reject":
        project.status = ProjectStatus.rejected.value
    elif req.decision == "request_revision":
        project.status = ProjectStatus.revision_requested.value
    else:
        project.status = ProjectStatus.under_review.value
        
    project.human_decision = req.decision
    project.reviewer_id = current_user.id
    project.reviewer_comment = req.comment
    
    await db.commit()
    await db.refresh(project)

    return {"ok": True, "result": project}


@router.post("/{project_id}/publish-showcase", response_model=ProjectOutEnvelope)
async def publish_showcase(
    project_id: UUID,
    current_user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.status != ProjectStatus.deep_research_completed.value:
        raise HTTPException(status_code=400, detail="Complete deep research before publishing")

    project.status = ProjectStatus.on_showcase.value
    await db.commit()
    await db.refresh(project)

    return {"ok": True, "result": project}
