"""Paid end-to-end check of the S3 spoken-video chain without the bot or database:
Hydrogen script -> Omni generate -> extend x2 (fallback: separate clip) -> ffmpeg overlay.

Run from backend/:
    uv run python -m scripts.model_probe.spoken                    # plan only
    uv run python -m scripts.model_probe.spoken --yes --language uz --resolution 360p

Outputs (gitignored): scripts/model_probe/out/spoken-<timestamp>/.
"""

import argparse
import asyncio
import json
import time
from collections.abc import Awaitable
from datetime import datetime
from decimal import Decimal

from app.core.config import get_settings
from app.domain.talking.script import continuation_prompt, speech_prompt, write_script
from app.gateway.base import MediaInput, ProviderError, VideoRequest, VideoResult
from app.gateway.factory import build_google_providers
from app.gateway.google_clients import SdkInteractions, gemini_client
from app.gateway.providers.gemini import OmniVideoProvider
from app.media.ffmpeg import Segment, compose_spoken_video
from app.models.enums import Language, Resolution
from scripts.model_probe.run import OMNI_MODEL, PROBE_DIR, list_selfies, load_media

IDEAS = {
    Language.UZ: (
        "Chilonzordagi kiyim do'konimga yangi qishki kurtkalar keldi, "
        "hafta oxirigacha 20% chegirma."
    ),
    Language.RU: (
        "В мой магазин одежды на Чиланзаре пришли новые зимние куртки, "  # noqa: RUF001
        "скидка 20% до выходных."
    ),
}
SALES_STYLE = (
    "Sell the product or service from the idea. Open with a hook about the viewer's problem, "
    "give one or two concrete benefits, and end the last line with a short call to action."
)


async def main(language: Language, resolution: Resolution, out_name: str) -> None:
    settings = get_settings()
    providers = build_google_providers(settings)
    omni = OmniVideoProvider(SdkInteractions(gemini_client(settings)), OMNI_MODEL)
    selfie = load_media(list_selfies()[0])
    out = PROBE_DIR / "out" / out_name
    out.mkdir(parents=True, exist_ok=True)
    cost = Decimal(0)
    log: list[dict[str, object]] = []

    def note(step: str, started: float, **extra: object) -> None:
        row = {"step": step, "seconds": round(time.monotonic() - started, 1), **extra}
        log.append(row)
        print(json.dumps(row, ensure_ascii=False, default=str))

    started = time.monotonic()
    draft = await write_script(
        providers.text,
        style_instructions=SALES_STYLE,
        language=language,
        parts=3,
        selfie=selfie,
        idea=IDEAS[language],
    )
    cost += draft.cost_usd
    if draft.script is None:
        note("script", started, rejected=draft.photo_reason or "idea")
        return
    script = draft.script
    note("script", started, lines=script.lines, bible=script.story_bible, cost=draft.cost_usd)

    async def timed(step: str, call: Awaitable[VideoResult]) -> VideoResult | None:
        nonlocal cost
        began = time.monotonic()
        try:
            result = await call
        except ProviderError as exc:
            note(step, began, error=f"{type(exc).__name__}: {exc}")
            return None
        cost += result.cost_usd
        (out / f"{step}.mp4").write_bytes(result.data)
        note(step, began, cost=result.cost_usd, mb=round(len(result.data) / 1e6, 1))
        return result

    def request(line: str) -> VideoRequest:
        return VideoRequest(
            prompt=speech_prompt(language, line, script.story_bible),
            duration_seconds=10,
            resolution=resolution,
            audio=True,
            first_frame=MediaInput(selfie.data, selfie.mime_type),
        )

    first = await timed("part1", omni.generate(request(script.lines[0])))
    if first is None:
        return
    segments = [Segment(first.data, (script.lines[0],))]
    chain: VideoResult | None = first
    for number, line in enumerate(script.lines[1:], start=2):
        if chain is not None and chain.continuation_id:
            prompt = continuation_prompt(language, line, script.story_bible)
            chain = await timed(f"extend{number}", omni.extend(chain.continuation_id, prompt, 10))
            if chain is not None:
                segments[0] = Segment(chain.data, (*segments[0].lines, line))
                continue
        clip = await timed(f"separate{number}", omni.generate(request(line)))
        if clip is None:
            return
        segments.append(Segment(clip.data, (line,)))

    began = time.monotonic()
    final = await compose_spoken_video(segments, resolution, True, "+998 90 123 45 67")
    (out / "final.mp4").write_bytes(final)
    note("final", began, segments=len(segments), mb=round(len(final) / 1e6, 1))
    (out / "log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"total cost ${cost:.2f} -> {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="spend money and run")
    parser.add_argument("--language", choices=[lang.value for lang in Language], default="uz")
    parser.add_argument("--resolution", choices=[r.value for r in Resolution], default="360p")
    args = parser.parse_args()
    if not args.yes:
        print("Plan: 1 Hydrogen script + 1 Omni generate + 2 extends (~$1 at 360p). Add --yes.")
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        asyncio.run(main(Language(args.language), Resolution(args.resolution), f"spoken-{stamp}"))
