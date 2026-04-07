"""Pydantic schemas for projects."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
    applications: list[ApplicationResponse] = Field(default_factory=list)


class ProjectStatusResponse(BaseModel):
    project_id: UUID
    title: str
    status: str
    application: dict | None
    research_report: dict | None
    tracker_tasks: list[dict]
    recent_agent_logs: list[dict]
    created_at: datetime
