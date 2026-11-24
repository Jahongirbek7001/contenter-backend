"""Paid model probe: checks the S1 model risks on real test assets and writes report.csv.

Run from backend/:
    uv run python -m scripts.model_probe.run              # print plan and cost estimate
    uv run python -m scripts.model_probe.run --yes        # run everything
    uv run python -m scripts.model_probe.run --yes --only trend talking

Assets (gitignored): scripts/model_probe/assets/{selfies,trends,scripts}/ (docs/setup-guide.md §4).
Outputs (gitignored): scripts/model_probe/out/<timestamp>/ with media files and report.csv.
"""

import argparse
import asyncio
import csv
import json
import mimetypes
import sys
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.core.config import get_settings
from app.gateway.base import (
    MediaInput,
    MediaResult,
    ProviderBlockedError,
    ProviderError,
    VideoRequest,
)
from app.gateway.factory import GoogleProviders, build_google_providers
from app.gateway.google_clients import SdkInteractions, gemini_client, vertex_client
from app.gateway.providers.gemini import OmniVideoProvider
from app.gateway.providers.veo import SdkVideoOperations, VeoVideoProvider
from app.models.enums import Resolution

PROBE_DIR = Path(__file__).resolve().parent
ASSETS = PROBE_DIR / "assets"
OMNI_MODEL = "gemini-omni-1.2-flash"
VEO_MODEL = "veo-3.1-lite-generate-001"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
EXPERIMENTS = ("selfie_block", "trend", "talking", "series", "upscale")

# Rough list-price estimates (pricing.py) used only for the pre-run summary.
ESTIMATE_USD = {
    "selfie_block": Decimal("0.07"),  # Omni 360p 3 s
    "trend": Decimal("0.50"),  # Hydrogen + Nano Banana 2K + Veo 1080p 8 s + Lyria
    "talking": Decimal("0.71"),  # Omni 720p 10 s
    "series": Decimal("1.40"),  # two 10 s extensions
    "upscale": Decimal("1.04"),  # Omni 1080p 10 s
}

TREND_INSTRUCTIONS = """You write prompts for an AI video pipeline. The input is a selfie and a
short trend description (Uzbek or Russian). Return JSON only, with English values:
{"image_prompt": "...", "video_prompt": "...", "music_prompt": "..."}
- image_prompt: Nano Banana edit of the selfie into the first frame of the trend scene, vertical
  9:16, keep the person's face and identity exactly, photorealistic.
- video_prompt: Veo prompt for an 8 second silent vertical clip starting from that frame:
  subject action, camera movement, lighting, mood. No dialogue, no on-screen text.
- music_prompt: Lyria prompt for an original 30 second instrumental matching the mood."""

SERIES_INSTRUCTIONS = """You continue short spoken advertising videos. Given the first 10 second
line, write the next two lines in the same language, each at most 22 words, so the three lines
form one story ending with a call to action. Return JSON only: {"lines": ["...", "..."]}"""


@dataclass
class Row:
    experiment: str
    item: str
    model: str
    status: str
    seconds: float
    cost_usd: Decimal
    output: str
    note: str = ""


@dataclass
class Probe:
    providers: GoogleProviders
    omni: OmniVideoProvider
    veo: VeoVideoProvider
    out_dir: Path
    rows: list[Row] = field(default_factory=list)
    # First talking clip per language, reused by series and upscale.
    talking_clips: dict[str, tuple[str, str]] = field(default_factory=dict)

    async def record[R: MediaResult](
        self,
        experiment: str,
        item: str,
        model: str,
        call: Awaitable[R],
        filename: str,
    ) -> R | None:
        started = time.monotonic()
        try:
            result = await call
        except ProviderBlockedError as exc:
            self.add(experiment, item, model, "blocked", started, Decimal(0), "", str(exc))
            return None
        except ProviderError as exc:
            self.add(experiment, item, model, "failed", started, Decimal(0), "", str(exc))
            return None
        path = self.out_dir / filename
        path.write_bytes(result.data)
        self.add(experiment, item, model, "ok", started, result.cost_usd, path.name)
        return result

    def add(
        self,
        experiment: str,
        item: str,
        model: str,
        status: str,
        started: float,
        cost: Decimal,
        output: str,
        note: str = "",
    ) -> None:
        row = Row(
            experiment,
            item,
            model,
            status,
            round(time.monotonic() - started, 1),
            cost,
            output,
            note[:300],
        )
        self.rows.append(row)
        print(f"  {status:8} {experiment:13} {item:28} {row.seconds:6.1f}s ${cost:.3f} {note[:80]}")


def load_media(path: Path) -> MediaInput:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return MediaInput(data=path.read_bytes(), mime_type=mime_type)


def list_selfies() -> list[Path]:
    folder = ASSETS / "selfies"
    return sorted(p for p in folder.glob("*") if p.suffix.lower() in IMAGE_SUFFIXES)


def list_trends() -> list[Path]:
    return sorted((ASSETS / "trends").glob("*_desc.txt"))


def list_scripts() -> list[Path]:
    return sorted((ASSETS / "scripts").glob("*.txt"))


def language_of(script: Path) -> str:
    return "ru" if script.stem.lower().startswith("ru") else "uz"


def parse_json(text: str) -> dict[str, object]:
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("expected a JSON object")
    return parsed


def speech_prompt(language: str, line: str) -> str:
    spoken = "Uzbek" if language == "uz" else "Russian"
    return (
        "Vertical selfie-style video. The person from the photo looks into the camera and speaks "
        f"naturally in {spoken} with correct pronunciation and lip sync, saying exactly: «{line}». "
        "Natural hand gestures, soft daylight, no on-screen text, no background music."
    )


async def run_selfie_block(probe: Probe, selfies: list[Path]) -> None:
    for selfie in selfies:
        request = VideoRequest(
            prompt="The person from the photo smiles at the camera and waves. No text.",
            duration_seconds=3,
            resolution=Resolution.P360,
            audio=True,
            first_frame=load_media(selfie),
        )
        await probe.record(
            "selfie_block",
            selfie.name,
            OMNI_MODEL,
            probe.omni.generate(request),
            f"selfie_block_{selfie.stem}.mp4",
        )


async def run_trend(probe: Probe, selfies: list[Path], trends: list[Path]) -> None:
    for index, desc_path in enumerate(trends):
        selfie = load_media(selfies[index % len(selfies)])
        name = desc_path.stem.removesuffix("_desc")
        started = time.monotonic()
        try:
            text = await probe.providers.text.complete(
                TREND_INSTRUCTIONS, desc_path.read_text(encoding="utf-8"), (selfie,)
            )
            prompts = parse_json(text.text)
        except (ProviderError, ValueError) as exc:
            probe.add(
                "trend",
                f"{name}/prompts",
                "gemini-4-hydrogen",
                "failed",
                started,
                Decimal(0),
                "",
                str(exc),
            )
            continue
        (probe.out_dir / f"trend_{name}_prompts.json").write_text(
            json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        probe.add(
            "trend",
            f"{name}/prompts",
            "gemini-4-hydrogen",
            "ok",
            started,
            text.cost_usd,
            f"trend_{name}_prompts.json",
        )

        frame = await probe.record(
            "trend",
            f"{name}/first_frame",
            "gemini-nano-banana-2.1",
            probe.providers.image.compose(str(prompts["image_prompt"]), (selfie,)),
            f"trend_{name}_frame.png",
        )
        if frame is not None:
            request = VideoRequest(
                prompt=str(prompts["video_prompt"]),
                duration_seconds=8,
                resolution=Resolution.P1080,
                audio=False,
                first_frame=MediaInput(data=frame.data, mime_type=frame.mime_type),
            )
            await probe.record(
                "trend",
                f"{name}/veo_1080p",
                VEO_MODEL,
                probe.veo.generate(request),
                f"trend_{name}_veo.mp4",
            )
        await probe.record(
            "trend",
            f"{name}/music",
            "lyria-3-clip-preview",
            probe.providers.music.compose(str(prompts["music_prompt"])),
            f"trend_{name}_music.mp3",
        )


async def run_talking(probe: Probe, selfies: list[Path], scripts: list[Path]) -> None:
    for index, script in enumerate(scripts):
        language = language_of(script)
        line = script.read_text(encoding="utf-8").strip()
        request = VideoRequest(
            prompt=speech_prompt(language, line),
            duration_seconds=10,
            resolution=Resolution.P720,
            audio=True,
            first_frame=load_media(selfies[index % len(selfies)]),
        )
        result = await probe.record(
            "talking",
            script.name,
            OMNI_MODEL,
            probe.omni.generate(request),
            f"talking_{script.stem}.mp4",
        )
        if result is not None and result.continuation_id and language not in probe.talking_clips:
            probe.talking_clips[language] = (result.continuation_id, line)


async def run_series(probe: Probe) -> None:
    for language, (interaction_id, first_line) in probe.talking_clips.items():
        started = time.monotonic()
        try:
            text = await probe.providers.text.complete(SERIES_INSTRUCTIONS, first_line, ())
            raw_lines = parse_json(text.text).get("lines")
            if not isinstance(raw_lines, list):
                raise ValueError("no lines in response")
            lines = [str(line) for line in raw_lines][:2]
        except (ProviderError, ValueError) as exc:
            probe.add(
                "series",
                f"{language}/script",
                "gemini-4-hydrogen",
                "failed",
                started,
                Decimal(0),
                "",
                str(exc),
            )
            continue
        probe.add(
            "series",
            f"{language}/script",
            "gemini-4-hydrogen",
            "ok",
            started,
            text.cost_usd,
            "",
            " | ".join(lines),
        )
        continuation = interaction_id
        for part, line in enumerate(lines, start=2):
            result = await probe.record(
                "series",
                f"{language}/part{part}",
                OMNI_MODEL,
                probe.omni.extend(
                    continuation, "Continue the scene. " + speech_prompt(language, line), 10
                ),
                f"series_{language}_part{part}.mp4",
            )
            if result is None or not result.continuation_id:
                break
            continuation = result.continuation_id


async def run_upscale(probe: Probe) -> None:
    for language, (interaction_id, _) in list(probe.talking_clips.items())[:1]:
        await probe.record(
            "upscale",
            f"{language}/720p->1080p",
            OMNI_MODEL,
            probe.omni.upscale(interaction_id, Resolution.P1080),
            f"upscale_{language}_1080p.mp4",
        )


def plan_counts(
    selected: set[str], selfies: list[Path], trends: list[Path], scripts: list[Path]
) -> dict[str, int]:
    talking = "talking" in selected
    counts = {
        "selfie_block": len(selfies),
        "trend": len(trends),
        "talking": len(scripts),
        # Series and upscale build on the talking clips of the same run.
        "series": len({language_of(s) for s in scripts}) if talking else 0,
        "upscale": 1 if talking and scripts else 0,
    }
    return {name: counts[name] for name in EXPERIMENTS if name in selected}


def write_report(probe: Probe) -> Path:
    path = probe.out_dir / "report.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["experiment", "item", "model", "status", "seconds", "cost_usd", "output", "note"]
        )
        for row in probe.rows:
            writer.writerow(
                [
                    row.experiment,
                    row.item,
                    row.model,
                    row.status,
                    row.seconds,
                    f"{row.cost_usd:.4f}",
                    row.output,
                    row.note,
                ]
            )
    return path


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--only", nargs="+", choices=EXPERIMENTS, default=list(EXPERIMENTS))
    parser.add_argument("--yes", action="store_true", help="run paid generations")
    args = parser.parse_args()
    selected = set(args.only)

    selfies, trends, scripts = list_selfies(), list_trends(), list_scripts()
    print(f"assets: {len(selfies)} selfies, {len(trends)} trends, {len(scripts)} scripts")
    if not selfies:
        print(f"no selfies in {ASSETS / 'selfies'}")
        return 1
    counts = plan_counts(selected, selfies, trends, scripts)
    total = sum((ESTIMATE_USD[name] * count for name, count in counts.items()), Decimal(0))
    for name, count in counts.items():
        print(f"  {name:13} x{count}  ~${ESTIMATE_USD[name] * count:.2f}")
    print(f"estimated total ~${total:.2f}")
    if not args.yes:
        print("dry run; add --yes to generate")
        return 0

    settings = get_settings()
    out_dir = PROBE_DIR / "out" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True)
    probe = Probe(
        providers=build_google_providers(settings),
        omni=OmniVideoProvider(SdkInteractions(gemini_client(settings)), OMNI_MODEL),
        veo=VeoVideoProvider(SdkVideoOperations(vertex_client(settings)), VEO_MODEL),
        out_dir=out_dir,
    )
    if "selfie_block" in selected:
        await run_selfie_block(probe, selfies)
    if "trend" in selected:
        await run_trend(probe, selfies, trends)
    if "talking" in selected:
        await run_talking(probe, selfies, scripts)
    if "series" in selected:
        await run_series(probe)
    if "upscale" in selected:
        await run_upscale(probe)

    report = write_report(probe)
    spent = sum((row.cost_usd for row in probe.rows), Decimal(0))
    print(f"report: {report}\nspent ~${spent:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
