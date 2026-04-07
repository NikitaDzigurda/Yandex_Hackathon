"""Top-level API router."""

from fastapi import APIRouter

from api.applications import router as applications_router
from api.demo import router as demo_router
from api.projects import router as projects_router

api_router = APIRouter()
api_router.include_router(applications_router)
api_router.include_router(projects_router)
api_router.include_router(demo_router)
