from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator, Iterator, List, Optional

from sonilo._requests import build_t2m_async_data, build_t2m_data
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

PATH = "/v1/text-to-music"


class TextToMusic:
    def __init__(self, client: "Sonilo") -> None:
        self._client = client

    def stream(
        self,
        *,
        prompt: str,
        duration: int,
        segments: Optional[List[Segment]] = None,
    ) -> Iterator[StreamEvent]:
        data = build_t2m_data(prompt, duration, segments)
        return self._client._stream_events(PATH, data=data)

    def generate(
        self,
        *,
        prompt: str,
        duration: int,
        segments: Optional[List[Segment]] = None,
    ) -> Track:
        return collect_track(self.stream(prompt=prompt, duration=duration, segments=segments))

    def submit(
        self,
        *,
        prompt: str,
        duration: int,
        segments: Optional[List[Segment]] = None,
        mode: Optional[str] = None,
        output_format: Optional[str] = None,
    ) -> SfxTask:
        """Submit an async text-to-music task; poll with
        `client.tasks.wait(task_id, parser=sonilo.resources.tasks.parse_music_result)`.
        Required for output_format="wav". `stream()`/`generate()` remain the
        streaming path.
        """
        data = build_t2m_async_data(prompt, duration, segments, mode, output_format)
        return parse_sfx_task(self._client._post_json(PATH, data=data))

    def generate_async(
        self,
        *,
        prompt: str,
        duration: int,
        segments: Optional[List[Segment]] = None,
        mode: Optional[str] = None,
        output_format: Optional[str] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> MusicResult:
        """submit() + tasks.wait(), returning the parsed MusicResult."""
        task = self.submit(
            prompt=prompt, duration=duration, segments=segments,
            mode=mode, output_format=output_format,
        )
        return self._client.tasks.wait(
            task.task_id, poll_interval=poll_interval, timeout=timeout,
            parser=parse_music_result,
        )


class AsyncTextToMusic:
    def __init__(self, client: "AsyncSonilo") -> None:
        self._client = client

    def stream(
        self,
        *,
        prompt: str,
        duration: int,
        segments: Optional[List[Segment]] = None,
    ) -> AsyncIterator[StreamEvent]:
        data = build_t2m_data(prompt, duration, segments)
        return self._client._stream_events(PATH, data=data)

    async def generate(
        self,
        *,
        prompt: str,
        duration: int,
        segments: Optional[List[Segment]] = None,
    ) -> Track:
        return await acollect_track(
            self.stream(prompt=prompt, duration=duration, segments=segments)
        )

    async def submit(
        self,
        *,
        prompt: str,
        duration: int,
        segments: Optional[List[Segment]] = None,
        mode: Optional[str] = None,
        output_format: Optional[str] = None,
    ) -> SfxTask:
        """Submit an async text-to-music task; poll with
        `client.tasks.wait(task_id, parser=sonilo.resources.tasks.parse_music_result)`.
        Required for output_format="wav". `stream()`/`generate()` remain the
        streaming path.
        """
        data = build_t2m_async_data(prompt, duration, segments, mode, output_format)
        return parse_sfx_task(await self._client._post_json(PATH, data=data))

    async def generate_async(
        self,
        *,
        prompt: str,
        duration: int,
        segments: Optional[List[Segment]] = None,
        mode: Optional[str] = None,
        output_format: Optional[str] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> MusicResult:
        """submit() + tasks.wait(), returning the parsed MusicResult."""
        task = await self.submit(
            prompt=prompt, duration=duration, segments=segments,
            mode=mode, output_format=output_format,
        )
        return await self._client.tasks.wait(
            task.task_id, poll_interval=poll_interval, timeout=timeout,
            parser=parse_music_result,
        )
