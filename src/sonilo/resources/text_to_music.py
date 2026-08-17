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
        variants_num: Optional[int] = None,
        stems: Optional[bool] = None,
    ) -> SfxTask:
        """Submit an async text-to-music task; poll with
        `client.tasks.wait(task_id, parser=sonilo.resources.tasks.parse_music_result)`.
        Required for output_format="wav" and for variants_num > 1.
        `stream()`/`generate()` remain the streaming path.

        `variants_num` (1-10, default 1) generates that many distinct music
        variants in one request; the result's `audio` gets one entry per
        variant. Cost scales linearly, and values above 1 are never covered
        by the free trial.

        `stems=True` (free of charge) also splits the generated music into
        drums/bass/vocals/other — the result gains a `stems` list (looked up
        by `stream_index`, never position) and possibly a `stems_error`.
        Separation runs after generation and typically adds 2-6 minutes,
        giving up after 30; when polling yourself, pass tasks.wait() a
        `timeout` well above its 600-second default (2400 covers the ceiling).
        """
        data = build_t2m_async_data(
            prompt, duration, segments, mode, output_format, variants_num, stems
        )
        return parse_sfx_task(self._client._post_json(PATH, data=data))

    def generate_async(
        self,
        *,
        prompt: str,
        duration: int,
        segments: Optional[List[Segment]] = None,
        mode: Optional[str] = None,
        output_format: Optional[str] = None,
        variants_num: Optional[int] = None,
        stems: Optional[bool] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> MusicResult:
        """submit() + tasks.wait(), returning the parsed MusicResult.

        With `stems=True`, pass a `timeout` well above the 600-second default
        (2400 covers the separation service's 30-minute ceiling) — see
        submit().
        """
        task = self.submit(
            prompt=prompt, duration=duration, segments=segments,
            mode=mode, output_format=output_format, variants_num=variants_num,
            stems=stems,
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
        variants_num: Optional[int] = None,
        stems: Optional[bool] = None,
    ) -> SfxTask:
        """Submit an async text-to-music task; poll with
        `client.tasks.wait(task_id, parser=sonilo.resources.tasks.parse_music_result)`.
        Required for output_format="wav" and for variants_num > 1.
        `stream()`/`generate()` remain the streaming path.

        `stems=True` (free) also splits the generated music into
        drums/bass/vocals/other — see the sync TextToMusic.submit().
        """
        data = build_t2m_async_data(
            prompt, duration, segments, mode, output_format, variants_num, stems
        )
        return parse_sfx_task(await self._client._post_json(PATH, data=data))

    async def generate_async(
        self,
        *,
        prompt: str,
        duration: int,
        segments: Optional[List[Segment]] = None,
        mode: Optional[str] = None,
        output_format: Optional[str] = None,
        variants_num: Optional[int] = None,
        stems: Optional[bool] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> MusicResult:
        """submit() + tasks.wait(), returning the parsed MusicResult.

        With `stems=True`, pass a `timeout` well above the 600-second default
        (2400 covers the separation service's 30-minute ceiling).
        """
        task = await self.submit(
            prompt=prompt, duration=duration, segments=segments,
            mode=mode, output_format=output_format, variants_num=variants_num,
            stems=stems,
        )
        return await self._client.tasks.wait(
            task.task_id, poll_interval=poll_interval, timeout=timeout,
            parser=parse_music_result,
        )
