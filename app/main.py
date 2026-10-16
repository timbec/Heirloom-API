from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin import mount_admin
from app.api import api_router
from app.config import get_settings
from app.errors import register_error_handlers


def create_app() -> FastAPI:
    settings = get_settings()
    # Docs live under /api with everything else, so one proxy rule covers the whole service.
    app = FastAPI(
        title="Heirloom API",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # Bearer tokens, no cookies, so credentials aren't needed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(api_router, prefix="/api")
    mount_admin(app)
    return app


app = create_app()
