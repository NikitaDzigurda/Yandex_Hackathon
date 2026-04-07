"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from api.router import api_router
from db.base import engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    yield


app = FastAPI(title="Yandex Hackathon API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


app.include_router(api_router)
