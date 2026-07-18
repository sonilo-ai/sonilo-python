from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from sonilo._requests import build_v2v_music_parts
from sonilo.resources.tasks import (
    DEFAULT_POLL_INTERVAL,
    DEFAULT_WAIT_TIMEOUT,
    parse_sfx_task,
    parse_video_result,
)
from sonilo.types import SfxTask, VideoResult

if TYPE_CHECKING:
    from sonilo._async_client import AsyncSonilo
    from sonilo._client import Sonilo

PATH = "/v1/video-to-video-music"


class VideoToVideoMusic:
    def __init__(self, client: "Sonilo") -> None:
        self._client = client

    def submit(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        preserve_speech: Optional[bool] = None,
        isolate_vocals: Optional[bool] = None,
    ) -> SfxTask:
        data, files, opened = build_v2v_music_parts(
            video, video_url, prompt, preserve_speech, isolate_vocals
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
        preserve_speech: Optional[bool] = None,
        isolate_vocals: Optional[bool] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> VideoResult:
        task = self.submit(
            video=video,
            video_url=video_url,
            prompt=prompt,
            preserve_speech=preserve_speech,
            isolate_vocals=isolate_vocals,
        )
        return self._client.tasks.wait(
            task.task_id,
            poll_interval=poll_interval,
            timeout=timeout,
            parser=parse_video_result,
        )


class AsyncVideoToVideoMusic:
    def __init__(self, client: "AsyncSonilo") -> None:
        self._client = client

    async def submit(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        preserve_speech: Optional[bool] = None,
        isolate_vocals: Optional[bool] = None,
    ) -> SfxTask:
        data, files, opened = build_v2v_music_parts(
            video, video_url, prompt, preserve_speech, isolate_vocals
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
        preserve_speech: Optional[bool] = None,
        isolate_vocals: Optional[bool] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> VideoResult:
        task = await self.submit(
            video=video,
            video_url=video_url,
            prompt=prompt,
            preserve_speech=preserve_speech,
            isolate_vocals=isolate_vocals,
        )
        return await self._client.tasks.wait(
            task.task_id,
            poll_interval=poll_interval,
            timeout=timeout,
            parser=parse_video_result,
        )
