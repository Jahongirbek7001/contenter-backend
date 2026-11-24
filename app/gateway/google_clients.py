"""Builds google-genai clients and adapts the Interactions API to a narrow, typed port."""

import asyncio
import time
from pathlib import Path
from typing import Any, Protocol

from google import genai
from google.auth.credentials import Credentials

# The Interactions API raises its own error types; they are not re-exported publicly.
from google.genai._gaos.lib.compat_errors import APIError, APIStatusError
from google.genai.interactions import Interaction
from google.oauth2 import service_account

from app.core.config import Settings
from app.gateway.base import ProviderBlockedError, ProviderFailedError

# Request bodies are JSON-shaped dicts passed straight to the SDK.
RequestBody = dict[str, Any]

CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
POLL_INTERVAL_SECONDS = 5.0
GENERATION_TIMEOUT_SECONDS = 600.0

_PENDING_STATUSES = frozenset({"in_progress", "queued"})
_SAFETY_MARKERS = ("safety", "blocked", "prohibited", "usage polic", "responsible ai")


def is_safety_message(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _SAFETY_MARKERS)


class InteractionsApi(Protocol):
    async def create(self, body: RequestBody) -> Interaction: ...

    async def get(self, interaction_id: str) -> Interaction: ...


class SdkInteractions:
    def __init__(self, client: genai.Client) -> None:
        self._api = client.aio.interactions

    async def create(self, body: RequestBody) -> Interaction:
        try:
            result = await self._api.create(timeout=GENERATION_TIMEOUT_SECONDS, **body)
        except APIStatusError as exc:
            raise _map_status_error(exc.status_code or 0, exc.message) from exc
        except APIError as exc:
            raise ProviderFailedError(str(exc)) from exc
        return _expect_interaction(result)

    async def get(self, interaction_id: str) -> Interaction:
        try:
            result = await self._api.get(interaction_id, timeout=60)
        except APIError as exc:
            raise ProviderFailedError(str(exc)) from exc
        return _expect_interaction(result)


async def run_interaction(api: InteractionsApi, body: RequestBody) -> Interaction:
    """Creates an interaction and waits for a final status, mapping failures to gateway errors."""
    interaction = await api.create(body)
    if not interaction.id:
        raise ProviderFailedError("interaction has no id")
    interaction_id = interaction.id
    deadline = time.monotonic() + GENERATION_TIMEOUT_SECONDS
    while interaction.status in _PENDING_STATUSES:
        if time.monotonic() > deadline:
            raise ProviderFailedError(f"interaction {interaction_id} timed out")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        interaction = await api.get(interaction_id)
    if interaction.status != "completed":
        message = "; ".join(f"{e.code}: {e.message}" for e in interaction.errors or [])
        detail = f"interaction {interaction.status}: {message or 'no details'}"
        if is_safety_message(message):
            raise ProviderBlockedError(detail)
        raise ProviderFailedError(detail)
    return interaction


def gemini_client(settings: Settings) -> genai.Client:
    return genai.Client(api_key=settings.gemini_api_key.get_secret_value())


def vertex_credentials(settings: Settings) -> Credentials | None:
    """Service account key when configured; None lets the SDK use gcloud ADC."""
    if not settings.google_application_credentials:
        return None
    path = Path(settings.google_application_credentials)
    if not path.is_file():
        raise FileNotFoundError(f"service account file not found: {path}")
    credentials: Credentials = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
        str(path), scopes=[CLOUD_SCOPE]
    )
    return credentials


def vertex_client(settings: Settings) -> genai.Client:
    return genai.Client(
        vertexai=True,
        project=settings.gcp_project_id,
        location=settings.gcp_location,
        credentials=vertex_credentials(settings),
    )


def _map_status_error(status_code: int, message: str) -> ProviderBlockedError | ProviderFailedError:
    detail = f"HTTP {status_code}: {message}"
    if status_code == 400 and is_safety_message(message):
        return ProviderBlockedError(detail)
    return ProviderFailedError(detail)


def _expect_interaction(result: object) -> Interaction:
    if not isinstance(result, Interaction):
        raise ProviderFailedError(f"expected an interaction, got {type(result).__name__}")
    return result
