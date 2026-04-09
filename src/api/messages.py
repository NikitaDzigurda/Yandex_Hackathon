"""Messages API endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_current_user
from db.base import get_db
from db.models import Message, Project, User

router = APIRouter()


class MessageCreate(BaseModel):
    body: str


class MessageOut(BaseModel):
    id: UUID
    project_id: UUID
    author_id: UUID
    body: str
    created_at: str

    model_config = ConfigDict(from_attributes=True)


@router.get("/{project_id}/messages", response_model=List[MessageOut])
async def get_messages(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.role == "submitter" and project.submitter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    msg_result = await db.execute(
        select(Message)
        .where(Message.project_id == project_id)
        .order_by(Message.created_at.asc())
    )
    messages = msg_result.scalars().all()
    
    return [
        {
            "id": msg.id,
            "project_id": msg.project_id,
            "author_id": msg.author_id,
            "body": msg.body,
            "created_at": msg.created_at.isoformat(),
        }
        for msg in messages
    ]


@router.post("/{project_id}/messages", response_model=MessageOut)
async def create_message(
    project_id: UUID,
    req: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not req.body or not req.body.strip():
        raise HTTPException(status_code=422, detail="Message body cannot be empty")

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.role == "submitter" and project.submitter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    msg = Message(
        project_id=project.id,
        author_id=current_user.id,
        body=req.body.strip(),
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    return {
        "id": msg.id,
        "project_id": msg.project_id,
        "author_id": msg.author_id,
        "body": msg.body,
        "created_at": msg.created_at.isoformat(),
    }
