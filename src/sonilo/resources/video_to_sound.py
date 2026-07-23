from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from sonilo._requests import build_v2s_parts
from sonilo.resources.tasks import (
    DEFAULT_POLL_INTERVAL,
    DEFAULT_WAIT_TIMEOUT,
    parse_sfx_task,
    parse_sound_result,
)
from sonilo.types import SfxSegment, SfxTask, SoundResult

if TYPE_CHECKING:
    from sonilo._async_client import AsyncSonilo
    from sonilo._client import Sonilo

PATH = "/v1/video-to-sound"


class VideoToSound:
    def __init__(self, client: "Sonilo") -> None:
        self._client = client

    def submit(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        music_prompt: Optional[str] = None,
        sfx_prompt: Optional[str] = None,
        segments: Optional[List[SfxSegment]] = None,
        preserve_speech: Optional[bool] = None,
        ducking: Optional[bool] = None,
    ) -> SfxTask:
        data, files, opened = build_v2s_parts(
            video, video_url, music_prompt, sfx_prompt, segments,
            preserve_speech, ducking,
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
        music_prompt: Optional[str] = None,
        sfx_prompt: Optional[str] = None,
        segments: Optional[List[SfxSegment]] = None,
        preserve_speech: Optional[bool] = None,
        ducking: Optional[bool] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> SoundResult:
        task = self.submit(
            video=video,
            video_url=video_url,
            music_prompt=music_prompt,
            sfx_prompt=sfx_prompt,
            segments=segments,
            preserve_speech=preserve_speech,
            ducking=ducking,
        )
        return self._client.tasks.wait(
            task.task_id,
            poll_interval=poll_interval,
            timeout=timeout,
            parser=parse_sound_result,
        )


class AsyncVideoToSound:
    def __init__(self, client: "AsyncSonilo") -> None:
        self._client = client

    async def submit(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        music_prompt: Optional[str] = None,
        sfx_prompt: Optional[str] = None,
        segments: Optional[List[SfxSegment]] = None,
        preserve_speech: Optional[bool] = None,
        ducking: Optional[bool] = None,
    ) -> SfxTask:
        data, files, opened = build_v2s_parts(
            video, video_url, music_prompt, sfx_prompt, segments,
            preserve_speech, ducking,
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
        music_prompt: Optional[str] = None,
        sfx_prompt: Optional[str] = None,
        segments: Optional[List[SfxSegment]] = None,
        preserve_speech: Optional[bool] = None,
        ducking: Optional[bool] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> SoundResult:
        task = await self.submit(
            video=video,
            video_url=video_url,
            music_prompt=music_prompt,
            sfx_prompt=sfx_prompt,
            segments=segments,
            preserve_speech=preserve_speech,
            ducking=ducking,
        )
        return await self._client.tasks.wait(
            task.task_id,
            poll_interval=poll_interval,
            timeout=timeout,
            parser=parse_sound_result,
        )
