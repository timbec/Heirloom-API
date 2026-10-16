from fastapi import APIRouter

from app.api import auth, health, narratives, sessions, subjects, transcripts

# Heirloom's app endpoints, at the paths the frontend already calls.
v1_router = APIRouter(prefix="/heirloom/v1")
v1_router.include_router(subjects.router)
v1_router.include_router(sessions.router)
v1_router.include_router(transcripts.router)
v1_router.include_router(narratives.router)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(v1_router)
api_router.include_router(narratives.share_router, prefix="/heirloom")
