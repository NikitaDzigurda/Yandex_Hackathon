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
    # Simple research format (fallback path)
    domain_overview: str | None = None
    key_sources: list[dict] | None = None
    hypotheses: list[dict] | None = None
    risks: list[dict] | None = None
    recommendations: str | None = None
    confidence_score: float | None = None

    # Deep research format
    source: str | None = None
    project_name: str | None = None
    decision: str | None = None
    feasibility_score: float | None = None
    quality_score: float | None = None
    completeness_score: float | None = None
    executive_summary: str | None = None
    final_report: str | None = None
    duration_sec: float | None = None
    agents_completed: int | None = None
    agents_total: int | None = None
