"""In-memory provider for tests and local development without Google keys."""

from decimal import Decimal

from app.gateway.base import (
    ProviderBlockedError,
    VideoCapabilities,
    VideoRequest,
    VideoResult,
    validate_video_request,
)
from app.models.enums import Resolution

BLOCKED_MARKER = "[blocked]"


class FakeVideoProvider:
    def __init__(self, model: str, capabilities: VideoCapabilities) -> None:
        self.model = model
        self._capabilities = capabilities
        self.requests: list[VideoRequest] = []

    @property
    def capabilities(self) -> VideoCapabilities:
        return self._capabilities

    async def generate(self, request: VideoRequest) -> VideoResult:
        validate_video_request(self._capabilities, request)
        if BLOCKED_MARKER in request.prompt:
            raise ProviderBlockedError("fake safety filter")
        self.requests.append(request)
        return self._result(f"gen-{len(self.requests)}")

    async def extend(self, continuation_id: str, prompt: str, duration_seconds: int) -> VideoResult:
        return self._result(f"{continuation_id}+ext")

    async def upscale(self, continuation_id: str, target: Resolution) -> VideoResult:
        return self._result(f"{continuation_id}@{target}")

    def _result(self, job_id: str) -> VideoResult:
        return VideoResult(
            data=b"fake-mp4",
            mime_type="video/mp4",
            cost_usd=Decimal("0"),
            provider_job_id=job_id,
            continuation_id=job_id,
        )
