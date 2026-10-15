from fastapi import APIRouter

from app.api import auth, health, sessions, subjects

# Heirloom's app endpoints, at the paths the frontend already calls.
v1_router = APIRouter(prefix="/heirloom/v1")
v1_router.include_router(subjects.router)
v1_router.include_router(sessions.router)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(v1_router)
