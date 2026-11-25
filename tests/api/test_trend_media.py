import shutil
import subprocess
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.admin.service import create_admin
from app.gateway.base import MediaResult, ProviderFailedError
from app.main import create_app
from app.media.ffmpeg import make_preview
from app.media.store import LocalMediaStore
from app.models import TrendTemplate
from app.models.enums import AdminRole

PASSWORD = "correct-horse-battery"
SessionFactory = async_sessionmaker[AsyncSession]
TREND_ID = 1  # registon-oqshomi, seeded and active


@dataclass
class FakeMusic:
    fail: bool = False
    calls: int = 0

    async def compose(self, prompt: str) -> MediaResult:
        self.calls += 1
        if self.fail:
            raise ProviderFailedError("lyria down")
        return MediaResult(data=b"ID3-mp3", mime_type="audio/mpeg", cost_usd=Decimal("0.04"))


@dataclass
class Env:
    http: AsyncClient
    music: FakeMusic
    root: Path


@pytest.fixture
async def env(session_factory: SessionFactory, tmp_path: Path) -> AsyncIterator[Env]:
    app = create_app(cors_origins=[])
    music = FakeMusic()
    app.state.session_factory = session_factory
    app.state.media_store = LocalMediaStore(tmp_path)
    app.state.transcode = make_preview
    app.state.music_provider = music
    async with session_factory() as session, session.begin():
        await create_admin(session, "admin@example.uz", PASSWORD, AdminRole.ADMIN)
        await create_admin(session, "support@example.uz", PASSWORD, AdminRole.SUPPORT)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield Env(http, music, tmp_path)
    # Seeded trends outlive a single test; put them back the way the migration left them.
    async with session_factory() as session, session.begin():
        await session.execute(
            update(TrendTemplate).values(preview_storage_key=None, preview_file_id=None)
        )
        await session.execute(
            update(TrendTemplate)
            .where(TrendTemplate.id == TREND_ID)
            .values(music_prompt="tantanali, sharqona torli cholg'u, kinematografik")
        )


async def login(env: Env, role: str = "admin") -> None:
    response = await env.http.post(
        "/admin/auth/login", json={"email": f"{role}@example.uz", "password": PASSWORD}
    )
    assert response.status_code == 200


def sample_video(tmp_path: Path) -> bytes:
    out = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=1080x1920:rate=24:duration=1",
            "-c:v",
            "libx264",
            str(out),
        ],
        check=True,
    )
    return out.read_bytes()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
async def test_preview_upload_is_served_with_range_support(env: Env) -> None:
    await login(env)
    upload = await env.http.post(
        f"/admin/trends/{TREND_ID}/preview",
        files={"video": ("clip.mp4", sample_video(env.root), "video/mp4")},
    )

    assert upload.status_code == 200, upload.text
    body = upload.json()
    assert body["has_preview"] is True
    url = body["preview_url"]
    assert url.startswith(f"/api/trends/{TREND_ID}/preview.mp4?v=")

    full = await env.http.get(url)
    partial = await env.http.get(url, headers={"Range": "bytes=0-99"})
    assert full.status_code == 200
    assert full.headers["content-type"] == "video/mp4"
    assert partial.status_code == 206
    assert len(partial.content) == 100


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
async def test_new_preview_replaces_the_old_file(env: Env) -> None:
    await login(env)
    video = sample_video(env.root)
    first = (
        await env.http.post(
            f"/admin/trends/{TREND_ID}/preview", files={"video": ("a.mp4", video, "video/mp4")}
        )
    ).json()["preview_url"]
    second = (
        await env.http.post(
            f"/admin/trends/{TREND_ID}/preview", files={"video": ("b.mp4", video, "video/mp4")}
        )
    ).json()["preview_url"]

    assert first != second
    assert len(list((env.root / "previews" / str(TREND_ID)).iterdir())) == 1


async def test_preview_rejects_non_video_and_read_only_roles(env: Env) -> None:
    await login(env)
    not_video = await env.http.post(
        f"/admin/trends/{TREND_ID}/preview", files={"video": ("a.txt", b"hello", "text/plain")}
    )
    broken = await env.http.post(
        f"/admin/trends/{TREND_ID}/preview", files={"video": ("a.mp4", b"junk", "video/mp4")}
    )
    assert not_video.status_code == broken.status_code == 422

    await login(env, "support")
    forbidden = await env.http.post(
        f"/admin/trends/{TREND_ID}/preview", files={"video": ("a.mp4", b"x", "video/mp4")}
    )
    assert forbidden.status_code == 403


async def test_missing_preview_is_404(env: Env) -> None:
    assert (await env.http.get(f"/api/trends/{TREND_ID}/preview.mp4")).status_code == 404


async def test_music_track_generation_replaces_active_track(env: Env) -> None:
    await login(env)

    first = await env.http.post(f"/admin/trends/{TREND_ID}/music")
    second = await env.http.post(f"/admin/trends/{TREND_ID}/music")
    tracks = (await env.http.get(f"/admin/trends/{TREND_ID}/music")).json()

    assert first.status_code == second.status_code == 201
    assert [(track["id"], track["is_active"]) for track in tracks] == [
        (second.json()["id"], True),
        (first.json()["id"], False),
    ]
    audio = await env.http.get(tracks[0]["audio_url"])
    assert audio.status_code == 200
    assert audio.content == b"ID3-mp3"
    assert env.music.calls == 2


async def test_music_needs_a_mood_and_reports_lyria_failure(
    env: Env, session_factory: SessionFactory
) -> None:
    await login(env)
    env.music.fail = True
    failed = await env.http.post(f"/admin/trends/{TREND_ID}/music")
    assert failed.status_code == 502

    async with session_factory() as session, session.begin():
        await session.execute(
            update(TrendTemplate).where(TrendTemplate.id == TREND_ID).values(music_prompt=None)
        )
    no_mood = await env.http.post(f"/admin/trends/{TREND_ID}/music")
    assert no_mood.status_code == 422


async def test_support_can_listen_but_not_generate(env: Env) -> None:
    await login(env, "support")
    assert (await env.http.get(f"/admin/trends/{TREND_ID}/music")).status_code == 200
    assert (await env.http.post(f"/admin/trends/{TREND_ID}/music")).status_code == 403
