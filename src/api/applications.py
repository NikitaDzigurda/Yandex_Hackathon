"""Applications API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.intake import IntakeAgent
from core.config import settings
from db.base import get_db
from db.models import Application, ApplicationStatus, Project
from integrations.tracker import TrackerClient
from integrations.yandex_cloud import YandexCloudAgentClient
from schemas.application import ApplicationCreate, ApplicationResponse, IntakeResult

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
async def create_application(payload: ApplicationCreate, db: AsyncSession = Depends(get_db)) -> ApplicationResponse:
    project = Project(
        title=payload.title,
        description=payload.text,
        status="submitted",
        created_by=payload.initiator_email,
    )
    db.add(project)
    await db.flush()

    application = Application(
        project_id=project.id,
        initiator_name=payload.initiator_name,
        initiator_email=payload.initiator_email,
        title=payload.title,
        domain=payload.domain,
        text=payload.text,
        attachments_url=payload.attachments_url,
        status=ApplicationStatus.SUBMITTED,
    )
    db.add(application)
    await db.commit()
    await db.refresh(application)

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    await redis.rpush("orchestrator:intake", str(application.id))
    await redis.close()
    return ApplicationResponse.model_validate(application)


@router.get("/{application_id}", response_model=ApplicationResponse)
async def get_application(application_id: UUID, db: AsyncSession = Depends(get_db)) -> ApplicationResponse:
    result = await db.execute(select(Application).where(Application.id == application_id))
    application = result.scalar_one_or_none()
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return ApplicationResponse.model_validate(application)


@router.post("/{application_id}/trigger-intake", response_model=IntakeResult)
async def trigger_intake(application_id: UUID, db: AsyncSession = Depends(get_db)) -> IntakeResult:
    agent = IntakeAgent(
        yc_client=YandexCloudAgentClient(),
        tracker_client=TrackerClient(),
        db_session=db,
    )
    try:
        return await agent.process(application_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
