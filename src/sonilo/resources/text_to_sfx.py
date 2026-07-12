from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sonilo._requests import build_sfx_t2s_data
from sonilo.resources.tasks import DEFAULT_POLL_INTERVAL, DEFAULT_WAIT_TIMEOUT, parse_sfx_task
from sonilo.types import SfxResult, SfxTask

if TYPE_CHECKING:
    from sonilo._async_client import AsyncSonilo
    from sonilo._client import Sonilo

PATH = "/v1/text-to-sfx"


class TextToSfx:
    def __init__(self, client: "Sonilo") -> None:
        self._client = client

    def submit(
        self, *, prompt: str, duration: int, audio_format: Optional[str] = None
    ) -> SfxTask:
        data = build_sfx_t2s_data(prompt, duration, audio_format)
        return parse_sfx_task(self._client._post_json(PATH, data=data))

    def generate(
        self,
        *,
        prompt: str,
        duration: int,
        audio_format: Optional[str] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> SfxResult:
        task = self.submit(prompt=prompt, duration=duration, audio_format=audio_format)
        return self._client.tasks.wait(
            task.task_id, poll_interval=poll_interval, timeout=timeout
        )


class AsyncTextToSfx:
    def __init__(self, client: "AsyncSonilo") -> None:
        self._client = client

    async def submit(
        self, *, prompt: str, duration: int, audio_format: Optional[str] = None
    ) -> SfxTask:
        data = build_sfx_t2s_data(prompt, duration, audio_format)
        return parse_sfx_task(await self._client._post_json(PATH, data=data))

    async def generate(
        self,
        *,
        prompt: str,
        duration: int,
        audio_format: Optional[str] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> SfxResult:
        task = await self.submit(prompt=prompt, duration=duration, audio_format=audio_format)
        return await self._client.tasks.wait(
            task.task_id, poll_interval=poll_interval, timeout=timeout
        )
