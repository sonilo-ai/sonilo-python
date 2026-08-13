from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from sonilo._requests import build_ducking_parts
from sonilo.resources.tasks import (
    DEFAULT_POLL_INTERVAL,
    DEFAULT_WAIT_TIMEOUT,
    parse_sfx_task,
    parse_sound_result,
)
from sonilo.types import SfxTask, SoundResult

if TYPE_CHECKING:
    from sonilo._async_client import AsyncSonilo
    from sonilo._client import Sonilo

PATH = "/v1/audio-ducking"


class AudioDucking:
    """Duck an existing music bed under a voice track. Async only (202 + poll).

    Both inputs are user-supplied — nothing is generated here. The voice may
    be audio OR a video: the backend extracts a video's audio track, ducks the
    music under it, and re-muxes the ducked mix back into a new video (the
    result's ``output_type`` announces which came back — "audio" for a .wav,
    "video" for a .mp4). The music must be audio — the backend never probes it
    for a video stream, so a video there would be silently mishandled.

    The result reuses ``SoundResult``: audio-ducking returns the same flat
    ``output_url``/``output_type``/``output_bytes`` envelope as
    /v1/video-to-sound, just with no stems and no ``outputs`` variants.
    """

    def __init__(self, client: "Sonilo") -> None:
        self._client = client

    def submit(
        self,
        *,
        voice: Any = None,
        voice_url: Optional[str] = None,
        music: Any = None,
        music_url: Optional[str] = None,
    ) -> SfxTask:
        data, files, close_after = build_ducking_parts(voice, voice_url, music, music_url)
        return parse_sfx_task(
            self._client._post_json(PATH, data=data, files=files, close_after=close_after)
        )

    def generate(
        self,
        *,
        voice: Any = None,
        voice_url: Optional[str] = None,
        music: Any = None,
        music_url: Optional[str] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> SoundResult:
        task = self.submit(
            voice=voice, voice_url=voice_url, music=music, music_url=music_url
        )
        return self._client.tasks.wait(
            task.task_id,
            poll_interval=poll_interval,
            timeout=timeout,
            parser=parse_sound_result,
        )


class AsyncAudioDucking:
    def __init__(self, client: "AsyncSonilo") -> None:
        self._client = client

    async def submit(
        self,
        *,
        voice: Any = None,
        voice_url: Optional[str] = None,
        music: Any = None,
        music_url: Optional[str] = None,
    ) -> SfxTask:
        data, files, close_after = build_ducking_parts(voice, voice_url, music, music_url)
        return parse_sfx_task(
            await self._client._post_json(
                PATH, data=data, files=files, close_after=close_after
            )
        )

    async def generate(
        self,
        *,
        voice: Any = None,
        voice_url: Optional[str] = None,
        music: Any = None,
        music_url: Optional[str] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> SoundResult:
        task = await self.submit(
            voice=voice, voice_url=voice_url, music=music, music_url=music_url
        )
        return await self._client.tasks.wait(
            task.task_id,
            poll_interval=poll_interval,
            timeout=timeout,
            parser=parse_sound_result,
        )
