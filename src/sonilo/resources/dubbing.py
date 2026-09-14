from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from sonilo._requests import build_dubbing_parts
from sonilo.resources.tasks import (
    DEFAULT_POLL_INTERVAL,
    DEFAULT_WAIT_TIMEOUT,
    parse_dubbing_result,
    parse_dubbing_task,
)
from sonilo.types import DubbingResult, DubbingTask

if TYPE_CHECKING:
    from sonilo._async_client import AsyncSonilo
    from sonilo._client import Sonilo

PATH = "/v1/dubbing"


class Dubbing:
    """Dub one video into several target languages. Async only; the result
    carries a language → dubbed-video-URL map under `outputs`.

    `ducking` (default off, free) ducks the background music/effects bed
    under the dubbed voice while it speaks; when off the bed is kept at a
    constant level. Every endpoint's `ducking` defaults off, so this one is
    no exception.

    `lipsync` is the one parameter here that defaults **on**: the speaker's
    mouth is re-rendered to match the dubbed speech. Pass `lipsync=False` to
    leave the picture completely untouched instead — the video comes back at
    its original resolution and frame rate rather than re-rendered, and only
    the audio is replaced, so the mouths keep moving to the original language.
    Reach for it on footage with no on-camera speaker, or when preserving the
    exact original picture matters more than matching lip movement. The
    background bed is rebuilt either way, so `ducking` behaves the same.

    `subtitles` maps each target language to the script to speak in it — an
    https URL or a local .srt/.vtt path. These are TARGET-language scripts,
    one per language being dubbed into, not source transcripts. With
    `export_srt=True` each language's delivered audio is force-aligned against
    its script and a re-timed .srt comes back under `DubbingResult.subtitles`,
    keeping the lines verbatim."""

    def __init__(self, client: "Sonilo") -> None:
        self._client = client

    def submit(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        languages: Optional[List[str]] = None,
        ducking: Optional[bool] = None,
        lipsync: Optional[bool] = None,
        subtitles: Optional[Dict[str, Union[str, Path]]] = None,
        export_srt: Optional[bool] = None,
    ) -> DubbingTask:
        data, files, close_after = build_dubbing_parts(
            video, video_url, languages, ducking, lipsync,
            subtitles=subtitles, export_srt=export_srt,
        )
        return parse_dubbing_task(
            self._client._post_json(PATH, data=data, files=files, close_after=close_after)
        )

    def generate(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        languages: Optional[List[str]] = None,
        ducking: Optional[bool] = None,
        lipsync: Optional[bool] = None,
        subtitles: Optional[Dict[str, Union[str, Path]]] = None,
        export_srt: Optional[bool] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> DubbingResult:
        task = self.submit(
            video=video, video_url=video_url, languages=languages,
            ducking=ducking, lipsync=lipsync,
            subtitles=subtitles, export_srt=export_srt,
        )
        return self._client.tasks.wait(
            task.task_id,
            poll_interval=poll_interval,
            timeout=timeout,
            parser=parse_dubbing_result,
        )


class AsyncDubbing:
    def __init__(self, client: "AsyncSonilo") -> None:
        self._client = client

    async def submit(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        languages: Optional[List[str]] = None,
        ducking: Optional[bool] = None,
        lipsync: Optional[bool] = None,
        subtitles: Optional[Dict[str, Union[str, Path]]] = None,
        export_srt: Optional[bool] = None,
    ) -> DubbingTask:
        data, files, close_after = build_dubbing_parts(
            video, video_url, languages, ducking, lipsync,
            subtitles=subtitles, export_srt=export_srt,
        )
        return parse_dubbing_task(
            await self._client._post_json(
                PATH, data=data, files=files, close_after=close_after
            )
        )

    async def generate(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        languages: Optional[List[str]] = None,
        ducking: Optional[bool] = None,
        lipsync: Optional[bool] = None,
        subtitles: Optional[Dict[str, Union[str, Path]]] = None,
        export_srt: Optional[bool] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> DubbingResult:
        task = await self.submit(
            video=video, video_url=video_url, languages=languages,
            ducking=ducking, lipsync=lipsync,
            subtitles=subtitles, export_srt=export_srt,
        )
        return await self._client.tasks.wait(
            task.task_id,
            poll_interval=poll_interval,
            timeout=timeout,
            parser=parse_dubbing_result,
        )
