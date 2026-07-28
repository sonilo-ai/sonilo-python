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
        variants_num: Optional[int] = None,
    ) -> SfxTask:
        """`variants_num` (1-10, default 1) generates that many distinct
        variants in one request; the result's `outputs` gets one entry per
        variant, and the top-level output/stem fields stay aliases for
        `outputs[0]`. Cost scales linearly, and values above 1 are never
        covered by the free trial. This endpoint is always async, so there
        is no mode to auto-select.
        """
        data, files, opened = build_v2s_parts(
            video, video_url, music_prompt, sfx_prompt, segments,
            preserve_speech, ducking, variants_num,
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
        variants_num: Optional[int] = None,
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
            variants_num=variants_num,
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
        variants_num: Optional[int] = None,
    ) -> SfxTask:
        data, files, opened = build_v2s_parts(
            video, video_url, music_prompt, sfx_prompt, segments,
            preserve_speech, ducking, variants_num,
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
        variants_num: Optional[int] = None,
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
            variants_num=variants_num,
        )
        return await self._client.tasks.wait(
            task.task_id,
            poll_interval=poll_interval,
            timeout=timeout,
            parser=parse_sound_result,
        )
