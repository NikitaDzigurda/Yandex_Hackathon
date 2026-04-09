"""Showcase API endpoints."""

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import get_db
from db.models import Project, ProjectStatus
from schemas.project import ProjectOut

router = APIRouter()


@router.get("", response_model=List[ProjectOut])
async def get_showcase(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Project)
        .where(Project.status == ProjectStatus.on_showcase.value)
        .order_by(Project.created_at.desc())
    )
    return result.scalars().all()
