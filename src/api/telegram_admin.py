"""Telegram Admin API endpoints and notifications."""

import logging
from typing import List
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from db.base import get_db
from db.models import Project, TelegramSubscriber, User
from integrations.yandex_cloud import YandexCloudAgentClient
from integrations.yandex_responses import YandexResponsesClient
from core.security import require_admin, require_reviewer

logger = logging.getLogger(__name__)
router = APIRouter()


class TelegramSubscriberCreate(BaseModel):
    chat_id: str
    label: str | None = None


class TelegramSubscriberOut(BaseModel):
    id: UUID
    chat_id: str
    label: str | None
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class TelegramSubscriberListEnvelope(BaseModel):
    ok: bool = True
    result: List[TelegramSubscriberOut]


@router.get("", response_model=TelegramSubscriberListEnvelope)
async def get_subscribers(
    current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(TelegramSubscriber).order_by(TelegramSubscriber.created_at.desc()))
    subscribers = result.scalars().all()
    out = [
        {
            "id": s.id,
            "chat_id": s.chat_id,
            "label": s.label,
            "created_at": s.created_at.isoformat(),
        }
        for s in subscribers
    ]
    return {"ok": True, "result": out}


@router.post("", response_model=TelegramSubscriberOut, status_code=status.HTTP_201_CREATED)
async def add_subscriber(
    req: TelegramSubscriberCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not req.chat_id or len(req.chat_id) > 32:
        raise HTTPException(status_code=422, detail="Invalid chat_id")
        
    result = await db.execute(select(TelegramSubscriber).where(TelegramSubscriber.chat_id == req.chat_id))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="chat_id already registered")

    sub = TelegramSubscriber(chat_id=req.chat_id, label=req.label[:255] if req.label else None)
    db.add(sub)
    await db.commit()
    await db.refresh(sub)

    return {
        "id": sub.id,
        "chat_id": sub.chat_id,
        "label": sub.label,
        "created_at": sub.created_at.isoformat(),
    }


@router.delete("/{subscriber_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscriber(
    subscriber_id: UUID, current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(TelegramSubscriber).where(TelegramSubscriber.id == subscriber_id))
    sub = result.scalar_one_or_none()
    
    if not sub:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    await db.delete(sub)
    await db.commit()


async def notify_new_project_submitted(project_id: UUID, db: AsyncSession):
    if not settings.telegram_bot_token:
        return

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        return

    subs_result = await db.execute(select(TelegramSubscriber))
    subscribers = subs_result.scalars().all()
    if not subscribers:
        return

    url = f"{settings.public_app_url.rstrip('/')}/projects/{project.id}"
    text = f"Новый проект: {project.title}\nID: {project.id}\n{url}"

    api_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    
    async with httpx.AsyncClient() as client:
        for sub in subscribers:
            payload = {"chat_id": sub.chat_id, "text": text}
            try:
                await client.post(api_url, json=payload, timeout=5.0)
            except Exception as e:
                logger.error(f"Failed to send telegram message to {sub.chat_id}: {e}")


@router.get("/ping-models")
async def ping_models(current_user: User = Depends(require_reviewer)):
    """Check availability of Yandex Cloud models."""
    yc_client = YandexCloudAgentClient()
    responses_client = YandexResponsesClient()
    
    # Try to use a known prompt_id for a more robust check if available
    test_prompt_id = settings.eval_technical_analyst_id or ""
    
    results = {
        "yandex_cloud_llm": "testing...",
        "yandex_ai_studio_responses": "testing..."
    }
    
    results["yandex_cloud_llm"] = "OK" if await yc_client.ping() else "FAILED"
    results["yandex_ai_studio_responses"] = "OK" if await responses_client.ping(test_prompt_id) else "FAILED"
    
    return {
        "status": "success" if all(v == "OK" for v in results.values()) else "partial_failure",
        "results": results
    }
