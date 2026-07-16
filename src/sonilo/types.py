from __future__ import annotations

import httpx
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

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
    # video-to-sfx now returns audio only; `video` is kept for backward
    # compatibility but is no longer populated by the API.
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


@dataclass
class MusicAudioMedia:
    """One entry of a music task's `audio` or `mux` array.

    Unlike SfxMedia (used for single-media fields such as `vocals`), array
    entries carry a `stream_index` and — for `audio` specifically —
    `sample_rate`/`channels`, which `mux` entries don't populate.
    """

    stream_index: int
    url: str
    content_type: Optional[str] = None
    file_size: Optional[int] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None


@dataclass
class MusicTitle:
    """The `title` object on a succeeded music task."""

    title: Optional[str] = None
    summary: Optional[str] = None
    display_tags: Optional[List[str]] = None


@dataclass
class MusicResult:
    """State of an async video-to-music task (`tasks.get`) or its final
    result (`tasks.wait` / `video_to_music.generate_async`).

    `audio` is always a list for async video-to-music. `vocals` (a single
    file) and `mux` (a list) are only populated when the task was submitted
    with `isolate_vocals=True`.
    """

    task_id: str
    status: str
    type: Optional[str] = None
    audio: Optional[List[MusicAudioMedia]] = None
    vocals: Optional[SfxMedia] = None
    mux: Optional[List[MusicAudioMedia]] = None
    title: Optional[MusicTitle] = None
    duration_seconds: Optional[float] = None
    cost: Optional[float] = None
    error: Optional[Dict[str, Any]] = None
    refunded: Optional[bool] = None

    def _media(self, which: str, index: int) -> Union[SfxMedia, MusicAudioMedia]:
        if which == "vocals":
            if self.vocals is None:
                raise SoniloError(f"No vocals on this result (status={self.status})")
            return self.vocals
        if which not in ("audio", "mux"):
            raise SoniloError('which must be "audio", "vocals", or "mux"')
        items = self.audio if which == "audio" else self.mux
        if not items:
            raise SoniloError(f"No {which} on this result (status={self.status})")
        try:
            return items[index]
        except IndexError:
            raise SoniloError(
                f"No {which} track at index {index} (have {len(items)})"
            ) from None

    def save(
        self,
        path: Union[str, Path],
        *,
        which: str = "audio",
        index: int = 0,
        timeout: float = DOWNLOAD_TIMEOUT,
    ) -> Path:
        """Download a track (`which="audio"|"vocals"|"mux"`, `index` selects
        within `audio`/`mux`) to `path` and return it.

        The URL is presigned — no API key is sent.
        """
        media = self._media(which, index)
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
        index: int = 0,
        timeout: float = DOWNLOAD_TIMEOUT,
    ) -> Path:
        """Async variant of save()."""
        media = self._media(which, index)
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as http:
            response = await http.get(media.url)
        if response.status_code >= 400:
            raise SoniloError(f"Download failed: HTTP {response.status_code}")
        p = Path(path)
        p.write_bytes(response.content)
        return p
