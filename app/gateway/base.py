"""Model gateway contracts. Product code depends on these, never on a vendor SDK."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from app.models.enums import Resolution

ASPECT_RATIO = "9:16"


class ProviderError(Exception):
    pass


class ProviderBlockedError(ProviderError):
    """The provider's safety filter rejected the request; the user gets credits back."""


class ProviderFailedError(ProviderError):
    """Technical failure (timeout, 5xx, malformed response)."""


class UnsupportedRequestError(ProviderError):
    pass


@dataclass(frozen=True)
class MediaInput:
    data: bytes
    mime_type: str


@dataclass(frozen=True)
class MediaResult:
    data: bytes
    mime_type: str
    cost_usd: Decimal


@dataclass(frozen=True)
class TextResult:
    text: str
    cost_usd: Decimal


@dataclass(frozen=True)
class VideoResult(MediaResult):
    provider_job_id: str
    # Handle for extend/upscale on providers that keep server-side state (Omni interactions).
    continuation_id: str | None


@dataclass(frozen=True)
class VideoCapabilities:
    durations_seconds: frozenset[int]
    resolutions: frozenset[Resolution]
    audio: bool
    max_reference_images: int
    first_frame: bool
    extend: bool
    upscale: bool


@dataclass(frozen=True)
class VideoRequest:
    prompt: str
    duration_seconds: int
    resolution: Resolution
    audio: bool
    first_frame: MediaInput | None = None
    reference_images: tuple[MediaInput, ...] = field(default_factory=tuple)


class TextProvider(Protocol):
    async def complete(
        self, instructions: str, prompt: str, media: tuple[MediaInput, ...]
    ) -> TextResult: ...


class ImageProvider(Protocol):
    async def compose(self, prompt: str, images: tuple[MediaInput, ...]) -> MediaResult: ...


class MusicProvider(Protocol):
    async def compose(self, prompt: str) -> MediaResult: ...


class VideoProvider(Protocol):
    @property
    def capabilities(self) -> VideoCapabilities: ...

    async def generate(self, request: VideoRequest) -> VideoResult: ...

    async def extend(
        self, continuation_id: str, prompt: str, duration_seconds: int
    ) -> VideoResult: ...

    async def upscale(self, continuation_id: str, target: Resolution) -> VideoResult: ...


def validate_video_request(capabilities: VideoCapabilities, request: VideoRequest) -> None:
    if request.duration_seconds not in capabilities.durations_seconds:
        raise UnsupportedRequestError(f"duration {request.duration_seconds}s not supported")
    if request.resolution not in capabilities.resolutions:
        raise UnsupportedRequestError(f"resolution {request.resolution} not supported")
    if request.audio and not capabilities.audio:
        raise UnsupportedRequestError("audio not supported")
    if request.first_frame is not None and not capabilities.first_frame:
        raise UnsupportedRequestError("first frame not supported")
    if len(request.reference_images) > capabilities.max_reference_images:
        raise UnsupportedRequestError(
            f"{len(request.reference_images)} reference images, "
            f"max {capabilities.max_reference_images}"
        )
