from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, List, Optional

from sonilo._requests import build_t2m_data
from sonilo._streaming import collect_track
from sonilo.types import Segment, StreamEvent, Track

if TYPE_CHECKING:
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
