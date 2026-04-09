"""Pydantic schemas for projects."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProjectCreate(BaseModel):
    title: str
    domain: str | None = None
    description: str | None = None
    attachments_url: list[str] | None = None
    task: str | None = None
    stage: str | None = None
    deadlines: str | None = None


class ProjectUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    task: str | None = None
    stage: str | None = None
    deadlines: str | None = None


class ReviewRequest(BaseModel):
    decision: str  # approve, reject, request_revision
    comment: str | None = None


class ProjectOut(BaseModel):
    id: UUID
    submitter_id: UUID | None
    reviewer_id: UUID | None
    title: str
    domain: str | None
    description: str | None
    attachments_url: list[str] | None
    task: str | None
    stage: str | None
    deadlines: str | None
    status: str
    human_decision: str
    reviewer_comment: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectOutEnvelope(BaseModel):
    ok: bool = True
    result: ProjectOut


class ReviewEnvelope(BaseModel):
    ok: bool = True
    result: ProjectOut
