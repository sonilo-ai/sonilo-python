from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from sonilo._requests import build_video_analysis_parts
from sonilo.resources.tasks import (
    DEFAULT_POLL_INTERVAL,
    DEFAULT_WAIT_TIMEOUT,
    parse_sfx_task,
    parse_video_analysis_result,
)
from sonilo.types import SfxTask, VideoAnalysisResult

if TYPE_CHECKING:
    from sonilo._async_client import AsyncSonilo
    from sonilo._client import Sonilo

PATH = "/v1/video-analysis"


class VideoAnalysis:
    """Analyze a video and get back a creative brief for scoring it. Async
    only.

    This endpoint generates nothing — no audio, no video, no file to
    download. The result is a work order: `segments` (a time-aligned section
    plan) and one `prompt` per requested variation, each ready to pass
    straight to video_to_music, video_to_sfx, video_to_sound or their
    video-to-video counterparts.

    `mode` picks the brief. The default, "both", returns the music brief in
    `segments`/`variations` plus a sound-design brief in
    `sfx_segments`/`sfx_prompt` in the same call; "music" or "sfx" returns
    just that one brief. "music" reproduces the pre-`mode` result shape. The
    price is the same for all three.

    The method is `analyze`, not `generate`, for that reason: every other
    resource's `generate` returns something you save, and this one never
    does.
    """

    def __init__(self, client: "Sonilo") -> None:
        self._client = client

    def submit(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        variants_num: Optional[int] = None,
        mode: Optional[str] = None,
    ) -> SfxTask:
        data, files, opened = build_video_analysis_parts(
            video, video_url, prompt, variants_num, mode
        )
        close_after = files["video"][1] if files is not None and opened else None
        return parse_sfx_task(
            self._client._post_json(PATH, data=data, files=files, close_after=close_after)
        )

    def analyze(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        variants_num: Optional[int] = None,
        mode: Optional[str] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> VideoAnalysisResult:
        """Submit and wait for the brief. `mode` defaults to "both" (music
        brief plus sound-design brief); pass "music" or "sfx" for one."""
        task = self.submit(
            video=video, video_url=video_url, prompt=prompt, variants_num=variants_num,
            mode=mode,
        )
        return self._client.tasks.wait(
            task.task_id,
            poll_interval=poll_interval,
            timeout=timeout,
            parser=parse_video_analysis_result,
        )


class AsyncVideoAnalysis:
    """Async twin of VideoAnalysis; same `mode` semantics (default "both")."""

    def __init__(self, client: "AsyncSonilo") -> None:
        self._client = client

    async def submit(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        variants_num: Optional[int] = None,
        mode: Optional[str] = None,
    ) -> SfxTask:
        data, files, opened = build_video_analysis_parts(
            video, video_url, prompt, variants_num, mode
        )
        close_after = files["video"][1] if files is not None and opened else None
        return parse_sfx_task(
            await self._client._post_json(
                PATH, data=data, files=files, close_after=close_after
            )
        )

    async def analyze(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        variants_num: Optional[int] = None,
        mode: Optional[str] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> VideoAnalysisResult:
        """Submit and wait for the brief. `mode` defaults to "both" (music
        brief plus sound-design brief); pass "music" or "sfx" for one."""
        task = await self.submit(
            video=video, video_url=video_url, prompt=prompt, variants_num=variants_num,
            mode=mode,
        )
        return await self._client.tasks.wait(
            task.task_id,
            poll_interval=poll_interval,
            timeout=timeout,
            parser=parse_video_analysis_result,
        )
