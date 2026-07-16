from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator, Iterator, List, Optional

from sonilo._requests import build_v2m_async_parts, build_v2m_parts
from sonilo._streaming import acollect_track, collect_track
from sonilo.resources.tasks import (
    DEFAULT_POLL_INTERVAL,
    DEFAULT_WAIT_TIMEOUT,
    parse_music_result,
    parse_sfx_task,
)
from sonilo.types import MusicResult, Segment, SfxTask, StreamEvent, Track

if TYPE_CHECKING:
    from sonilo._async_client import AsyncSonilo
    from sonilo._client import Sonilo

PATH = "/v1/video-to-music"


class VideoToMusic:
    def __init__(self, client: "Sonilo") -> None:
        self._client = client

    def stream(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        segments: Optional[List[Segment]] = None,
    ) -> Iterator[StreamEvent]:
        data, files, opened = build_v2m_parts(video, video_url, prompt, segments)
        close_after = files["video"][1] if files is not None and opened else None
        return self._client._stream_events(PATH, data=data, files=files, close_after=close_after)

    def generate(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        segments: Optional[List[Segment]] = None,
    ) -> Track:
        return collect_track(
            self.stream(video=video, video_url=video_url, prompt=prompt, segments=segments)
        )

    def submit(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        segments: Optional[List[Segment]] = None,
        isolate_vocals: Optional[bool] = None,
        mode: Optional[str] = None,
    ) -> SfxTask:
        """Submit an async video-to-music task and return its ack.

        isolate_vocals=True requires mode="async" (auto-selected if `mode`
        is omitted); passing an explicit non-async mode alongside
        isolate_vocals raises a SoniloError before any request is made. Poll
        with `client.tasks.wait(task_id, parser=sonilo.resources.tasks.parse_music_result)`
        or use `generate_async()` to submit and wait in one call.
        """
        data, files, opened = build_v2m_async_parts(
            video, video_url, prompt, segments, mode, isolate_vocals
        )
        close_after = files["video"][1] if files is not None and opened else None
        return parse_sfx_task(
            self._client._post_json(PATH, data=data, files=files, close_after=close_after)
        )

    def generate_async(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        segments: Optional[List[Segment]] = None,
        isolate_vocals: Optional[bool] = None,
        mode: Optional[str] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> MusicResult:
        """submit() + tasks.wait(), returning the parsed MusicResult."""
        task = self.submit(
            video=video,
            video_url=video_url,
            prompt=prompt,
            segments=segments,
            isolate_vocals=isolate_vocals,
            mode=mode,
        )
        return self._client.tasks.wait(
            task.task_id,
            poll_interval=poll_interval,
            timeout=timeout,
            parser=parse_music_result,
        )


class AsyncVideoToMusic:
    def __init__(self, client: "AsyncSonilo") -> None:
        self._client = client

    def stream(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        segments: Optional[List[Segment]] = None,
    ) -> AsyncIterator[StreamEvent]:
        data, files, opened = build_v2m_parts(video, video_url, prompt, segments)
        close_after = files["video"][1] if files is not None and opened else None
        return self._client._stream_events(PATH, data=data, files=files, close_after=close_after)

    async def generate(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        segments: Optional[List[Segment]] = None,
    ) -> Track:
        return await acollect_track(
            self.stream(video=video, video_url=video_url, prompt=prompt, segments=segments)
        )

    async def submit(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        segments: Optional[List[Segment]] = None,
        isolate_vocals: Optional[bool] = None,
        mode: Optional[str] = None,
    ) -> SfxTask:
        """Submit an async video-to-music task and return its ack.

        isolate_vocals=True requires mode="async" (auto-selected if `mode`
        is omitted); passing an explicit non-async mode alongside
        isolate_vocals raises a SoniloError before any request is made.
        """
        data, files, opened = build_v2m_async_parts(
            video, video_url, prompt, segments, mode, isolate_vocals
        )
        close_after = files["video"][1] if files is not None and opened else None
        return parse_sfx_task(
            await self._client._post_json(
                PATH, data=data, files=files, close_after=close_after
            )
        )

    async def generate_async(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        segments: Optional[List[Segment]] = None,
        isolate_vocals: Optional[bool] = None,
        mode: Optional[str] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> MusicResult:
        """submit() + tasks.wait(), returning the parsed MusicResult."""
        task = await self.submit(
            video=video,
            video_url=video_url,
            prompt=prompt,
            segments=segments,
            isolate_vocals=isolate_vocals,
            mode=mode,
        )
        return await self._client.tasks.wait(
            task.task_id,
            poll_interval=poll_interval,
            timeout=timeout,
            parser=parse_music_result,
        )
