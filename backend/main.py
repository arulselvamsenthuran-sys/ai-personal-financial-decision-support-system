"""FastAPI application entrypoint for Vercel / serverless deployments."""

from app.main import app

__all__ = ["app"]

