from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator, Iterator, List, Optional

from sonilo._requests import build_t2m_data
from sonilo._streaming import acollect_track, collect_track
from sonilo.types import Segment, StreamEvent, Track

if TYPE_CHECKING:
    from sonilo._async_client import AsyncSonilo
    from sonilo._client import Sonilo

PATH = "/v1/text-to-music"


class TextToMusic:
    def __init__(self, client: "Sonilo") -> None:
        self._client = client

    def stream(
        self,
        *,
        prompt: str,
        duration: int,
        segments: Optional[List[Segment]] = None,
    ) -> Iterator[StreamEvent]:
        data = build_t2m_data(prompt, duration, segments)
        return self._client._stream_events(PATH, data=data)

    def generate(
        self,
        *,
        prompt: str,
        duration: int,
        segments: Optional[List[Segment]] = None,
    ) -> Track:
        return collect_track(self.stream(prompt=prompt, duration=duration, segments=segments))


class AsyncTextToMusic:
    def __init__(self, client: "AsyncSonilo") -> None:
        self._client = client

    def stream(
        self,
        *,
        prompt: str,
        duration: int,
        segments: Optional[List[Segment]] = None,
    ) -> AsyncIterator[StreamEvent]:
        data = build_t2m_data(prompt, duration, segments)
        return self._client._stream_events(PATH, data=data)

    async def generate(
        self,
        *,
        prompt: str,
        duration: int,
        segments: Optional[List[Segment]] = None,
    ) -> Track:
        return await acollect_track(
            self.stream(prompt=prompt, duration=duration, segments=segments)
        )
