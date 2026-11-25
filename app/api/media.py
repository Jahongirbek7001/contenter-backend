from pathlib import Path

from fastapi import HTTPException, Request, status
from fastapi.responses import FileResponse

from app.media.store import LocalMediaStore


def preview_url(trend_id: int, storage_key: str | None) -> str | None:
    """Public, cache-busted path of a trend preview (the key changes on every upload)."""
    if storage_key is None:
        return None
    version = Path(storage_key).stem
    return f"/api/trends/{trend_id}/preview.mp4?v={version}"


def file_response(request: Request, key: str, media_type: str, max_age: int) -> FileResponse:
    """FileResponse answers Range requests, which iOS needs to play video and audio."""
    store = request.app.state.media_store
    if not isinstance(store, LocalMediaStore):
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "media store has no local files")
    path = store.local_path(key)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found")
    return FileResponse(
        path, media_type=media_type, headers={"Cache-Control": f"public, max-age={max_age}"}
    )
