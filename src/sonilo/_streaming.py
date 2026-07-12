from __future__ import annotations

import base64
import binascii
import json
import re
from typing import AsyncIterable, AsyncIterator, Dict, Iterable, Iterator, List, Optional

from sonilo.errors import GenerationError
from sonilo.types import StreamEvent, Track


def _parse_line(line: str) -> Optional[StreamEvent]:
    """Returns `None` for a valid-JSON-but-non-dict line (e.g. a bare `null`
    or a number/string), which carries no event `type` and is skipped like
    any other junk line rather than crashing on a `.get()` off `None`."""
    parsed = json.loads(line)
    if not isinstance(parsed, dict):
        return None
    event = parsed
    if event.get("type") == "audio_chunk" and isinstance(event.get("data"), str):
        try:
            # validate=True is required: the lenient (default) decoder
            # silently discards any character outside the base64 alphabet
            # and re-aligns the remaining quartets instead of raising, so a
            # corrupted chunk whose padding still happens to work out would
            # decode to fewer, wrong bytes with no error at all. Whitespace
            # is stripped first so legitimately-whitespace-containing
            # base64 (e.g. wrapped/pretty-printed payloads) still decodes.
            decoded = base64.b64decode(re.sub(r"\s", "", event["data"]), validate=True)
            event = {**event, "data": decoded}
        except (binascii.Error, ValueError):
            # Don't raise here: this must reach _TrackBuilder.add, whose
            # malformed-chunk check turns undecodable data into a typed
            # GenerationError. Raising in place would let a raw
            # binascii.Error/ValueError escape stream()/generate(), breaking
            # the SDK's "all errors extend SoniloError" contract.
            pass
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
                event = _parse_line(line)
                if event is not None:
                    yield event

    def flush(self) -> Iterator[StreamEvent]:
        line, self._buf = self._buf.strip(), ""
        if line:
            event = _parse_line(line)
            if event is not None:
                yield event


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
        if event_type == "audio_chunk":
            # A malformed chunk (missing/non-decodable `data`) must not be
            # silently dropped: that would hand back a "successful" Track
            # with empty or truncated audio and no indication anything went
            # wrong.
            if not isinstance(event.get("data"), bytes):
                raise GenerationError(
                    "received a malformed audio_chunk event (missing or non-decodable data)"
                )
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
