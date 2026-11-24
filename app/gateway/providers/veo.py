"""Veo on Vertex AI (Agent Platform): silent trend clips from a first frame."""

import asyncio
import time
from typing import Protocol

from google import genai
from google.genai import types
from google.genai.errors import APIError

from app.gateway.base import (
    ASPECT_RATIO,
    ProviderBlockedError,
    ProviderFailedError,
    UnsupportedRequestError,
    VideoCapabilities,
    VideoRequest,
    VideoResult,
    validate_video_request,
)
from app.gateway.capabilities import VEO_3_1_LITE
from app.gateway.google_clients import (
    GENERATION_TIMEOUT_SECONDS,
    POLL_INTERVAL_SECONDS,
    is_safety_message,
)
from app.gateway.pricing import veo_cost
from app.models.enums import Resolution

Operation = types.GenerateVideosOperation


class VideoOperationsApi(Protocol):
    async def start(
        self, model: str, prompt: str, image: types.Image | None, config: types.GenerateVideosConfig
    ) -> Operation: ...

    async def refresh(self, operation: Operation) -> Operation: ...


class SdkVideoOperations:
    def __init__(self, client: genai.Client) -> None:
        self._client = client

    async def start(
        self, model: str, prompt: str, image: types.Image | None, config: types.GenerateVideosConfig
    ) -> Operation:
        try:
            return await self._client.aio.models.generate_videos(
                model=model, prompt=prompt, image=image, config=config
            )
        except APIError as exc:
            if exc.code == 400 and is_safety_message(str(exc.message)):
                raise ProviderBlockedError(str(exc)) from exc
            raise ProviderFailedError(str(exc)) from exc

    async def refresh(self, operation: Operation) -> Operation:
        try:
            return await self._client.aio.operations.get(operation)
        except APIError as exc:
            raise ProviderFailedError(str(exc)) from exc


class VeoVideoProvider:
    def __init__(self, api: VideoOperationsApi, model: str) -> None:
        self._api = api
        self.model = model

    @property
    def capabilities(self) -> VideoCapabilities:
        return VEO_3_1_LITE

    async def generate(self, request: VideoRequest) -> VideoResult:
        validate_video_request(self.capabilities, request)
        image = (
            types.Image(
                image_bytes=request.first_frame.data, mime_type=request.first_frame.mime_type
            )
            if request.first_frame
            else None
        )
        config = types.GenerateVideosConfig(
            aspect_ratio=ASPECT_RATIO,
            resolution=request.resolution.value,
            duration_seconds=request.duration_seconds,
            generate_audio=False,
            number_of_videos=1,
            person_generation="allow_adult",
        )
        operation = await self._api.start(self.model, request.prompt, image, config)
        operation = await self._wait(operation)
        return self._result(operation, request)

    async def extend(self, continuation_id: str, prompt: str, duration_seconds: int) -> VideoResult:
        raise UnsupportedRequestError("Veo 3.1 Lite cannot extend videos")

    async def upscale(self, continuation_id: str, target: Resolution) -> VideoResult:
        raise UnsupportedRequestError("Veo 3.1 Lite cannot upscale videos")

    async def _wait(self, operation: Operation) -> Operation:
        deadline = time.monotonic() + GENERATION_TIMEOUT_SECONDS
        while not operation.done:
            if time.monotonic() > deadline:
                raise ProviderFailedError(f"operation {operation.name} timed out")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            operation = await self._api.refresh(operation)
        return operation

    def _result(self, operation: Operation, request: VideoRequest) -> VideoResult:
        if operation.error:
            message = str(operation.error.get("message", operation.error))
            if is_safety_message(message):
                raise ProviderBlockedError(message)
            raise ProviderFailedError(message)
        response = operation.response or operation.result
        if response is None:
            raise ProviderFailedError("operation finished without a response")
        if response.rai_media_filtered_count:
            reasons = "; ".join(response.rai_media_filtered_reasons or [])
            raise ProviderBlockedError(f"Veo safety filter: {reasons or 'no reason given'}")
        videos = response.generated_videos or []
        video = videos[0].video if videos else None
        if video is None or not video.video_bytes:
            raise ProviderFailedError("no video bytes in response")
        return VideoResult(
            data=video.video_bytes,
            mime_type=video.mime_type or "video/mp4",
            cost_usd=veo_cost(self.model, request.resolution, request.duration_seconds),
            provider_job_id=operation.name or "",
            continuation_id=None,
        )
