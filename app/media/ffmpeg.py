"""ffmpeg post-processing. Veo returns ~30 Mbit/s files (22-31 MB for 8 s), far too heavy
for Telegram on mobile data, so every result is re-encoded here."""

import asyncio
import tempfile
from pathlib import Path

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


class FfmpegError(RuntimeError):
    pass


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

        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise FfmpegError(stderr.decode(errors="replace")[-2000:])
        return out_path.read_bytes()
