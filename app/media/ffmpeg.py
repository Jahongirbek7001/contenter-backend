"""ffmpeg post-processing. Veo returns ~30 Mbit/s files (22-31 MB for 8 s), far too heavy
for Telegram on mobile data, so every result is re-encoded here."""

import asyncio
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.models.enums import Resolution

# H.264 for every phone; CRF with a bitrate cap keeps 8 s of 1080x1920 under ~7 MB.
VIDEO_ARGS = (
    "-c:v",
    "libx264",
    "-preset",
    "medium",
    "-crf",
    "23",
    "-maxrate",
    "6M",
    "-bufsize",
    "12M",
    "-pix_fmt",
    "yuv420p",
)
AUDIO_ARGS = ("-c:a", "aac", "-b:a", "128k")
MUSIC_FADE_SECONDS = 1.0


# Catalog previews autoplay muted in a grid, so they are small, silent and short.
PREVIEW_ARGS = (
    "-vf",
    "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
    "-c:v",
    "libx264",
    "-preset",
    "medium",
    "-crf",
    "28",
    "-maxrate",
    "2M",
    "-bufsize",
    "4M",
    "-pix_fmt",
    "yuv420p",
    "-an",
)
PREVIEW_MAX_SECONDS = 10


class FfmpegError(RuntimeError):
    pass


async def _run(args: list[str], cwd: Path | None = None) -> None:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, cwd=cwd
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise FfmpegError(stderr.decode(errors="replace")[-2000:])


async def make_preview(video: bytes, ffmpeg: str = "ffmpeg") -> bytes:
    """Any uploaded clip -> 720x1280 silent H.264, at most 10 s, ready for streaming."""
    with tempfile.TemporaryDirectory(prefix="contentor-") as workdir:
        root = Path(workdir)
        source = root / "source"
        source.write_bytes(video)
        out_path = root / "preview.mp4"
        await _run(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-t",
                str(PREVIEW_MAX_SECONDS),
                *PREVIEW_ARGS,
                "-movflags",
                "+faststart",
                str(out_path),
            ]
        )
        return out_path.read_bytes()


async def compose_trend_video(
    video: bytes, music: bytes | None, duration_seconds: float, ffmpeg: str = "ffmpeg"
) -> bytes:
    """Re-encode the clip and lay the music under it, trimmed to the clip with a fade-out."""
    with tempfile.TemporaryDirectory(prefix="contentor-") as workdir:
        root = Path(workdir)
        video_path = root / "in.mp4"
        video_path.write_bytes(video)
        out_path = root / "out.mp4"
        args = [ffmpeg, "-y", "-loglevel", "error", "-i", str(video_path)]
        if music is not None:
            music_path = root / "music"
            music_path.write_bytes(music)
            fade_start = max(duration_seconds - MUSIC_FADE_SECONDS, 0)
            args += [
                "-i",
                str(music_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-af",
                f"afade=t=out:st={fade_start}:d={MUSIC_FADE_SECONDS}",
                *AUDIO_ARGS,
                "-t",
                str(duration_seconds),
            ]
        else:
            args += ["-map", "0:v:0", "-an"]
        args += [*VIDEO_ARGS, "-movflags", "+faststart", str(out_path)]
        await _run(args)
        return out_path.read_bytes()


# Spoken videos: Omni output size per resolution, and subtitles/contact burned in with ASS.
FRAME_SIZE = {
    Resolution.P360: (360, 640),
    Resolution.P720: (720, 1280),
    Resolution.P1080: (1080, 1920),
}
SUBTITLE_FONT = "Arial"
MAX_WORDS_PER_CUE = 5
# Bottom margin keeps subtitles above Telegram's and Instagram's caption overlays.
_ASS_FIELDS = (
    "Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
    "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
)
# Colours are &HAABBGGRR. Contact uses BorderStyle 3: an opaque box behind the text.
_ASS_STYLES = (
    f"Style: Sub,{SUBTITLE_FONT},72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
    "-1,0,0,0,100,100,0,0,1,5,0,2,80,80,420,1",
    f"Style: Contact,{SUBTITLE_FONT},50,&H00FFFFFF,&H000000FF,&H8C000000,&H8C000000,"
    "-1,0,0,0,100,100,0,0,3,16,0,8,80,80,150,1",
)
ASS_HEADER = "\n".join(
    [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        f"Format: {_ASS_FIELDS}",
        *_ASS_STYLES,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        "",
    ]
)
_DURATION = re.compile(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class Segment:
    """One clip from the model and the script lines spoken in it, in order."""

    video: bytes
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def build_cues(timed_lines: Sequence[tuple[str, float, float]]) -> list[Cue]:
    """Splits each line into short chunks timed by character count within the line's slot.
    Without a speech aligner this is approximate, so each slot is trimmed at both ends."""
    cues: list[Cue] = []
    for line, start, end in timed_lines:
        words = line.split()
        if not words:
            continue
        count = -(-len(words) // MAX_WORDS_PER_CUE)
        size = -(-len(words) // count)
        chunks = [" ".join(words[i : i + size]) for i in range(0, len(words), size)]
        slot_start, slot_end = start + 0.2, max(end - 0.3, start + 0.4)
        total = sum(len(chunk) for chunk in chunks)
        cursor = slot_start
        for chunk in chunks:
            length = (slot_end - slot_start) * len(chunk) / total
            cues.append(Cue(round(cursor, 2), round(cursor + length, 2), chunk))
            cursor += length
    return cues


def _ass_time(seconds: float) -> str:
    centis = round(seconds * 100)
    hours, rest = divmod(centis, 360_000)
    minutes, rest = divmod(rest, 6_000)
    secs, centis = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _ass_text(text: str) -> str:
    return " ".join(text.replace("\\", "/").replace("{", "(").replace("}", ")").split())


def ass_document(cues: Sequence[Cue], contact: str | None, duration: float) -> str:
    events = [
        f"Dialogue: 0,{_ass_time(c.start)},{_ass_time(c.end)},Sub,,0,0,0,,{_ass_text(c.text)}"
        for c in cues
    ]
    if contact:
        events.append(
            f"Dialogue: 1,{_ass_time(0)},{_ass_time(duration)},Contact,,0,0,0,,{_ass_text(contact)}"
        )
    return ASS_HEADER + "\n".join(events) + "\n"


async def media_duration(path: Path, ffmpeg: str) -> float:
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-hide_banner",
        "-i",
        str(path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    match = _DURATION.search(stderr.decode(errors="replace"))
    if match is None:
        raise FfmpegError(f"no duration for {path.name}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


async def compose_spoken_video(
    segments: Sequence[Segment],
    resolution: Resolution,
    subtitles: bool,
    contact: str | None,
    ffmpeg: str = "ffmpeg",
) -> bytes:
    """Joins the clips (one, or several when a series fell back to separate parts),
    burns in subtitles and the contact line, and re-encodes for Telegram."""
    if not segments:
        raise ValueError("no segments")
    width, height = FRAME_SIZE[resolution]
    with tempfile.TemporaryDirectory(prefix="contentor-") as workdir:
        root = Path(workdir)
        inputs: list[str] = []
        timed_lines: list[tuple[str, float, float]] = []
        offset = 0.0
        for index, segment in enumerate(segments):
            path = root / f"part{index}.mp4"
            path.write_bytes(segment.video)
            inputs += ["-i", path.name]
            duration = await media_duration(path, ffmpeg)
            slot = duration / max(len(segment.lines), 1)
            for number, line in enumerate(segment.lines):
                timed_lines.append((line, offset + number * slot, offset + (number + 1) * slot))
            offset += duration

        chains = [
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps=24[v{i}];[{i}:a]aresample=48000[a{i}]"
            for i in range(len(segments))
        ]
        joined = "".join(f"[v{i}][a{i}]" for i in range(len(segments)))
        graph = ";".join(chains) + f";{joined}concat=n={len(segments)}:v=1:a=1[vc][aout]"
        cues = build_cues(timed_lines) if subtitles else []
        if cues or contact:
            (root / "overlay.ass").write_text(ass_document(cues, contact, offset), encoding="utf-8")
            graph += ";[vc]ass=overlay.ass[vout]"
        else:
            graph += ";[vc]null[vout]"
        await _run(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                *inputs,
                "-filter_complex",
                graph,
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                *VIDEO_ARGS,
                *AUDIO_ARGS,
                "-movflags",
                "+faststart",
                "out.mp4",
            ],
            cwd=root,
        )
        return (root / "out.mp4").read_bytes()
