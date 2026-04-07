"""SQLAlchemy base objects and async session management."""

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


def _build_async_db_url() -> str:
    raw_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/hackathon")
    if raw_url.startswith("postgresql+psycopg://"):
        return raw_url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    if raw_url.startswith("postgresql://"):
        return raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw_url


class Base(DeclarativeBase):
    """Shared declarative base for ORM models."""


DATABASE_URL = _build_async_db_url()

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for acquiring a DB session."""
    async with AsyncSessionLocal() as session:
        yield session
