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
        prompt_influence: Optional[float] = None,
    ) -> Iterator[StreamEvent]:
        """`prompt_influence` (0-1, API default 0.5) sets how strongly the
        generated music follows the prompt: lower values let the video lead;
        higher values follow the prompt more literally. Free of charge, and
        valid here on the streaming path as well as on submit()."""
        data, files, opened = build_v2m_parts(
            video, video_url, prompt, segments, prompt_influence=prompt_influence
        )
        close_after = files["video"][1] if files is not None and opened else None
        return self._client._stream_events(PATH, data=data, files=files, close_after=close_after)

    def generate(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        segments: Optional[List[Segment]] = None,
        prompt_influence: Optional[float] = None,
    ) -> Track:
        return collect_track(
            self.stream(
                video=video,
                video_url=video_url,
                prompt=prompt,
                segments=segments,
                prompt_influence=prompt_influence,
            )
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
        preserve_speech: Optional[bool] = None,
        output_format: Optional[str] = None,
        ducking: Optional[bool] = None,
        variants_num: Optional[int] = None,
        prompt_influence: Optional[float] = None,
    ) -> SfxTask:
        """Submit an async video-to-music task and return its ack.

        isolate_vocals/preserve_speech/ducking/output_format="wav"/
        variants_num>1 require mode="async" (auto-selected if `mode` is
        omitted); passing an explicit non-async mode alongside any of them
        raises a SoniloError before any request is made. Poll with
        `client.tasks.wait(task_id, parser=sonilo.resources.tasks.parse_music_result)`
        or use `generate_async()` to submit and wait in one call.

        `variants_num` (1-10, default 1) generates that many distinct music
        variants in one request; the result's `audio` gets one entry per
        variant. Cost scales linearly, and values above 1 are never covered
        by the free trial.

        `prompt_influence` (0-1, API default 0.5) sets how strongly the
        generated music follows the prompt: lower values let the video lead;
        higher values follow the prompt more literally. Free of charge and
        not async-only — stream()/generate() take it too. Out-of-range
        values are rejected by the API with a 422.
        """
        data, files, opened = build_v2m_async_parts(
            video, video_url, prompt, segments, mode, isolate_vocals,
            preserve_speech=preserve_speech,
            output_format=output_format,
            ducking=ducking,
            variants_num=variants_num,
            prompt_influence=prompt_influence,
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
        preserve_speech: Optional[bool] = None,
        output_format: Optional[str] = None,
        ducking: Optional[bool] = None,
        variants_num: Optional[int] = None,
        prompt_influence: Optional[float] = None,
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
            preserve_speech=preserve_speech,
            output_format=output_format,
            ducking=ducking,
            variants_num=variants_num,
            prompt_influence=prompt_influence,
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
        prompt_influence: Optional[float] = None,
    ) -> AsyncIterator[StreamEvent]:
        """`prompt_influence` (0-1, API default 0.5) sets how strongly the
        generated music follows the prompt: lower values let the video lead;
        higher values follow the prompt more literally. Free of charge, and
        valid here on the streaming path as well as on submit()."""
        data, files, opened = build_v2m_parts(
            video, video_url, prompt, segments, prompt_influence=prompt_influence
        )
        close_after = files["video"][1] if files is not None and opened else None
        return self._client._stream_events(PATH, data=data, files=files, close_after=close_after)

    async def generate(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        segments: Optional[List[Segment]] = None,
        prompt_influence: Optional[float] = None,
    ) -> Track:
        return await acollect_track(
            self.stream(
                video=video,
                video_url=video_url,
                prompt=prompt,
                segments=segments,
                prompt_influence=prompt_influence,
            )
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
        preserve_speech: Optional[bool] = None,
        output_format: Optional[str] = None,
        ducking: Optional[bool] = None,
        variants_num: Optional[int] = None,
        prompt_influence: Optional[float] = None,
    ) -> SfxTask:
        """Submit an async video-to-music task and return its ack.

        isolate_vocals/preserve_speech/ducking/output_format="wav"/
        variants_num>1 require mode="async" (auto-selected if `mode` is
        omitted); passing an explicit non-async mode alongside any of them
        raises a SoniloError before any request is made.

        `prompt_influence` (0-1, API default 0.5) sets how strongly the
        generated music follows the prompt: lower values let the video lead;
        higher values follow the prompt more literally. Free of charge and
        not async-only — stream()/generate() take it too.
        """
        data, files, opened = build_v2m_async_parts(
            video, video_url, prompt, segments, mode, isolate_vocals,
            preserve_speech=preserve_speech,
            output_format=output_format,
            ducking=ducking,
            variants_num=variants_num,
            prompt_influence=prompt_influence,
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
        preserve_speech: Optional[bool] = None,
        output_format: Optional[str] = None,
        ducking: Optional[bool] = None,
        variants_num: Optional[int] = None,
        prompt_influence: Optional[float] = None,
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
            preserve_speech=preserve_speech,
            output_format=output_format,
            ducking=ducking,
            variants_num=variants_num,
            prompt_influence=prompt_influence,
        )
        return await self._client.tasks.wait(
            task.task_id,
            poll_interval=poll_interval,
            timeout=timeout,
            parser=parse_music_result,
        )
