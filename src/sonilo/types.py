from __future__ import annotations

import httpx
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union

from sonilo.errors import SoniloError

# httpx defaults to a ~5s timeout, which is far too short for real media
# downloads. Kept independent of sonilo._client to avoid a circular import.
DOWNLOAD_TIMEOUT = 600.0

Segment = Dict[str, Any]
"""{"start": float, "prompt": str, "label": optional str}"""

StreamEvent = Dict[str, Any]
"""One NDJSON event; audio_chunk events carry `data` as decoded bytes."""

SfxSegment = Dict[str, Any]
"""{"start": float, "end": float, "prompt": str} — SFX segments (unlike music
Segment) require `end`, must start at 0, and be contiguous; validated server-side."""


@dataclass
class Track:
    audio: bytes
    title: Optional[str] = None
    cost: Optional[Dict[str, str]] = None

    def save(self, path: Union[str, Path]) -> Path:
        """Write the audio bytes to `path` and return it."""
        p = Path(path)
        p.write_bytes(self.audio)
        return p


@dataclass
class SfxTask:
    """Submission ack for the async SFX endpoints."""

    task_id: str
    status: str


@dataclass
class SfxMedia:
    """A generated file re-hosted on R2 behind a presigned URL."""

    url: str
    content_type: Optional[str] = None
    file_size: Optional[int] = None


@dataclass
class SfxResult:
    """State of an SFX task (`tasks.get`) or its final result (`wait`/`generate`)."""

    task_id: str
    status: str
    type: Optional[str] = None
    audio: Optional[SfxMedia] = None
    video: Optional[SfxMedia] = None
    cost: Optional[float] = None
    error: Optional[Dict[str, Any]] = None
    refunded: Optional[bool] = None

    def _media(self, which: str) -> SfxMedia:
        if which not in ("audio", "video"):
            raise SoniloError('which must be "audio" or "video"')
        media = getattr(self, which)
        if media is None:
            raise SoniloError(f"No {which} on this result (status={self.status})")
        return media

    def save(
        self,
        path: Union[str, Path],
        *,
        which: str = "audio",
        timeout: float = DOWNLOAD_TIMEOUT,
    ) -> Path:
        """Download the audio (or video) to `path` and return it.

        The URL is presigned — no API key is sent.
        """
        media = self._media(which)
        response = httpx.get(media.url, follow_redirects=True, timeout=timeout)
        if response.status_code >= 400:
            raise SoniloError(f"Download failed: HTTP {response.status_code}")
        p = Path(path)
        p.write_bytes(response.content)
        return p

    async def asave(
        self,
        path: Union[str, Path],
        *,
        which: str = "audio",
        timeout: float = DOWNLOAD_TIMEOUT,
    ) -> Path:
        """Async variant of save()."""
        media = self._media(which)
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as http:
            response = await http.get(media.url)
        if response.status_code >= 400:
            raise SoniloError(f"Download failed: HTTP {response.status_code}")
        p = Path(path)
        p.write_bytes(response.content)
        return p
