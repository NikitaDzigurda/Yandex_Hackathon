"""Pydantic schemas for agent runs."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from db.models import RunStatus, RunType


class EvaluationRunRequest(BaseModel):
    evaluation_prompt: str | None = None
    tracker_context: str | None = None
    source_craft_context: str | None = None
    continue_on_agent_error: bool = False


class DeepResearchRunRequest(BaseModel):
    tracker_context: str | None = None
    source_craft_context: str | None = None
    continue_on_agent_error: bool = False


class AgentRunOut(BaseModel):
    id: UUID
    project_id: UUID
    run_type: RunType
    status: RunStatus
    current_agent: str | None
    completed_agents: int
    total_agents: int
    evaluation_prompt: str | None
    error_text: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentRunDetailOut(BaseModel):
    ok: bool = True
    result: AgentRunOut
    payload: dict | None
    progress: dict | None


class LatestDeepResearchOut(BaseModel):
    ok: bool = True
    project_id: UUID
    run_id: UUID
    finished_at: datetime | None
    payload: dict | None


class ExportRequest(BaseModel):
    queue: str | None = None


class ExportTasksOut(BaseModel):
    ok: bool = True
    tasks_planned: int = 0
    created: list[dict] = []
    errors: list[str] = []
