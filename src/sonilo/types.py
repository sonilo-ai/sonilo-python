from __future__ import annotations

import httpx
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict, Union

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


class TrialQuota(TypedDict):
    """One service's free-trial allowance. `remaining` is already floored at
    0, so it is safe to compare directly."""

    granted: int
    used: int
    remaining: int


class _AccountServicesRequired(TypedDict):
    """The always-present half of AccountServices. Split out because `trial`
    is optional and Required/NotRequired only exist from Python 3.11."""

    available_services: List[str]
    rpm_limit: int
    concurrency_limit: int
    discount_factor: Union[float, str]
    max_upload_size_mb: Optional[int]


class AccountServices(_AccountServicesRequired, total=False):
    """Shape of `GET /v1/account/services` (`client.account.services()`).

    Still a plain dict at runtime — this is a typing aid, not a parsed model.
    """

    trial: Dict[str, TrialQuota]
    """Free-trial allowance keyed by service (`granted` / `used` /
    `remaining`). Present only for self-serve accounts, so always treat it as
    possibly absent; a service missing from the map has no trial allowance
    rather than an unlimited one."""


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
class MusicTitle:
    """The `title` object on a succeeded music task."""

    title: Optional[str] = None
    summary: Optional[str] = None
    display_tags: Optional[List[str]] = None


@dataclass
class MusicAudioMedia:
    """One entry of a music task's `audio` or `mux` array.

    Unlike SfxMedia (used for single-media fields such as `vocals`), array
    entries carry a `stream_index` and — for `audio` specifically —
    `sample_rate`/`channels`, which `mux` entries don't populate.

    `title` is only populated on `audio` entries, and only when
    `variants_num > 1` — each variant is its own creative direction with its
    own title, unlike the single-variant case where `title` only appears at
    the top level of the result.
    """

    stream_index: int
    url: str
    content_type: Optional[str] = None
    file_size: Optional[int] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    title: Optional[MusicTitle] = None


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
    ducked: Optional[List[MusicAudioMedia]] = None
    title: Optional[MusicTitle] = None
    duration_seconds: Optional[float] = None
    cost: Optional[float] = None
    error: Optional[Dict[str, Any]] = None
    refunded: Optional[bool] = None
    variants_num: Optional[int] = None
    """Echoed by GET /v1/tasks/{id} only when > 1. `audio` (and `mux`/`ducked`
    when present) then holds one entry per variant instead of one entry per
    stream of a single generation; `title` stays an alias for `audio[0]`'s
    title."""

    def _media(self, which: str, index: int) -> Union[SfxMedia, MusicAudioMedia]:
        if which == "vocals":
            if self.vocals is None:
                raise SoniloError(f"No vocals on this result (status={self.status})")
            return self.vocals
        if which not in ("audio", "mux", "ducked"):
            raise SoniloError('which must be "audio", "vocals", "mux", or "ducked"')
        items = {"audio": self.audio, "mux": self.mux, "ducked": self.ducked}[which]
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


@dataclass
class VideoResult:
    """State of an async video-to-video task (`tasks.get`) or its final result.

    The output is a re-hosted video (generated music or SFX muxed into the
    source picture); `video` is a single presigned media object — kept as a
    permanent alias for `videos[0]` even when `variants_num > 1` produced
    several scored videos.
    """

    task_id: str
    status: str
    type: Optional[str] = None
    video: Optional[SfxMedia] = None
    videos: List[SfxMedia] = field(default_factory=list)
    """One entry per variant (video-to-video-music only). Empty unless the
    task echoed a `videos` array; `video` above always mirrors `videos[0]`."""
    duration_seconds: Optional[float] = None
    cost: Optional[float] = None
    error: Optional[Dict[str, Any]] = None
    refunded: Optional[bool] = None
    variants_num: Optional[int] = None
    """Echoed by GET /v1/tasks/{id} only when > 1."""

    def _media(self, index: Optional[int] = None) -> SfxMedia:
        if index is not None:
            if not self.videos:
                raise SoniloError(f"No videos on this result (status={self.status})")
            try:
                return self.videos[index]
            except IndexError:
                raise SoniloError(
                    f"No video at index {index} (have {len(self.videos)})"
                ) from None
        if self.video is None:
            raise SoniloError(f"No video on this result (status={self.status})")
        return self.video

    def save(
        self,
        path: Union[str, Path],
        *,
        index: Optional[int] = None,
        timeout: float = DOWNLOAD_TIMEOUT,
    ) -> Path:
        """Download the result video to `path` and return it. The URL is
        presigned — no API key is sent. `index` selects a specific variant
        from `videos`; omit it (the default) to keep downloading `video`,
        unchanged from before `variants_num` existed."""
        media = self._media(index)
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
        index: Optional[int] = None,
        timeout: float = DOWNLOAD_TIMEOUT,
    ) -> Path:
        """Async variant of save()."""
        media = self._media(index)
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as http:
            response = await http.get(media.url)
        if response.status_code >= 400:
            raise SoniloError(f"Download failed: HTTP {response.status_code}")
        p = Path(path)
        p.write_bytes(response.content)
        return p


_SOUND_STEMS = ("music", "music_processed", "sfx")


def _download_to(url: str, path: Union[str, Path], timeout: float) -> Path:
    """Fetch a presigned result URL to `path`. No API key is sent."""
    response = httpx.get(url, follow_redirects=True, timeout=timeout)
    if response.status_code >= 400:
        raise SoniloError(f"Download failed: HTTP {response.status_code}")
    p = Path(path)
    p.write_bytes(response.content)
    return p


async def _adownload_to(url: str, path: Union[str, Path], timeout: float) -> Path:
    """Async variant of _download_to."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as http:
        response = await http.get(url)
    if response.status_code >= 400:
        raise SoniloError(f"Download failed: HTTP {response.status_code}")
    p = Path(path)
    p.write_bytes(response.content)
    return p


@dataclass
class SoundOutput:
    """One entry of a video-to-sound / video-to-video-sound task's `outputs`
    array — one per variant (`variants_num`), sorted by `variant_index`.
    `music_processed` is present only when preserve_speech or ducking
    altered that variant's music bed."""

    variant_index: int
    output_url: str
    output_type: Optional[str] = None
    output_bytes: Optional[int] = None
    music: Optional[SfxMedia] = None
    music_processed: Optional[SfxMedia] = None
    sfx: Optional[SfxMedia] = None


@dataclass
class SoundResult:
    """State of a video-to-sound / video-to-video-sound task (`tasks.get`) or
    its final result (`wait`/`generate`).

    The combined music+SFX result is `output_url` — a bare presigned URL rather
    than a media object, because these endpoints render exactly one artifact
    whose kind is announced by `output_type` ("audio" for /v1/video-to-sound,
    "video" for /v1/video-to-video-sound). `music`, `music_processed` and `sfx`
    are the individual stems; `music_processed` is present only when
    preserve_speech or ducking altered the music bed. All of the above stay
    aliases for `outputs[0]`'s corresponding fields, even when
    `variants_num > 1` produced several variants.
    """

    task_id: str
    status: str
    type: Optional[str] = None
    output_url: Optional[str] = None
    output_type: Optional[str] = None
    output_bytes: Optional[int] = None
    music: Optional[SfxMedia] = None
    music_processed: Optional[SfxMedia] = None
    sfx: Optional[SfxMedia] = None
    outputs: List[SoundOutput] = field(default_factory=list)
    """One entry per variant. Empty unless the task echoed an `outputs`
    array; the top-level fields above always mirror `outputs[0]`."""
    duration_seconds: Optional[float] = None
    cost: Optional[float] = None
    error: Optional[Dict[str, Any]] = None
    refunded: Optional[bool] = None
    variants_num: Optional[int] = None
    """Echoed by GET /v1/tasks/{id} only when > 1."""

    def _output(self, index: Optional[int] = None) -> str:
        if index is not None:
            entry = self._entry_at(index)
            return entry.output_url
        if not self.output_url:
            raise SoniloError(f"No output on this result (status={self.status})")
        return self.output_url

    def _entry_at(self, index: int) -> SoundOutput:
        if not self.outputs:
            raise SoniloError(f"No output on this result (status={self.status})")
        try:
            return self.outputs[index]
        except IndexError:
            raise SoniloError(
                f"No output at index {index} (have {len(self.outputs)})"
            ) from None

    def _stem(self, which: str, index: Optional[int] = None) -> str:
        if which not in _SOUND_STEMS:
            raise SoniloError(
                f"Unknown stem {which!r}; expected one of {', '.join(_SOUND_STEMS)}"
            )
        if index is not None:
            media = getattr(self._entry_at(index), which)
            if media is None:
                raise SoniloError(
                    f"No {which} stem on this result at index {index} (status={self.status})"
                )
            return media.url
        media = getattr(self, which)
        if media is None:
            raise SoniloError(f"No {which} stem on this result (status={self.status})")
        return media.url

    def save(
        self,
        path: Union[str, Path],
        *,
        index: Optional[int] = None,
        timeout: float = DOWNLOAD_TIMEOUT,
    ) -> Path:
        """Download the combined result to `path` and return it. The URL is
        presigned — no API key is sent. `index` selects a specific variant
        from `outputs`; omit it (the default) to keep downloading
        `output_url`, unchanged from before `variants_num` existed."""
        return _download_to(self._output(index), path, timeout)

    async def asave(
        self,
        path: Union[str, Path],
        *,
        index: Optional[int] = None,
        timeout: float = DOWNLOAD_TIMEOUT,
    ) -> Path:
        """Async variant of save()."""
        return await _adownload_to(self._output(index), path, timeout)

    def save_stem(
        self,
        path: Union[str, Path],
        *,
        which: str = "music",
        index: Optional[int] = None,
        timeout: float = DOWNLOAD_TIMEOUT,
    ) -> Path:
        """Download one stem ("music", "music_processed" or "sfx") to `path`.
        `index` selects a specific variant from `outputs`; omit it (the
        default) to keep using the top-level stem fields."""
        return _download_to(self._stem(which, index), path, timeout)

    async def asave_stem(
        self,
        path: Union[str, Path],
        *,
        which: str = "music",
        index: Optional[int] = None,
        timeout: float = DOWNLOAD_TIMEOUT,
    ) -> Path:
        """Async variant of save_stem()."""
        return await _adownload_to(self._stem(which, index), path, timeout)


@dataclass
class DubbingResult:
    """State of a dubbing task (`tasks.get`) or its final result
    (`wait`/`generate`).

    Unlike every other endpoint's result there is no single artifact: a dubbing
    task renders one video per requested language, so `outputs` is a map of
    language code to presigned `.mp4` URL rather than an audio/video media
    object. `save` therefore takes the language to fetch, and `save_all` is the
    convenience for pulling every one of them down at once.
    """

    task_id: str
    status: str
    type: Optional[str] = None
    outputs: Dict[str, str] = field(default_factory=dict)
    duration_seconds: Optional[float] = None
    cost: Optional[float] = None
    error: Optional[Dict[str, Any]] = None
    refunded: Optional[bool] = None

    def _url(self, language: str) -> str:
        if language not in self.outputs:
            available = ", ".join(sorted(self.outputs)) or "none"
            raise SoniloError(
                f"No output for language {language!r} on this result "
                f"(status={self.status}; available: {available})"
            )
        return self.outputs[language]

    def save(
        self,
        language: str,
        path: Union[str, Path],
        *,
        timeout: float = DOWNLOAD_TIMEOUT,
    ) -> Path:
        """Download one language's dubbed video to `path` and return it. The
        URL is presigned — no API key is sent."""
        return _download_to(self._url(language), path, timeout)

    async def asave(
        self,
        language: str,
        path: Union[str, Path],
        *,
        timeout: float = DOWNLOAD_TIMEOUT,
    ) -> Path:
        """Async variant of save()."""
        return await _adownload_to(self._url(language), path, timeout)

    def save_all(
        self,
        directory: Union[str, Path],
        *,
        prefix: str = "dubbed",
        timeout: float = DOWNLOAD_TIMEOUT,
    ) -> Dict[str, Path]:
        """Download every language into `directory` as
        `{prefix}.{language}.mp4`, returning the language → path map. The
        directory is created if it does not exist."""
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        return {
            language: self.save(
                language, target / f"{prefix}.{language}.mp4", timeout=timeout
            )
            for language in sorted(self.outputs)
        }

    async def asave_all(
        self,
        directory: Union[str, Path],
        *,
        prefix: str = "dubbed",
        timeout: float = DOWNLOAD_TIMEOUT,
    ) -> Dict[str, Path]:
        """Async variant of save_all()."""
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        return {
            language: await self.asave(
                language, target / f"{prefix}.{language}.mp4", timeout=timeout
            )
            for language in sorted(self.outputs)
        }
