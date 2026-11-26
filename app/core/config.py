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
    telegram_bot_username: str = "contentorai_bot"

    # User photos and cached music; object storage replaces this when the worker moves hosts.
    media_dir: str = "var/media"
    ffmpeg_path: str = "ffmpeg"

    # Site origins allowed to call the API from the browser (JSON list in .env).
    cors_origins: list[str] = ["http://localhost:3000"]

    # True in production (HTTPS); local development runs over plain http.
    admin_cookie_secure: bool = False

    # Public site address; Payme/Click send the customer back here after paying.
    site_url: str = "http://localhost:3000"

    # Shown by /paysupport (Telegram requires it for Stars), e.g. "@contentor_support".
    # Unset: the site address is shown instead.
    support_contact: str | None = None

    # Payme Merchant API. Unset until the merchant contract is signed: the site then hides Payme.
    payme_merchant_id: str | None = None
    payme_key: SecretStr | None = None
    # True: checkout on test.paycom.uz with the sandbox key.
    payme_test: bool = True

    # Click SHOP-API. Unset until the merchant contract is signed: the site then hides Click.
    click_service_id: str | None = None
    click_merchant_id: str | None = None
    click_secret_key: SecretStr | None = None

    # LOCAL DEVELOPMENT ONLY: lets the mini app run in a normal browser (no Telegram
    # initData) as this Telegram user. Must stay unset in production.
    miniapp_dev_telegram_id: int | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
