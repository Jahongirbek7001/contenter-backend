import base64
from decimal import Decimal

import pytest
from google.genai import types
from google.genai.interactions import Interaction

from app.gateway import google_clients
from app.gateway.base import (
    MediaInput,
    ProviderBlockedError,
    ProviderFailedError,
    UnsupportedRequestError,
    VideoRequest,
)
from app.gateway.google_clients import RequestBody, is_safety_message
from app.gateway.pricing import token_cost
from app.gateway.providers import veo
from app.gateway.providers.gemini import (
    HydrogenTextProvider,
    LyriaMusicProvider,
    OmniVideoProvider,
)
from app.gateway.providers.veo import VeoVideoProvider
from app.models.enums import Resolution

OMNI = "gemini-omni-1.2-flash"
VEO = "veo-3.1-lite-generate-001"
SELFIE = MediaInput(data=b"jpeg-bytes", mime_type="image/jpeg")


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def interaction(status: str = "completed", **fields: object) -> Interaction:
    return Interaction.model_validate({"id": "int-1", "status": status, **fields})


def video_done(data: bytes = b"mp4") -> Interaction:
    return interaction(
        output_video={"type": "video", "data": b64(data), "mime_type": "video/mp4"},
        usage={"total_input_tokens": 1000, "total_output_tokens": 57920},
    )


class StubInteractions:
    def __init__(self, *responses: Interaction) -> None:
        self._responses = list(responses)
        self.bodies: list[RequestBody] = []
        self.polled: list[str] = []

    async def create(self, body: RequestBody) -> Interaction:
        self.bodies.append(body)
        return self._responses.pop(0)

    async def get(self, interaction_id: str) -> Interaction:
        self.polled.append(interaction_id)
        return self._responses.pop(0)


class StubOperations:
    def __init__(self, *operations: types.GenerateVideosOperation) -> None:
        self._operations = list(operations)
        self.configs: list[types.GenerateVideosConfig] = []

    async def start(
        self,
        model: str,
        prompt: str,
        image: types.Image | None,
        config: types.GenerateVideosConfig,
    ) -> types.GenerateVideosOperation:
        self.configs.append(config)
        return self._operations.pop(0)

    async def refresh(
        self, operation: types.GenerateVideosOperation
    ) -> types.GenerateVideosOperation:
        return self._operations.pop(0)


@pytest.fixture(autouse=True)
def no_poll_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(google_clients, "POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(veo, "POLL_INTERVAL_SECONDS", 0)


async def test_omni_generate_sends_vertical_format_and_images_before_text() -> None:
    api = StubInteractions(video_done(b"clip"))

    result = await OmniVideoProvider(api, OMNI).generate(
        VideoRequest(
            prompt="Say hello",
            duration_seconds=10,
            resolution=Resolution.P720,
            audio=True,
            first_frame=SELFIE,
        )
    )

    body = api.bodies[0]
    assert body["response_format"] == {
        "type": "video",
        "aspect_ratio": "9:16",
        "duration": "10s",
        "resolution": "720p",
    }
    assert [part["type"] for part in body["input"]] == ["image", "text"]
    assert result.data == b"clip"
    assert result.continuation_id == "int-1"
    assert result.cost_usd == token_cost(OMNI, 1000, 57920)


async def test_omni_extend_continues_previous_interaction() -> None:
    api = StubInteractions(video_done())

    await OmniVideoProvider(api, OMNI).extend("int-0", "Continue the scene", 10)

    assert api.bodies[0]["previous_interaction_id"] == "int-0"
    assert api.bodies[0]["response_format"]["duration"] == "10s"


async def test_omni_extend_rejects_out_of_range_duration() -> None:
    with pytest.raises(UnsupportedRequestError):
        await OmniVideoProvider(StubInteractions(), OMNI).extend("int-0", "go", 15)


async def test_pending_interaction_is_polled_until_complete() -> None:
    api = StubInteractions(interaction("in_progress"), interaction("queued"), video_done())

    result = await OmniVideoProvider(api, OMNI).upscale("int-0", Resolution.P1080)

    assert api.polled == ["int-1", "int-1"]
    assert result.data == b"mp4"
    assert api.bodies[0]["response_format"]["resolution"] == "1080p"


@pytest.mark.parametrize(
    ("message", "error"),
    [
        ("Prompt blocked by safety filters", ProviderBlockedError),
        ("Internal error, try again", ProviderFailedError),
    ],
)
async def test_failed_interaction_maps_to_gateway_error(
    message: str, error: type[Exception]
) -> None:
    api = StubInteractions(interaction("failed", errors=[{"code": "x", "message": message}]))

    with pytest.raises(error):
        await HydrogenTextProvider(api, "gemini-4-hydrogen").complete("sys", "hi", ())


async def test_hydrogen_passes_system_instruction_and_media() -> None:
    response = interaction(
        usage={"total_input_tokens": 100, "total_output_tokens": 10, "total_thought_tokens": 50}
    )
    # The SDK derives output_text while parsing the HTTP response, not in model validation.
    response.output_text = "a prompt"
    api = StubInteractions(response)

    result = await HydrogenTextProvider(api, "gemini-4-hydrogen").complete(
        "be brief", "write a prompt", (SELFIE,)
    )

    assert api.bodies[0]["system_instruction"] == "be brief"
    assert [part["type"] for part in api.bodies[0]["input"]] == ["image", "text"]
    assert result.text == "a prompt"
    assert result.cost_usd == token_cost("gemini-4-hydrogen", 100, 60)


async def test_lyria_returns_mp3_at_flat_price() -> None:
    api = StubInteractions(
        interaction(output_audio={"type": "audio", "data": b64(b"mp3"), "mime_type": "audio/mpeg"})
    )

    result = await LyriaMusicProvider(api, "lyria-3-clip-preview").compose("calm beat")

    assert result.data == b"mp3"
    assert result.cost_usd == Decimal("0.04")


def veo_request() -> VideoRequest:
    return VideoRequest(
        prompt="escalator",
        duration_seconds=8,
        resolution=Resolution.P1080,
        audio=False,
        first_frame=SELFIE,
    )


async def test_veo_waits_for_operation_and_prices_by_second() -> None:
    done = types.GenerateVideosOperation(
        name="op-1",
        done=True,
        response=types.GenerateVideosResponse(
            generated_videos=[types.GeneratedVideo(video=types.Video(video_bytes=b"veo"))]
        ),
    )
    api = StubOperations(types.GenerateVideosOperation(name="op-1", done=False), done)

    result = await VeoVideoProvider(api, VEO).generate(veo_request())

    config = api.configs[0]
    assert config.aspect_ratio == "9:16"
    assert config.resolution == "1080p"
    assert config.generate_audio is False
    assert result.data == b"veo"
    assert result.cost_usd == Decimal("0.40")


async def test_veo_safety_filtered_result_is_blocked() -> None:
    filtered = types.GenerateVideosOperation(
        name="op-1",
        done=True,
        response=types.GenerateVideosResponse(
            rai_media_filtered_count=1, rai_media_filtered_reasons=["person"]
        ),
    )

    with pytest.raises(ProviderBlockedError):
        await VeoVideoProvider(StubOperations(filtered), VEO).generate(veo_request())


async def test_veo_cannot_extend() -> None:
    with pytest.raises(UnsupportedRequestError):
        await VeoVideoProvider(StubOperations(), VEO).extend("op-1", "more", 4)


def test_safety_message_detection_ignores_unrelated_words() -> None:
    assert is_safety_message("Request blocked: violates usage policies")
    assert not is_safety_message("constraint violated: training quota exceeded")
