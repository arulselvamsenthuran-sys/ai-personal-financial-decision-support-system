"""Core configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings.

    Values are read from environment variables or a .env file.
    """

    # ---- Application ----
    app_name: str = "Finance Support API"
    debug: bool = False

    # ---- Database ----
    database_url: str = "postgresql+psycopg://findev:findev_local_password@localhost:5432/finance_support"

    # ---- Server ----
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # ---- CORS ----
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
