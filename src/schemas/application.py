"""Pydantic schemas for applications and intake results."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from db.models import ApplicationStatus


class ApplicationCreate(BaseModel):
    initiator_name: str
    initiator_email: EmailStr
    title: str
    text: str
    domain: str
    attachments_url: list[str] = Field(default_factory=list)


class ApplicationResponse(BaseModel):
    id: UUID
    project_id: UUID
    status: ApplicationStatus
    scorecard: dict | None
    summary: str | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ScorecardItem(BaseModel):
    criterion: str
    score: int = Field(ge=1, le=10)
    rationale: str


class IntakeResult(BaseModel):
    application_id: UUID
    scorecard: list[ScorecardItem]
    clarifying_questions: list[str]
    summary: str
    recommended_action: Literal["approve", "reject", "clarify"]


class ResearchReport(BaseModel):
    domain_overview: str
    key_sources: list[dict]
    hypotheses: list[dict]
    risks: list[dict]
    recommendations: str
    confidence_score: float
