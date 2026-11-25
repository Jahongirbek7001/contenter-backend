from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str

    gemini_api_key: SecretStr
    gcp_project_id: str
    gcp_location: str
    # Service account key path; None means Application Default Credentials (gcloud login).
    google_application_credentials: str | None = None

    telegram_bot_token: SecretStr

    # Site origins allowed to call the API from the browser (JSON list in .env).
    cors_origins: list[str] = ["http://localhost:3000"]

    # True in production (HTTPS); local development runs over plain http.
    admin_cookie_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
