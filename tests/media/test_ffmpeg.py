import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.media.ffmpeg import compose_trend_video
from app.media.store import LocalMediaStore

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
