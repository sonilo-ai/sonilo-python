from __future__ import annotations

from typing import Any, AsyncIterator, Dict, Optional

import httpx

from sonilo._client import DEFAULT_BASE_URL, DEFAULT_TIMEOUT, _default_headers, _resolve_api_key
from sonilo._streaming import aiter_events
from sonilo.errors import error_from_response
from sonilo.resources.account import AsyncAccount
from sonilo.resources.tasks import AsyncTasks
from sonilo.resources.text_to_music import AsyncTextToMusic
from sonilo.resources.text_to_sfx import AsyncTextToSfx
from sonilo.resources.video_to_music import AsyncVideoToMusic
from sonilo.resources.video_to_sfx import AsyncVideoToSfx
from sonilo.types import StreamEvent


class AsyncSonilo:
    """Asynchronous Sonilo API client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        key = _resolve_api_key(api_key)
        self._http = httpx.AsyncClient(
            base_url=(base_url or DEFAULT_BASE_URL).rstrip("/"),
            headers=_default_headers(key, "sdk-python"),
            timeout=timeout,
        )
        self.text_to_music = AsyncTextToMusic(self)
        self.video_to_music = AsyncVideoToMusic(self)
        self.text_to_sfx = AsyncTextToSfx(self)
        self.video_to_sfx = AsyncVideoToSfx(self)
        self.account = AsyncAccount(self)
        self.tasks = AsyncTasks(self)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AsyncSonilo":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()

    # -- internal transport -------------------------------------------------

    async def _get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        response = await self._http.get(path, params=params)
        if response.status_code >= 400:
            raise error_from_response(response)
        return response.json()

    async def _post_json(
        self,
        path: str,
        *,
        data: Dict[str, str],
        files: Optional[Dict[str, tuple]] = None,
        close_after: Any = None,
    ) -> Any:
        try:
            response = await self._http.post(path, data=data, files=files)
        finally:
            if close_after is not None:
                close_after.close()
        if response.status_code >= 400:
            raise error_from_response(response)
        return response.json()

    async def _stream_events(
        self,
        path: str,
        *,
        data: Dict[str, str],
        files: Optional[Dict[str, tuple]] = None,
        close_after: Any = None,
    ) -> AsyncIterator[StreamEvent]:
        try:
            async with self._http.stream("POST", path, data=data, files=files) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise error_from_response(response)
                async for event in aiter_events(response.aiter_text()):
                    yield event
        finally:
            if close_after is not None:
                close_after.close()
