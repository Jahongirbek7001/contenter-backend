import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.media.ffmpeg import (
    Cue,
    Segment,
    ass_document,
    build_cues,
    compose_spoken_video,
    compose_trend_video,
)
from app.media.store import LocalMediaStore
from app.models.enums import Resolution

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _render(tmp_path: Path, name: str, args: list[str]) -> bytes:
    out = tmp_path / name
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args, str(out)], check=True)
    return out.read_bytes()


def _probe(tmp_path: Path, data: bytes) -> dict[str, object]:
    path = tmp_path / "probe.mp4"
    path.write_bytes(data)
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    parsed: dict[str, object] = json.loads(result.stdout)
    return parsed


async def test_compose_adds_music_trimmed_to_the_clip(tmp_path: Path) -> None:
    video = _render(
        tmp_path,
        "clip.mp4",
        ["-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=24:duration=2", "-c:v", "libx264"],
    )
    music = _render(tmp_path, "music.mp3", ["-f", "lavfi", "-i", "sine=duration=5"])

    result = await compose_trend_video(video, music, 2.0)

    info = _probe(tmp_path, result)
    streams = info["streams"]
    assert isinstance(streams, list)
    kinds = {stream["codec_type"]: stream for stream in streams}
    assert (kinds["video"]["width"], kinds["video"]["height"]) == (1080, 1920)
    assert kinds["audio"]["codec_name"] == "aac"
    duration = float(info["format"]["duration"])  # type: ignore[index]
    assert duration == pytest.approx(2.0, abs=0.15)


async def test_compose_without_music_is_silent(tmp_path: Path) -> None:
    video = _render(
        tmp_path,
        "clip.mp4",
        ["-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=24:duration=1", "-c:v", "libx264"],
    )

    result = await compose_trend_video(video, None, 1.0)

    streams = _probe(tmp_path, result)["streams"]
    assert isinstance(streams, list)
    assert [stream["codec_type"] for stream in streams] == ["video"]


async def test_local_store_round_trip_and_rejects_escape(tmp_path: Path) -> None:
    store = LocalMediaStore(tmp_path)
    await store.save("inputs/1.jpg", b"x")
    assert await store.load("inputs/1.jpg") == b"x"
    await store.delete("inputs/1.jpg")
    await store.delete("inputs/1.jpg")
    for bad in ("../secret", "/etc/passwd", ""):
        with pytest.raises(ValueError, match="invalid media key"):
            await store.save(bad, b"x")


def _spoken_clip(tmp_path: Path, name: str, seconds: int, size: str = "720x1280") -> bytes:
    return _render(
        tmp_path,
        name,
        [
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={size}:rate=24:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=duration={seconds}",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
        ],
    )


async def test_spoken_parts_are_joined_with_overlay(tmp_path: Path) -> None:
    first = _spoken_clip(tmp_path, "a.mp4", 2)
    # A fallback part may come back in another size; it is scaled to the ordered resolution.
    second = _spoken_clip(tmp_path, "b.mp4", 1, size="1080x1920")

    result = await compose_spoken_video(
        [
            Segment(first, ("Salom do'stlar, bugun", "yangi kurtkalar")),
            Segment(second, ("Keling!",)),
        ],
        Resolution.P720,
        subtitles=True,
        contact="+998 90 123 45 67 · {bold}",
    )

    info = _probe(tmp_path, result)
    streams = info["streams"]
    assert isinstance(streams, list)
    kinds = {stream["codec_type"]: stream for stream in streams}
    assert (kinds["video"]["width"], kinds["video"]["height"]) == (720, 1280)
    assert kinds["audio"]["codec_name"] == "aac"
    assert float(info["format"]["duration"]) == pytest.approx(3.0, abs=0.2)  # type: ignore[index]


async def test_spoken_video_without_overlay(tmp_path: Path) -> None:
    clip = _spoken_clip(tmp_path, "a.mp4", 1, size="360x640")
    result = await compose_spoken_video([Segment(clip, ("x",))], Resolution.P360, False, None)
    assert result[4:8] == b"ftyp"


def test_cues_split_lines_and_stay_inside_their_slot() -> None:
    cues = build_cues([("bir ikki uch to'rt besh olti yetti", 0.0, 10.0), ("sakkiz", 10.0, 20.0)])

    assert [cue.text for cue in cues] == ["bir ikki uch to'rt", "besh olti yetti", "sakkiz"]
    assert cues[0].start == pytest.approx(0.2)
    assert cues[1].end == pytest.approx(9.7)
    assert cues[1].start == pytest.approx(cues[0].end)
    assert cues[2].start == pytest.approx(10.2)
    assert cues[2].end == pytest.approx(19.7)


def test_ass_escapes_override_braces() -> None:
    document = ass_document([Cue(0, 1, "a {\b1} b")], "tel {x}", 1.0)
    assert "{" not in document.split("[Events]")[1]
