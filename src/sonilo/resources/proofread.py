from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from sonilo._requests import build_proofread_parts
from sonilo.resources.tasks import (
    DEFAULT_POLL_INTERVAL,
    DEFAULT_WAIT_TIMEOUT,
    parse_proofread_result,
    parse_sfx_task,
)
from sonilo.types import ProofreadResult, SfxTask

if TYPE_CHECKING:
    from sonilo._async_client import AsyncSonilo
    from sonilo._client import Sonilo

PATH = "/v1/proofread"


class Proofread:
    """Transcribe one video and translate the transcript into editable
    subtitle files. Async only; the result carries a language → `.srt`-URL map
    under `subtitles`.

    This is the step before `client.dubbing`, not a replacement for it:
    proofread returns one `.srt` per language plus the source-language
    transcript, you review or correct the wording, and the corrected files go
    to `client.dubbing` as `subtitles[<language>]` so the dub speaks exactly
    the approved lines. The language codes are the same on both endpoints, so
    a proofread script can go straight into a dub.

    Pass exactly one of `video` / `video_url` (`video_url` must be **https**),
    plus optional `languages` — the target languages to translate into, sent
    as a JSON array. Omit it, or pass `[]`, for the source-language transcript
    alone. `source_language` is an optional hint telling transcription which
    language to expect, which helps on short, noisy or mixed-language audio;
    without it the language is detected, and either way the finished task
    reports what the transcript is in.

    Billing is per second of video multiplied by the number of target
    languages; a transcript-only request counts as one.
    """

    def __init__(self, client: "Sonilo") -> None:
        self._client = client

    def submit(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        languages: Optional[List[str]] = None,
        source_language: Optional[str] = None,
    ) -> SfxTask:
        data, files, opened = build_proofread_parts(
            video, video_url, languages, source_language
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
        languages: Optional[List[str]] = None,
        source_language: Optional[str] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> ProofreadResult:
        task = self.submit(
            video=video, video_url=video_url, languages=languages,
            source_language=source_language,
        )
        return self._client.tasks.wait(
            task.task_id,
            poll_interval=poll_interval,
            timeout=timeout,
            parser=parse_proofread_result,
        )


class AsyncProofread:
    """Async twin of Proofread; same parameters and same result shape."""

    def __init__(self, client: "AsyncSonilo") -> None:
        self._client = client

    async def submit(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        languages: Optional[List[str]] = None,
        source_language: Optional[str] = None,
    ) -> SfxTask:
        data, files, opened = build_proofread_parts(
            video, video_url, languages, source_language
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
        languages: Optional[List[str]] = None,
        source_language: Optional[str] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> ProofreadResult:
        task = await self.submit(
            video=video, video_url=video_url, languages=languages,
            source_language=source_language,
        )
        return await self._client.tasks.wait(
            task.task_id,
            poll_interval=poll_interval,
            timeout=timeout,
            parser=parse_proofread_result,
        )
