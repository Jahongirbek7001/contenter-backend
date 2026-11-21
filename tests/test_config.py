import pytest

from app.core.config import Settings


def test_settings_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("GCP_LOCATION", "us-central1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")

    settings = Settings(_env_file=None)

    assert settings.gcp_location == "us-central1"
    assert settings.gemini_api_key.get_secret_value() == "test-key"
    assert "test-key" not in repr(settings)
