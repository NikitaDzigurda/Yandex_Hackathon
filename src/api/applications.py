"""Applications API endpoints."""

from uuid import UUID
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.intake import IntakeAgent, IntakeParseError
from agents.research import ResearchAgent
from core.config import settings
from db.base import get_db
from db.models import AgentLog, AgentLogStatus, Application, ApplicationStatus, Document, Project, Task
from integrations.tracker import TrackerAPIError, TrackerClient
from integrations.yandex_cloud import YCAgentError, YandexCloudAgentClient
from schemas.application import ApplicationCreate, ApplicationResponse, IntakeResult, ResearchReport

router = APIRouter(prefix="/applications", tags=["applications"])


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str


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


@router.get("/pending", response_model=list[ApplicationResponse])
async def pending_applications(db: AsyncSession = Depends(get_db)) -> list[ApplicationResponse]:
    result = await db.execute(select(Application).where(Application.status == ApplicationStatus.SCORING))
    items = result.scalars().all()
    return [ApplicationResponse.model_validate(item) for item in items]


@router.get("/{application_id}", response_model=ApplicationResponse)
async def get_application(application_id: UUID, db: AsyncSession = Depends(get_db)) -> ApplicationResponse:
    result = await db.execute(select(Application).where(Application.id == application_id))
    application = result.scalar_one_or_none()
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return ApplicationResponse.model_validate(application)


@router.post("/{application_id}/trigger-intake", response_model=IntakeResult)
async def trigger_intake(application_id: UUID, db: AsyncSession = Depends(get_db)) -> IntakeResult:
    result = await db.execute(select(Application).where(Application.id == application_id))
    application = result.scalar_one_or_none()
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    if application.status in {
        ApplicationStatus.SCORING,
        ApplicationStatus.APPROVED,
        ApplicationStatus.REJECTED,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Intake already processed for this application",
        )

    agent = IntakeAgent(
        yc_client=YandexCloudAgentClient(),
        tracker_client=TrackerClient(),
        db_session=db,
    )
    try:
        return await agent.process(application_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except IntakeParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to parse intake model response: {exc}",
        ) from exc
    except YCAgentError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Yandex Cloud agent invocation failed: {exc}",
        ) from exc
    except TrackerAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Tracker API request failed: {exc}",
        ) from exc


@router.post("/{application_id}/trigger-research", response_model=ResearchReport)
async def trigger_research(application_id: UUID, db: AsyncSession = Depends(get_db)) -> ResearchReport:
    result = await db.execute(select(Application).where(Application.id == application_id))
    application = result.scalar_one_or_none()
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    agent = ResearchAgent(
        yc_client=YandexCloudAgentClient(),
        tracker_client=TrackerClient(),
        db_session=db,
    )
    try:
        report = await agent.process(application_id)
        return ResearchReport.model_validate(report)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (IntakeParseError, YCAgentError, TrackerAPIError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/{application_id}/report", response_model=ResearchReport)
async def get_research_report(application_id: UUID, db: AsyncSession = Depends(get_db)) -> ResearchReport:
    result = await db.execute(select(Application).where(Application.id == application_id))
    application = result.scalar_one_or_none()
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    doc_result = await db.execute(
        select(Document)
        .where(
            Document.project_id == application.project_id,
            Document.doc_type == "research_report",
        )
        .order_by(Document.created_at.desc())
        .limit(1)
    )
    document = doc_result.scalar_one_or_none()
    if document is None or not document.content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Research report not available yet",
        )
    return ResearchReport.model_validate_json(document.content)


@router.post("/{application_id}/decision", response_model=ApplicationResponse)
async def application_decision(
    application_id: UUID,
    payload: ApprovalDecision,
    db: AsyncSession = Depends(get_db),
) -> ApplicationResponse:
    result = await db.execute(select(Application).where(Application.id == application_id))
    application = result.scalar_one_or_none()
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    if application.status != ApplicationStatus.SCORING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Application is not awaiting PM decision")
    if not payload.comment.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Comment is required")

    application.status = ApplicationStatus.APPROVED if payload.decision == "approve" else ApplicationStatus.REJECTED
    project_result = await db.execute(select(Project).where(Project.id == application.project_id))
    project = project_result.scalar_one_or_none()
    if project is not None and payload.decision == "reject":
        project.status = "rejected"

    tracker = TrackerClient()
    try:
        issue_result = await db.execute(
            select(Task)
            .where(Task.project_id == application.project_id, Task.tracker_issue_id.is_not(None))
            .order_by(Task.created_at.desc())
            .limit(1)
        )
        issue_task = issue_result.scalar_one_or_none()
        if issue_task and issue_task.tracker_issue_id:
            await tracker.add_comment(
                issue_task.tracker_issue_id,
                f"Решение РП: {payload.decision}. Комментарий: {payload.comment}",
            )
    except Exception:
        pass

    if payload.decision == "approve":
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        await redis.rpush("orchestrator:research", str(application.id))
        await redis.close()
        if project is not None:
            project.status = "approved_for_research"

    db.add(
        AgentLog(
            project_id=application.project_id,
            correlation_id=uuid.uuid4(),
            agent_name="pm",
            stage="approval",
            action="decision",
            input_payload=payload.model_dump(),
            output_payload={"application_id": str(application.id), "decision": payload.decision},
            status=AgentLogStatus.SUCCESS,
        )
    )

    await db.commit()
    await db.refresh(application)
    return ApplicationResponse.model_validate(application)
