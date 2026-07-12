from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

from sonilo.errors import TaskFailedError, TaskTimeoutError
from sonilo.types import SfxMedia, SfxResult, SfxTask

if TYPE_CHECKING:
    from sonilo._async_client import AsyncSonilo
    from sonilo._client import Sonilo

DEFAULT_POLL_INTERVAL = 2.0
DEFAULT_WAIT_TIMEOUT = 600.0

# Test seams: monkeypatched in tests so polling is instant and deterministic.
_sleep = time.sleep
_async_sleep = asyncio.sleep
_monotonic = time.monotonic


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


def parse_sfx_task(body: Dict[str, Any]) -> SfxTask:
    """Map a submission ack to SfxTask."""
    return SfxTask(task_id=body["task_id"], status=body.get("status", "processing"))


def _raise_if_failed(result: SfxResult) -> None:
    if result.status == "failed":
        error = result.error or {}
        message = error.get("message") or "Generation failed"
        raise TaskFailedError(
            f"Task {result.task_id} failed: {message}",
            code=error.get("code"),
            task_id=result.task_id,
            refunded=result.refunded,
        )


def _timeout_error(task_id: str, timeout: float) -> TaskTimeoutError:
    return TaskTimeoutError(
        f"Task {task_id} still processing after {timeout:.0f}s; "
        "it may finish later — resume with tasks.wait or tasks.get",
        task_id=task_id,
    )


class Tasks:
    def __init__(self, client: "Sonilo") -> None:
        self._client = client

    def get(self, task_id: str) -> SfxResult:
        """Fetch current task state. Never raises on a failed status."""
        return parse_sfx_result(self._client._get_json(f"/v1/tasks/{task_id}"))

    def wait(
        self,
        task_id: str,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> SfxResult:
        """Poll until the task is terminal; raise on failure or deadline."""
        deadline = _monotonic() + timeout
        while True:
            result = self.get(task_id)
            if result.status == "succeeded":
                return result
            _raise_if_failed(result)
            if _monotonic() >= deadline:
                raise _timeout_error(task_id, timeout)
            _sleep(poll_interval)


class AsyncTasks:
    def __init__(self, client: "AsyncSonilo") -> None:
        self._client = client

    async def get(self, task_id: str) -> SfxResult:
        """Fetch current task state. Never raises on a failed status."""
        return parse_sfx_result(await self._client._get_json(f"/v1/tasks/{task_id}"))

    async def wait(
        self,
        task_id: str,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
    ) -> SfxResult:
        """Poll until the task is terminal; raise on failure or deadline."""
        deadline = _monotonic() + timeout
        while True:
            result = await self.get(task_id)
            if result.status == "succeeded":
                return result
            _raise_if_failed(result)
            if _monotonic() >= deadline:
                raise _timeout_error(task_id, timeout)
            await _async_sleep(poll_interval)
