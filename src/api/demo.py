"""Demo data endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from db.base import get_db
from db.models import Application, ApplicationStatus, Project
from fixtures.demo_data import DEMO_APPLICATIONS

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/seed")
async def seed_demo_data(db: AsyncSession = Depends(get_db)) -> dict:
    if settings.app_env.lower() == "prod":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo seed is disabled in production",
        )

    created_ids: list[str] = []
    for item in DEMO_APPLICATIONS:
        project = Project(
            title=item["title"],
            description=item["text"],
            status="submitted",
            created_by=item["initiator_email"],
        )
        db.add(project)
        await db.flush()

        application = Application(
            project_id=project.id,
            initiator_name=item["initiator_name"],
            initiator_email=item["initiator_email"],
            title=item["title"],
            domain=item["domain"],
            text=item["text"],
            attachments_url=[],
            status=ApplicationStatus.SUBMITTED,
        )
        db.add(application)
        await db.flush()
        created_ids.append(str(application.id))

    await db.commit()
    return {"application_ids": created_ids}
