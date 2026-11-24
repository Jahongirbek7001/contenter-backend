"""Gemini API providers (Interactions API): Hydrogen text, Nano Banana image, Lyria music,
Omni video. Request shapes follow ai.google.dev/gemini-api/docs/omni and music-generation.
"""

import base64
from decimal import Decimal

from google.genai.interactions import Interaction

from app.gateway.base import (
    ASPECT_RATIO,
    MediaInput,
    MediaResult,
    ProviderFailedError,
    TextResult,
    UnsupportedRequestError,
    VideoCapabilities,
    VideoRequest,
    VideoResult,
    validate_video_request,
)
from app.gateway.capabilities import OMNI_1_2_FLASH
from app.gateway.google_clients import InteractionsApi, RequestBody, run_interaction
from app.gateway.pricing import request_cost, token_cost
from app.models.enums import Resolution

IMAGE_SIZE = "2K"
UPSCALE_INSTRUCTION = (
    "Keep this video exactly as it is: same frames, motion, audio and speech. "
    "Only increase the resolution."
)


def media_part(media: MediaInput) -> RequestBody:
    kind = media.mime_type.split("/", 1)[0]
    if kind not in {"image", "video", "audio"}:
        raise UnsupportedRequestError(f"unsupported media type {media.mime_type}")
    return {
        "type": kind,
        "data": base64.b64encode(media.data).decode("ascii"),
        "mime_type": media.mime_type,
    }


def text_part(text: str) -> RequestBody:
    return {"type": "text", "text": text}


def usage_cost(model: str, interaction: Interaction) -> Decimal:
    usage = interaction.usage
    if usage is None:
        return Decimal(0)
    # Thinking tokens are billed at the output rate.
    output_tokens = (usage.total_output_tokens or 0) + (usage.total_thought_tokens or 0)
    return token_cost(model, usage.total_input_tokens or 0, output_tokens)


class HydrogenTextProvider:
    def __init__(self, api: InteractionsApi, model: str) -> None:
        self._api = api
        self.model = model

    async def complete(
        self, instructions: str, prompt: str, media: tuple[MediaInput, ...]
    ) -> TextResult:
        interaction = await run_interaction(
            self._api,
            {
                "model": self.model,
                "system_instruction": instructions,
                "input": [*(media_part(m) for m in media), text_part(prompt)],
            },
        )
        if not interaction.output_text:
            raise ProviderFailedError("empty text response")
        return TextResult(
            text=interaction.output_text, cost_usd=usage_cost(self.model, interaction)
        )


class NanoBananaImageProvider:
    def __init__(self, api: InteractionsApi, model: str) -> None:
        self._api = api
        self.model = model

    async def compose(self, prompt: str, images: tuple[MediaInput, ...]) -> MediaResult:
        interaction = await run_interaction(
            self._api,
            {
                "model": self.model,
                "input": [*(media_part(i) for i in images), text_part(prompt)],
                "response_format": {
                    "type": "image",
                    "aspect_ratio": ASPECT_RATIO,
                    "image_size": IMAGE_SIZE,
                },
            },
        )
        image = interaction.output_image
        if image is None or not image.data:
            raise ProviderFailedError("no image in response")
        return MediaResult(
            data=base64.b64decode(image.data),
            mime_type=image.mime_type or "image/png",
            cost_usd=usage_cost(self.model, interaction),
        )


class LyriaMusicProvider:
    def __init__(self, api: InteractionsApi, model: str) -> None:
        self._api = api
        self.model = model

    async def compose(self, prompt: str) -> MediaResult:
        interaction = await run_interaction(self._api, {"model": self.model, "input": prompt})
        audio = interaction.output_audio
        if audio is None or not audio.data:
            raise ProviderFailedError("no audio in response")
        return MediaResult(
            data=base64.b64decode(audio.data),
            mime_type=audio.mime_type or "audio/mpeg",
            cost_usd=request_cost(self.model),
        )


class OmniVideoProvider:
    """continuation_id is the interaction id; extend and upscale build on it server-side."""

    def __init__(self, api: InteractionsApi, model: str) -> None:
        self._api = api
        self.model = model

    @property
    def capabilities(self) -> VideoCapabilities:
        return OMNI_1_2_FLASH

    async def generate(self, request: VideoRequest) -> VideoResult:
        validate_video_request(self.capabilities, request)
        images = (
            *request.reference_images,
            *((request.first_frame,) if request.first_frame else ()),
        )
        return await self._run(
            {
                "model": self.model,
                "input": [*(media_part(i) for i in images), text_part(request.prompt)],
                "response_format": self._format(request.duration_seconds, request.resolution),
            }
        )

    async def extend(self, continuation_id: str, prompt: str, duration_seconds: int) -> VideoResult:
        if not 3 <= duration_seconds <= 10:
            raise UnsupportedRequestError("extension must be 3-10 seconds")
        return await self._run(
            {
                "model": self.model,
                "previous_interaction_id": continuation_id,
                "input": prompt,
                "response_format": {
                    "type": "video",
                    "aspect_ratio": ASPECT_RATIO,
                    "duration": f"{duration_seconds}s",
                },
            }
        )

    async def upscale(self, continuation_id: str, target: Resolution) -> VideoResult:
        if target not in self.capabilities.resolutions:
            raise UnsupportedRequestError(f"resolution {target} not supported")
        return await self._run(
            {
                "model": self.model,
                "previous_interaction_id": continuation_id,
                "input": UPSCALE_INSTRUCTION,
                "response_format": {
                    "type": "video",
                    "aspect_ratio": ASPECT_RATIO,
                    "resolution": target.value,
                },
            }
        )

    @staticmethod
    def _format(duration_seconds: int, resolution: Resolution) -> RequestBody:
        return {
            "type": "video",
            "aspect_ratio": ASPECT_RATIO,
            "duration": f"{duration_seconds}s",
            "resolution": resolution.value,
        }

    async def _run(self, body: RequestBody) -> VideoResult:
        interaction = await run_interaction(self._api, body)
        video = interaction.output_video
        if video is None or not video.data:
            raise ProviderFailedError("no video in response")
        return VideoResult(
            data=base64.b64decode(video.data),
            mime_type=video.mime_type or "video/mp4",
            cost_usd=usage_cost(self.model, interaction),
            provider_job_id=interaction.id or "",
            continuation_id=interaction.id,
        )
