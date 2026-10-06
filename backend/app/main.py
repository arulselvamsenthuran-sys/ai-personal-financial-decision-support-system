"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.financial import router as financial_router
from app.api.health import router as health_router
from app.api.oauth import router as oauth_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — runs on startup and shutdown."""
    logger.info("Starting %s", settings.app_name)
    logger.info("API docs available at http://%s:%s/docs", settings.api_host, settings.api_port)
    yield
    logger.info("Shutting down %s", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    description="AI-Powered Personal Financial Decision Support System — Phase 6 Financial Data Model",
    version="0.6.0",
    lifespan=lifespan,
    swagger_ui_parameters={"withCredentials": True},
)

# ---- CORS ----
# Note: allow_origins must be explicit (never ["*"]) when allow_credentials=True
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ---- Error handlers ----
register_exception_handlers(app)

# ---- Routers ----
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(oauth_router)
app.include_router(financial_router)

