"""Checks that the Google keys in .env work, using free metadata calls only.

Run from backend/: uv run python -m scripts.check_connections
Never prints key values.
"""

import sys
from pathlib import Path

import google.auth
import httpx
from google import genai
from google.auth.credentials import Credentials
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from app.core.config import Settings, get_settings

CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
MODEL_KEYWORDS = ("omni", "veo", "hydrogen", "lyria", "image", "banana")
VERTEX_VEO_CANDIDATES = (
    "veo-3.1-lite-generate-001",
    "veo-3.1-lite-generate-preview",
    "veo-3.1-fast-generate-001",
    "veo-3.1-generate-001",
)


def report(ok: bool, label: str, detail: str = "") -> bool:
    print(f"[{'OK' if ok else 'FAIL'}] {label}{': ' + detail if detail else ''}")
    return ok


def check_gemini_api(settings: Settings) -> bool:
    client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())
    try:
        names = [m.name or "" for m in client.models.list()]
    except Exception as exc:
        return report(False, "Gemini API key", f"{type(exc).__name__}: {exc}")
    report(True, "Gemini API key", f"{len(names)} models visible")
    for name in sorted(n for n in names if any(k in n.lower() for k in MODEL_KEYWORDS)):
        print(f"       {name}")
    return True


def load_vertex_credentials(settings: Settings) -> Credentials:
    if settings.google_application_credentials:
        path = Path(settings.google_application_credentials)
        if not path.is_file():
            raise FileNotFoundError(f"service account file not found: {path}")
        creds: Credentials = service_account.Credentials.from_service_account_file(
            str(path),
            scopes=[CLOUD_SCOPE],  # type: ignore[no-untyped-call]
        )
        return creds
    adc, _ = google.auth.default(scopes=[CLOUD_SCOPE])
    return adc


def check_vertex(settings: Settings) -> bool:
    source = "service account" if settings.google_application_credentials else "gcloud ADC"
    try:
        creds = load_vertex_credentials(settings)
        creds.refresh(Request())  # type: ignore[no-untyped-call]
    except Exception as exc:
        return report(False, f"Vertex auth ({source})", f"{type(exc).__name__}: {exc}")
    sa_project = getattr(creds, "project_id", None)
    report(True, f"Vertex auth ({source})", f"key project = {sa_project or 'n/a'}")
    if sa_project and sa_project != settings.gcp_project_id:
        report(False, "GCP_PROJECT_ID", f"{settings.gcp_project_id} != key project {sa_project}")

    client = genai.Client(
        vertexai=True,
        project=settings.gcp_project_id,
        location=settings.gcp_location,
        credentials=creds,
    )
    found = False
    for model_id in VERTEX_VEO_CANDIDATES:
        try:
            client.models.get(model=model_id)
        except Exception as exc:
            print(f"       {model_id}: not available ({type(exc).__name__})")
            continue
        report(True, "Vertex Veo model", model_id)
        found = True
    return found or report(False, "Vertex Veo model", "none of the candidates answered")


def check_telegram(settings: Settings) -> bool:
    token = settings.telegram_bot_token.get_secret_value()
    try:
        response = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15)
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # The exception text can contain the request URL, which holds the token.
        return report(False, "Telegram bot token", type(exc).__name__)
    if not payload.get("ok"):
        return report(False, "Telegram bot token", str(payload.get("description")))
    bot = payload["result"]
    return report(True, "Telegram bot token", f"@{bot.get('username')} (id {bot.get('id')})")


def main() -> int:
    settings = get_settings()
    print(f"project={settings.gcp_project_id} location={settings.gcp_location}")
    results = [check_gemini_api(settings), check_vertex(settings), check_telegram(settings)]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
