import base64
import json

import pytest

from sonilo._streaming import acollect_track, aiter_events, collect_track, iter_events
from sonilo.errors import GenerationError
from sonilo.types import Track


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


LINES = (
    json.dumps({"type": "title", "title": "Skyline", "summary": "s"})
    + "\n"
    + json.dumps({"type": "audio_chunk", "data": b64(b"abc")})
    + "\n"
    + json.dumps({"type": "audio_chunk", "data": b64(b"def")})
    + "\n"
    + json.dumps({"type": "complete"})
    + "\n"
)


def chunked(text: str, size: int):
    return [text[i : i + size] for i in range(0, len(text), size)]


async def as_async_iter(items):
    for item in items:
        yield item


def test_iter_events_whole_chunks():
    events = list(iter_events([LINES]))
    assert [e["type"] for e in events] == ["title", "audio_chunk", "audio_chunk", "complete"]


def test_iter_events_one_char_chunks():
    events = list(iter_events(chunked(LINES, 1)))
    assert [e["type"] for e in events] == ["title", "audio_chunk", "audio_chunk", "complete"]


def test_audio_chunk_data_is_decoded_bytes():
    events = list(iter_events(chunked(LINES, 7)))
    assert events[1]["data"] == b"abc"


def test_trailing_line_without_newline():
    events = list(iter_events([json.dumps({"type": "complete"})]))
    assert events == [{"type": "complete"}]


def test_empty_lines_skipped():
    events = list(iter_events(["\n\n" + json.dumps({"type": "complete"}) + "\n\n"]))
    assert events == [{"type": "complete"}]


def test_unknown_event_passed_through():
    events = list(iter_events([json.dumps({"type": "stage_start", "stage": "analyze"}) + "\n"]))
    assert events == [{"type": "stage_start", "stage": "analyze"}]


def test_bare_null_line_skipped_instead_of_raising_attribute_error():
    text = "null\n" + json.dumps({"type": "complete"}) + "\n"
    events = list(iter_events([text]))
    assert events == [{"type": "complete"}]


async def test_aiter_events_matches_sync():
    events = [e async for e in aiter_events(as_async_iter(chunked(LINES, 3)))]
    assert [e["type"] for e in events] == ["title", "audio_chunk", "audio_chunk", "complete"]
    assert events[1]["data"] == b"abc"


COST = {
    "type": "cost",
    "billing_rate_per_sec": "0.01",
    "billing_before_discount": "0.6000",
    "billing_after_discount": "0.4800",
    "discount_factor": "0.8000",
}


def test_collect_track_concatenates_and_captures_metadata():
    text = LINES.replace(json.dumps({"type": "complete"}) + "\n", "") + json.dumps(COST) + "\n" + json.dumps({"type": "complete"}) + "\n"
    track = collect_track(iter_events(chunked(text, 11)))
    assert isinstance(track, Track)
    assert track.audio == b"abcdef"
    assert track.title == "Skyline"
    assert track.cost == {k: v for k, v in COST.items() if k != "type"}


def test_collect_track_ignores_unknown_events():
    text = (
        json.dumps({"type": "stage_start"})
        + "\n"
        + json.dumps({"type": "audio_chunk", "data": b64(b"x")})
        + "\n"
        + json.dumps({"type": "complete"})
        + "\n"
    )
    track = collect_track(iter_events([text]))
    assert track.audio == b"x"
    assert track.title is None


def test_collect_track_raises_generation_error_on_error_event():
    text = (
        json.dumps({"type": "audio_chunk", "data": b64(b"x")})
        + "\n"
        + json.dumps({"type": "error", "code": "PROXY_ERROR", "message": "upstream died"})
        + "\n"
    )
    with pytest.raises(GenerationError) as excinfo:
        collect_track(iter_events([text]))
    assert excinfo.value.code == "PROXY_ERROR"
    assert "upstream died" in str(excinfo.value)


async def test_acollect_track_matches_sync():
    track = await acollect_track(aiter_events(as_async_iter(chunked(LINES, 5))))
    assert track.audio == b"abcdef"
    assert track.title == "Skyline"


def test_track_save(tmp_path):
    out = Track(audio=b"abc").save(tmp_path / "out.mp3")
    assert out.read_bytes() == b"abc"


def test_collect_track_closes_generator_on_error_event():
    closed = []

    def gen():
        try:
            yield {"type": "error", "message": "boom"}
            yield {"type": "complete"}
        finally:
            closed.append(True)

    with pytest.raises(GenerationError):
        collect_track(gen())
    assert closed == [True]


async def test_acollect_track_closes_generator_on_error_event():
    closed = []

    async def agen():
        try:
            yield {"type": "error", "message": "boom"}
            yield {"type": "complete"}
        finally:
            closed.append(True)

    with pytest.raises(GenerationError):
        await acollect_track(agen())
    assert closed == [True]


def test_collect_track_raises_on_missing_complete():
    events = iter_events([json.dumps({"type": "audio_chunk", "data": b64(b"x")}) + "\n"])
    with pytest.raises(GenerationError):
        collect_track(events)


def test_collect_track_raises_on_empty_stream():
    with pytest.raises(GenerationError):
        collect_track(iter_events([]))


def test_collect_track_raises_on_audio_chunk_with_missing_data():
    text = (
        json.dumps({"type": "title", "title": "Skyline"})
        + "\n"
        + json.dumps({"type": "audio_chunk"})
        + "\n"
        + json.dumps({"type": "complete"})
        + "\n"
    )
    with pytest.raises(GenerationError):
        collect_track(iter_events([text]))


def test_collect_track_raises_on_audio_chunk_with_non_string_data():
    text = (
        json.dumps({"type": "title", "title": "Skyline"})
        + "\n"
        + json.dumps({"type": "audio_chunk", "data": 12345})
        + "\n"
        + json.dumps({"type": "complete"})
        + "\n"
    )
    with pytest.raises(GenerationError):
        collect_track(iter_events([text]))


async def test_acollect_track_raises_on_audio_chunk_with_missing_data():
    text = (
        json.dumps({"type": "title", "title": "Skyline"})
        + "\n"
        + json.dumps({"type": "audio_chunk"})
        + "\n"
        + json.dumps({"type": "complete"})
        + "\n"
    )
    with pytest.raises(GenerationError):
        await acollect_track(aiter_events(as_async_iter([text])))


def test_audio_chunk_with_undecodable_base64_data_passes_through_undecoded():
    text = (
        json.dumps({"type": "title", "title": "Skyline"})
        + "\n"
        + json.dumps({"type": "audio_chunk", "data": "not-valid-base64!!!"})
        + "\n"
        + json.dumps({"type": "complete"})
        + "\n"
    )
    events = list(iter_events([text]))
    audio_chunk = next(e for e in events if e["type"] == "audio_chunk")
    assert audio_chunk["data"] == "not-valid-base64!!!"


def test_collect_track_raises_generation_error_on_undecodable_audio_chunk_data():
    text = (
        json.dumps({"type": "title", "title": "Skyline"})
        + "\n"
        + json.dumps({"type": "audio_chunk", "data": "not-valid-base64!!!"})
        + "\n"
        + json.dumps({"type": "complete"})
        + "\n"
    )
    with pytest.raises(GenerationError):
        collect_track(iter_events([text]))


def test_audio_chunk_empty_string_data_still_decodes_to_zero_length_bytes():
    text = (
        json.dumps({"type": "title", "title": "Skyline"})
        + "\n"
        + json.dumps({"type": "audio_chunk", "data": ""})
        + "\n"
        + json.dumps({"type": "complete"})
        + "\n"
    )
    events = list(iter_events([text]))
    audio_chunk = next(e for e in events if e["type"] == "audio_chunk")
    assert audio_chunk["data"] == b""
    track = collect_track(iter_events([text]))
    assert track.audio == b""
