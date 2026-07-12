from __future__ import annotations

import os
from typing import Any, Dict, Iterator, Optional

import httpx

from sonilo._streaming import iter_events
from sonilo._version import __version__
from sonilo.errors import SoniloError, error_from_response
from sonilo.resources.account import Account
from sonilo.resources.tasks import Tasks
from sonilo.resources.text_to_music import TextToMusic
from sonilo.resources.video_to_music import VideoToMusic
from sonilo.types import StreamEvent

DEFAULT_BASE_URL = "https://api.sonilo.com"
DEFAULT_TIMEOUT = 600.0


def _resolve_api_key(api_key: Optional[str]) -> str:
    key = api_key or os.environ.get("SONILO_API_KEY")
    if not key:
        raise SoniloError(
            "Missing API key: pass api_key= or set the SONILO_API_KEY environment variable"
        )
    return key


def _default_headers(api_key: str, client_name: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "X-Sonilo-Client": client_name,
        "X-Sonilo-Client-Version": __version__,
    }


class Sonilo:
    """Synchronous Sonilo API client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        key = _resolve_api_key(api_key)
        self._http = httpx.Client(
            base_url=(base_url or DEFAULT_BASE_URL).rstrip("/"),
            headers=_default_headers(key, "sdk-python"),
            timeout=timeout,
        )
        self.text_to_music = TextToMusic(self)
        self.video_to_music = VideoToMusic(self)
        self.account = Account(self)
        self.tasks = Tasks(self)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Sonilo":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # -- internal transport -------------------------------------------------

    def _get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        response = self._http.get(path, params=params)
        if response.status_code >= 400:
            raise error_from_response(response)
        return response.json()

    def _stream_events(
        self,
        path: str,
        *,
        data: Dict[str, str],
        files: Optional[Dict[str, tuple]] = None,
        close_after: Any = None,
    ) -> Iterator[StreamEvent]:
        try:
            with self._http.stream("POST", path, data=data, files=files) as response:
                if response.status_code >= 400:
                    response.read()
                    raise error_from_response(response)
                for event in iter_events(response.iter_text()):
                    yield event
        finally:
            if close_after is not None:
                close_after.close()
