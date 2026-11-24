"""Wires real Google providers. Video routing comes from model_routes; the helper models
(text, image, music) are fixed here until the admin cabinet manages them (S5).
"""

from dataclasses import dataclass

from app.core.config import Settings
from app.gateway.base import ImageProvider, MusicProvider, TextProvider, VideoProvider
from app.gateway.google_clients import SdkInteractions, gemini_client, vertex_client
from app.gateway.providers.gemini import (
    HydrogenTextProvider,
    LyriaMusicProvider,
    NanoBananaImageProvider,
    OmniVideoProvider,
)
from app.gateway.providers.veo import SdkVideoOperations, VeoVideoProvider
from app.gateway.registry import VideoProviderRegistry

HYDROGEN_MODEL = "gemini-4-hydrogen"
NANO_BANANA_MODEL = "gemini-nano-banana-2.1"
LYRIA_MODEL = "lyria-3-clip-preview"


@dataclass(frozen=True)
class GoogleProviders:
    text: TextProvider
    image: ImageProvider
    music: MusicProvider
    videos: VideoProviderRegistry


def build_google_providers(settings: Settings) -> GoogleProviders:
    interactions = SdkInteractions(gemini_client(settings))
    operations = SdkVideoOperations(vertex_client(settings))

    def omni(model: str) -> VideoProvider:
        return OmniVideoProvider(interactions, model)

    def veo(model: str) -> VideoProvider:
        return VeoVideoProvider(operations, model)

    return GoogleProviders(
        text=HydrogenTextProvider(interactions, HYDROGEN_MODEL),
        image=NanoBananaImageProvider(interactions, NANO_BANANA_MODEL),
        music=LyriaMusicProvider(interactions, LYRIA_MODEL),
        videos=VideoProviderRegistry({"gemini": omni, "vertex": veo}),
    )
