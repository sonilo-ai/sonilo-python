from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Protocol, TypeVar
from urllib.parse import quote

from sonilo.errors import SoniloError, TaskFailedError, TaskTimeoutError
from sonilo.types import MusicAudioMedia, MusicResult, MusicTitle, SfxMedia, SfxResult, SfxTask

if TYPE_CHECKING:
    from sonilo._async_client import AsyncSonilo
    from sonilo._client import Sonilo

DEFAULT_POLL_INTERVAL = 2.0
DEFAULT_WAIT_TIMEOUT = 600.0

# Test seams: monkeypatched in tests so polling is instant and deterministic.
_sleep = time.sleep
_async_sleep = asyncio.sleep
_monotonic = time.monotonic


class _PollableResult(Protocol):
    """Structural shape Tasks.get()/wait() need from any parsed result,
    regardless of which endpoint produced it (SFX vs. music)."""

    task_id: str
    status: str
    error: Optional[Dict[str, Any]]
    refunded: Optional[bool]


ResultT = TypeVar("ResultT", bound=_PollableResult)


def _media_from(data: Any) -> Optional[SfxMedia]:
    if not isinstance(data, dict) or "url" not in data:
        return None
    return SfxMedia(
        url=data["url"],
        content_type=data.get("content_type"),
        file_size=data.get("file_size"),
    )


def parse_sfx_result(body: Dict[str, Any]) -> SfxResult:
    """Map a GET /v1/tasks/{id} body to SfxResult; unknown fields are ignored."""
    try:
        return SfxResult(
            task_id=body["task_id"],
            status=body["status"],
            type=body.get("type"),
            audio=_media_from(body.get("audio")),
            video=_media_from(body.get("video")),
            cost=body.get("cost"),
            error=body.get("error"),
            refunded=body.get("refunded"),
        )
    except KeyError as e:
        raise SoniloError(f"Malformed task response: missing {e.args[0]!r}") from e


def _music_audio_from(data: Any) -> Optional[MusicAudioMedia]:
    if not isinstance(data, dict) or "url" not in data:
        return None
    return MusicAudioMedia(
        stream_index=data.get("stream_index", 0),
        url=data["url"],
        content_type=data.get("content_type"),
        file_size=data.get("file_size"),
        sample_rate=data.get("sample_rate"),
        channels=data.get("channels"),
    )


def _music_audio_list_from(data: Any) -> Optional[List[MusicAudioMedia]]:
    if not isinstance(data, list):
        return None
    items = [item for item in (_music_audio_from(entry) for entry in data) if item is not None]
    return items


def _music_title_from(data: Any) -> Optional[MusicTitle]:
    if not isinstance(data, dict):
        return None
    return MusicTitle(
        title=data.get("title"),
        summary=data.get("summary"),
        display_tags=data.get("display_tags"),
    )


def parse_music_result(body: Dict[str, Any]) -> MusicResult:
    """Map a GET /v1/tasks/{id} body for a video-to-music task to
    MusicResult; unknown fields are ignored.

    `audio` is always a list; `vocals`/`mux` are only populated when the
    task was submitted with isolate_vocals=True.
    """
    try:
        return MusicResult(
            task_id=body["task_id"],
            status=body["status"],
            type=body.get("type"),
            audio=_music_audio_list_from(body.get("audio")),
            vocals=_media_from(body.get("vocals")),
            mux=_music_audio_list_from(body.get("mux")),
            title=_music_title_from(body.get("title")),
            duration_seconds=body.get("duration_seconds"),
            cost=body.get("cost"),
            error=body.get("error"),
            refunded=body.get("refunded"),
        )
    except KeyError as e:
        raise SoniloError(f"Malformed task response: missing {e.args[0]!r}") from e


def parse_sfx_task(body: Dict[str, Any]) -> SfxTask:
    """Map a submission ack to SfxTask."""
    try:
        return SfxTask(task_id=body["task_id"], status=body.get("status", "processing"))
    except KeyError as e:
        raise SoniloError(f"Malformed task response: missing {e.args[0]!r}") from e


def _raise_if_failed(result: _PollableResult) -> None:
    if result.status == "failed":
        error = result.error if isinstance(result.error, dict) else {}
        message = error.get("message") or "Generation failed"
        raise TaskFailedError(
            f"Task {result.task_id} failed: {message}",
            code=error.get("code"),
            task_id=result.task_id,
            refunded=result.refunded,
        )


def _validate_wait_args(poll_interval: float, timeout: float) -> None:
    if poll_interval < 0:
        raise SoniloError(f"poll_interval must be >= 0, got {poll_interval}")
    if timeout < 0:
        raise SoniloError(f"timeout must be >= 0, got {timeout}")


def _timeout_error(task_id: str, timeout: float) -> TaskTimeoutError:
    return TaskTimeoutError(
        f"Task {task_id} still processing after {timeout:.0f}s; "
        "it may finish later — resume with tasks.wait or tasks.get",
        task_id=task_id,
    )


class Tasks:
    def __init__(self, client: "Sonilo") -> None:
        self._client = client

    def get(
        self,
        task_id: str,
        *,
        parser: Callable[[Dict[str, Any]], ResultT] = parse_sfx_result,  # type: ignore[assignment]
    ) -> ResultT:
        """Fetch current task state. Never raises on a failed status.

        `parser` maps the raw response body to a result type; it defaults to
        the SFX parser for back-compat. Pass `parse_music_result` for
        video-to-music async tasks.
        """
        return parser(self._client._get_json(f"/v1/tasks/{quote(task_id, safe='')}"))

    def wait(
        self,
        task_id: str,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
        parser: Callable[[Dict[str, Any]], ResultT] = parse_sfx_result,  # type: ignore[assignment]
    ) -> ResultT:
        """Poll until the task is terminal; raise on failure or deadline."""
        _validate_wait_args(poll_interval, timeout)
        deadline = _monotonic() + timeout
        while True:
            result = self.get(task_id, parser=parser)
            if result.status == "succeeded":
                return result
            _raise_if_failed(result)
            remaining = deadline - _monotonic()
            if remaining <= 0:
                raise _timeout_error(task_id, timeout)
            _sleep(min(poll_interval, remaining))


class AsyncTasks:
    def __init__(self, client: "AsyncSonilo") -> None:
        self._client = client

    async def get(
        self,
        task_id: str,
        *,
        parser: Callable[[Dict[str, Any]], ResultT] = parse_sfx_result,  # type: ignore[assignment]
    ) -> ResultT:
        """Fetch current task state. Never raises on a failed status.

        `parser` maps the raw response body to a result type; it defaults to
        the SFX parser for back-compat. Pass `parse_music_result` for
        video-to-music async tasks.
        """
        return parser(await self._client._get_json(f"/v1/tasks/{quote(task_id, safe='')}"))

    async def wait(
        self,
        task_id: str,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
        parser: Callable[[Dict[str, Any]], ResultT] = parse_sfx_result,  # type: ignore[assignment]
    ) -> ResultT:
        """Poll until the task is terminal; raise on failure or deadline."""
        _validate_wait_args(poll_interval, timeout)
        deadline = _monotonic() + timeout
        while True:
            result = await self.get(task_id, parser=parser)
            if result.status == "succeeded":
                return result
            _raise_if_failed(result)
            remaining = deadline - _monotonic()
            if remaining <= 0:
                raise _timeout_error(task_id, timeout)
            await _async_sleep(min(poll_interval, remaining))
