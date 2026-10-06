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
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000"
    ]

    # ---- Session & Cookies ----
    session_cookie_name: str = "session_id"
    session_max_age_seconds: int = 60 * 60 * 24 * 7  # 7 days
    session_cookie_secure: bool = False  # Set to True in production (HTTPS)
    session_cookie_samesite: str = "lax"  # "lax", "strict", or "none"
    session_cookie_domain: str | None = None
    session_cookie_path: str = "/"

    # ---- Document Upload ----
    upload_max_file_size_bytes: int = 10_485_760  # 10 MB
    upload_allowed_extensions: list[str] = [".csv", ".pdf"]
    upload_storage_dir: str = "uploads"

    # ---- OAuth ----
    google_client_id: str = "google-dummy-client-id.apps.googleusercontent.com"
    google_client_secret: str = "google-dummy-client-secret"
    google_redirect_uri: str = "http://localhost:5173/auth/callback/google"
    facebook_client_id: str = "facebook-dummy-client-id"
    facebook_client_secret: str = "facebook-dummy-client-secret"
    facebook_redirect_uri: str = "http://localhost:5173/auth/callback/facebook"
    oauth_state_secret: str = "oauth-state-secret-key-change-in-prod"

    # ---- LLM / AI Explanation Layer (Phase 13 + Phase 16) ----
    # Provider: "gemini" (production/free-tier), "mock" (deterministic test provider), or "none" (disabled).
    llm_provider: str = "none"
    llm_api_key: str = ""
    gemini_api_key: str | None = None
    llm_model: str = "gemini-3.5-flash"
    llm_timeout_seconds: int = 30
    llm_max_tokens: int = 2048
    llm_temperature: float = 0.1  # Low temperature for factual consistency

    # ---- AI Safety Layer Limits (Phase 16) ----
    ai_max_input_tokens: int = 4000
    ai_max_output_tokens: int = 2048
    ai_max_tool_result_size: int = 8000
    ai_max_document_context_size: int = 10000
    ai_max_question_length: int = 1000
    ai_max_chat_history_messages: int = 10
    ai_max_tool_calls_per_request: int = 3
    ai_rate_limit_per_minute: int = 10

    model_config = {
        "env_file": (".env", "../.env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()

