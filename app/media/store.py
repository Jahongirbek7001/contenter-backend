"""Where user photos and generated assets live between the bot, API and worker.

Local disk for now; the production worker runs on another host, so this becomes object
storage behind the same protocol.
"""

from pathlib import Path, PurePosixPath
from typing import Protocol


class MediaStore(Protocol):
    async def save(self, key: str, data: bytes) -> None: ...

    async def load(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...


class LocalMediaStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def save(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def load(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    async def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def local_path(self, key: str) -> Path:
        """For range-capable file responses (iOS needs ranges to play video). Object
        storage will hand out URLs instead."""
        return self._path(key)

    def _path(self, key: str) -> Path:
        relative = PurePosixPath(key)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError(f"invalid media key: {key!r}")
        return self._root.joinpath(*relative.parts)
