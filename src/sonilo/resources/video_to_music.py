from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator, Iterator, List, Optional

from sonilo._requests import build_v2m_parts
from sonilo._streaming import acollect_track, collect_track
from sonilo.types import Segment, StreamEvent, Track

if TYPE_CHECKING:
    from sonilo._async_client import AsyncSonilo
    from sonilo._client import Sonilo

PATH = "/v1/video-to-music"


class VideoToMusic:
    def __init__(self, client: "Sonilo") -> None:
        self._client = client

    def stream(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        segments: Optional[List[Segment]] = None,
    ) -> Iterator[StreamEvent]:
        data, files, opened = build_v2m_parts(video, video_url, prompt, segments)
        close_after = files["video"][1] if files is not None and opened else None
        return self._client._stream_events(PATH, data=data, files=files, close_after=close_after)

    def generate(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        segments: Optional[List[Segment]] = None,
    ) -> Track:
        return collect_track(
            self.stream(video=video, video_url=video_url, prompt=prompt, segments=segments)
        )


class AsyncVideoToMusic:
    def __init__(self, client: "AsyncSonilo") -> None:
        self._client = client

    def stream(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        segments: Optional[List[Segment]] = None,
    ) -> AsyncIterator[StreamEvent]:
        data, files, opened = build_v2m_parts(video, video_url, prompt, segments)
        close_after = files["video"][1] if files is not None and opened else None
        return self._client._stream_events(PATH, data=data, files=files, close_after=close_after)

    async def generate(
        self,
        *,
        video: Any = None,
        video_url: Optional[str] = None,
        prompt: Optional[str] = None,
        segments: Optional[List[Segment]] = None,
    ) -> Track:
        return await acollect_track(
            self.stream(video=video, video_url=video_url, prompt=prompt, segments=segments)
        )
