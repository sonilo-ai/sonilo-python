from __future__ import annotations

import base64
import json
from typing import AsyncIterable, AsyncIterator, Dict, Iterable, Iterator, List, Optional

from sonilo.errors import GenerationError
from sonilo.types import StreamEvent, Track


def _parse_line(line: str) -> StreamEvent:
    event = json.loads(line)
    if event.get("type") == "audio_chunk" and isinstance(event.get("data"), str):
        event = {**event, "data": base64.b64decode(event["data"])}
    return event


class _LineBuffer:
    """Accumulates text chunks and yields complete NDJSON lines."""

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, text: str) -> Iterator[StreamEvent]:
        self._buf += text
        while True:
            idx = self._buf.find("\n")
            if idx == -1:
                return
            line, self._buf = self._buf[:idx].strip(), self._buf[idx + 1 :]
            if line:
                yield _parse_line(line)

    def flush(self) -> Iterator[StreamEvent]:
        line, self._buf = self._buf.strip(), ""
        if line:
            yield _parse_line(line)


def iter_events(text_chunks: Iterable[str]) -> Iterator[StreamEvent]:
    buf = _LineBuffer()
    for chunk in text_chunks:
        yield from buf.feed(chunk)
    yield from buf.flush()


async def aiter_events(text_chunks: AsyncIterable[str]) -> AsyncIterator[StreamEvent]:
    buf = _LineBuffer()
    async for chunk in text_chunks:
        for event in buf.feed(chunk):
            yield event
    for event in buf.flush():
        yield event


class _TrackBuilder:
    def __init__(self) -> None:
        self._chunks: List[bytes] = []
        self._title: Optional[str] = None
        self._cost: Optional[Dict[str, str]] = None
        self._complete = False

    def add(self, event: StreamEvent) -> None:
        event_type = event.get("type")
        if event_type == "audio_chunk" and isinstance(event.get("data"), bytes):
            self._chunks.append(event["data"])
        elif event_type == "title" and isinstance(event.get("title"), str):
            self._title = event["title"]
        elif event_type == "cost":
            self._cost = {k: v for k, v in event.items() if k != "type"}
        elif event_type == "error":
            message = event.get("message") or "generation failed"
            code = event.get("code")
            raise GenerationError(str(message), code=code if isinstance(code, str) else None)
        elif event_type == "complete":
            self._complete = True
        # unknown event types: ignored

    def build(self) -> Track:
        if not self._complete:
            raise GenerationError("stream ended before a 'complete' event (truncated response)")
        return Track(audio=b"".join(self._chunks), title=self._title, cost=self._cost)


def collect_track(events: Iterable[StreamEvent]) -> Track:
    builder = _TrackBuilder()
    try:
        for event in events:
            builder.add(event)
    finally:
        close = getattr(events, "close", None)
        if close is not None:
            close()
    return builder.build()


async def acollect_track(events: AsyncIterable[StreamEvent]) -> Track:
    builder = _TrackBuilder()
    try:
        async for event in events:
            builder.add(event)
    finally:
        aclose = getattr(events, "aclose", None)
        if aclose is not None:
            await aclose()
    return builder.build()
