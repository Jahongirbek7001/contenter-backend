"""Known model capabilities (docs/research-log.md). Re-checked by scripts/model_probe."""

from app.gateway.base import VideoCapabilities
from app.models.enums import Resolution

VEO_3_1_LITE = VideoCapabilities(
    durations_seconds=frozenset({4, 6, 8}),
    resolutions=frozenset({Resolution.P720, Resolution.P1080}),
    audio=False,  # we use the silent tier; music is added by ffmpeg
    max_reference_images=0,
    first_frame=True,
    extend=False,
    upscale=False,
)

OMNI_1_2_FLASH = VideoCapabilities(
    durations_seconds=frozenset(range(3, 16)),
    resolutions=frozenset({Resolution.P360, Resolution.P720, Resolution.P1080}),
    audio=True,
    max_reference_images=6,
    first_frame=True,
    extend=True,
    upscale=True,
)
