"""
Market Auto Issuer — FastAPI application.
"""
import logging
import sys

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import engine
from app.models.models import Base

# Auto-create tables on startup (Alembic handles migrations in production)
Base.metadata.create_all(bind=engine)

from app.api.webhook import router as webhook_router
from app.api.admin_api import router as admin_api_router
from app.api.admin_ui import router as admin_ui_router

logging.basicConfig(
    stream=sys.stdout,
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(webhook_router, prefix="/api")
app.include_router(admin_api_router)
app.include_router(admin_ui_router)


# ── Health check ─────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}


# ── Root redirect ─────────────────────────────────────────────────────────────
@app.get("/")
def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin")
