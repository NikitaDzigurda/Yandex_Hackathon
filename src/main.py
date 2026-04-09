"""FastAPI application entrypoint."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis
from sqlalchemy import text

from agents.orchestrator import Orchestrator
from api.auth import router as auth_router
from api.messages import router as messages_router
from api.projects import router as projects_router
from api.runs import router as runs_router
from api.showcase import router as showcase_router
from api.telegram_admin import router as telegram_admin_router
from core.config import settings
from db.base import Base
from db.base import engine
from db.base import AsyncSessionLocal
from db.models import User, UserRole
from core.security import get_password_hash
from integrations.tracker import TrackerClient
from integrations.yandex_cloud import YandexCloudAgentClient


async def _seed_admin() -> None:
    """Create a default admin user on first startup if none exist."""
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == "admin@example.com"))
        if result.scalar_one_or_none() is None:
            admin = User(
                email="admin@example.com",
                full_name="Admin",
                hashed_password=get_password_hash("secret123"),
                role=UserRole.admin,
                is_active=True,
            )
            session.add(admin)
            await session.commit()
            import logging
            logging.getLogger(__name__).info("Seeded default admin user: admin@example.com / secret123")


@asynccontextmanager
async def lifespan(_: FastAPI):
    orchestrator = Orchestrator()
    async with engine.begin() as connection:
        await connection.execute(text("SELECT 1"))
        # Dev-safe fallback: ensure schema exists even if migrations were skipped.
        await connection.run_sync(Base.metadata.create_all)
    await _seed_admin()
    orchestrator_task = asyncio.create_task(orchestrator.run())
    yield
    orchestrator_task.cancel()
    try:
        await orchestrator_task
    except asyncio.CancelledError:
        pass
    await orchestrator.close()


app = FastAPI(title="Yandex Hackathon API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(projects_router, prefix="/api/projects", tags=["projects"])
app.include_router(runs_router, prefix="/api/projects", tags=["runs"])
app.include_router(messages_router, prefix="/api/projects", tags=["messages"])
app.include_router(showcase_router, prefix="/api/showcase", tags=["showcase"])
app.include_router(telegram_admin_router, prefix="/api/admin", tags=["admin"])


@app.get("/health")
async def health() -> dict:
    checks = {
        "database": "error",
        "redis": "error",
        "yandex_cloud": "error",
        "tracker": "error",
    }

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"

    try:
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        await redis.ping()
        await redis.close()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"

    try:
        yc = YandexCloudAgentClient()
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                yc.base_url,
                headers=yc._headers,  # noqa: SLF001
                json={"modelUri": yc.build_model_uri("yandexgpt-pro"), "messages": [], "completionOptions": {"stream": False, "temperature": 0, "maxTokens": "1"}},
            )
        if response.status_code < 500:
            checks["yandex_cloud"] = "ok"
    except Exception:
        checks["yandex_cloud"] = "error"

    try:
        tracker = TrackerClient()
        await tracker.list_issues(settings.tracker_queue_key)
        checks["tracker"] = "ok"
    except Exception:
        checks["tracker"] = "error"

    if checks["database"] == "ok" and checks["redis"] == "ok":
        overall = "ok" if checks["tracker"] == "ok" and checks["yandex_cloud"] == "ok" else "degraded"
    else:
        overall = "error"

    return {
        "status": overall,
        "version": "0.1.0",
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


app.mount("/", StaticFiles(directory="static", html=True), name="static")
