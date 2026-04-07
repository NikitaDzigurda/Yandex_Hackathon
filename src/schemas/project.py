"""Pydantic schemas for projects."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from schemas.application import ApplicationResponse


class ProjectCreate(BaseModel):
    title: str
    description: str


class ProjectResponse(BaseModel):
    id: UUID
    title: str
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProjectDetailResponse(ProjectResponse):
    description: str | None
    applications: list[ApplicationResponse] = []
