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


@lru_cache
def get_settings() -> Settings:
    return Settings()
