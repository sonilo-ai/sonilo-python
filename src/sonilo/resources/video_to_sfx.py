from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from sonilo._requests import build_sfx_v2s_parts
from sonilo.resources.tasks import DEFAULT_POLL_INTERVAL, DEFAULT_WAIT_TIMEOUT, parse_sfx_task
from sonilo.types import SfxResult, SfxSegment, SfxTask

if TYPE_CHECKING:
    from sonilo._async_client import AsyncSonilo
    from sonilo._client import Sonilo

PATH = "/v1/video-to-sfx"


class VideoToSfx:
    def __init__(self, client: "Sonilo") -> None:
        self._client = client

    def submit(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        segments: Optional[List[SfxSegment]] = None,
        audio_format: Optional[str] = None,
    ) -> SfxTask:
        data, files, opened = build_sfx_v2s_parts(
            video, video_url, prompt, segments, audio_format
        )
        close_after = files["video"][1] if files is not None and opened else None
        return parse_sfx_task(
            self._client._post_json(PATH, data=data, files=files, close_after=close_after)
        )

    def generate(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        segments: Optional[List[SfxSegment]] = None,
        audio_format: Optional[str] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> SfxResult:
        task = self.submit(
            video=video,
            video_url=video_url,
            prompt=prompt,
            segments=segments,
            audio_format=audio_format,
        )
        return self._client.tasks.wait(
            task.task_id, poll_interval=poll_interval, timeout=timeout
        )


class AsyncVideoToSfx:
    def __init__(self, client: "AsyncSonilo") -> None:
        self._client = client

    async def submit(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        segments: Optional[List[SfxSegment]] = None,
        audio_format: Optional[str] = None,
    ) -> SfxTask:
        data, files, opened = build_sfx_v2s_parts(
            video, video_url, prompt, segments, audio_format
        )
        close_after = files["video"][1] if files is not None and opened else None
        return parse_sfx_task(
            await self._client._post_json(
                PATH, data=data, files=files, close_after=close_after
            )
        )

    async def generate(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        segments: Optional[List[SfxSegment]] = None,
        audio_format: Optional[str] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> SfxResult:
        task = await self.submit(
            video=video,
            video_url=video_url,
            prompt=prompt,
            segments=segments,
            audio_format=audio_format,
        )
        return await self._client.tasks.wait(
            task.task_id, poll_interval=poll_interval, timeout=timeout
        )
