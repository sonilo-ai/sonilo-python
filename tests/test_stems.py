"""Covers the `stems` option on text-to-music and video-to-music.

`stems=True` (free of charge) asks the API to also split the GENERATED music
into drums/bass/vocals/other after generation. These tests pin the request
side — the field is omitted unless explicitly passed, an explicit False is
sent, and requesting stems is async-only with the same local fail-fast as the
other finalize-time options — and the result side, whose two fields are
independent by contract: `stems` entries are looked up by `stream_index`
(never list position — the list can be shorter than `audio`), and
`stems_error` can accompany a PARTIAL `stems` list, so it must never be
treated as "no stems".
"""
import inspect

import httpx
import pytest
import respx

from sonilo import MusicStems, SoniloError
from sonilo._requests import build_t2m_async_data, build_v2m_async_parts
from sonilo.resources.audio_ducking import AsyncAudioDucking, AudioDucking
from sonilo.resources.dubbing import AsyncDubbing, Dubbing
from sonilo.resources.tasks import parse_music_result
from sonilo.resources.text_to_music import AsyncTextToMusic, TextToMusic
from sonilo.resources.video_to_music import AsyncVideoToMusic, VideoToMusic
from sonilo.resources.video_to_sfx import AsyncVideoToSfx, VideoToSfx
from sonilo.resources.video_to_sound import AsyncVideoToSound, VideoToSound
from sonilo.resources.video_to_video_music import (
    AsyncVideoToVideoMusic,
    VideoToVideoMusic,
)
from sonilo.resources.video_to_video_sound import (
    AsyncVideoToVideoSound,
    VideoToVideoSound,
)
from sonilo.types import MusicResult, SfxMedia


# --- the request: text-to-music ----------------------------------------------

def test_t2m_async_data_sends_stems():
    data = build_t2m_async_data("lofi", 30, None, None, None, stems=True)
    assert data["stems"] == "true"


def test_t2m_async_data_sends_explicit_false():
    # Same tri-state as ducking: None means unset, False is a real value that
    # goes on the wire.
    data = build_t2m_async_data("lofi", 30, None, None, None, stems=False)
    assert data["stems"] == "false"


def test_t2m_async_data_omits_stems_when_unset():
    data = build_t2m_async_data("lofi", 30, None, None, None)
    assert "stems" not in data


# --- the request: video-to-music ---------------------------------------------

def test_v2m_async_parts_sends_stems_and_auto_selects_async():
    data, _, _ = build_v2m_async_parts(
        None, "https://x/v.mp4", None, None, None, None, stems=True
    )
    assert data["stems"] == "true"
    assert data["mode"] == "async"


def test_v2m_async_parts_omits_stems_when_unset():
    data, _, _ = build_v2m_async_parts(
        None, "https://x/v.mp4", None, None, None, None
    )
    assert "stems" not in data


def test_v2m_stems_with_explicit_non_async_mode_raises_locally():
    # The API answers 400 "stems requires mode=async"; the SDK fails fast
    # before any request instead, same as the other async-only options.
    with pytest.raises(SoniloError, match="stems"):
        build_v2m_async_parts(
            None, "https://x/v.mp4", None, None, "sync", None, stems=True
        )


def test_v2m_explicit_false_stems_does_not_force_async():
    # bool(stems), not `is not None`: stems=False requests nothing
    # finalize-time, so it must not hijack an explicitly chosen mode.
    data, _, _ = build_v2m_async_parts(
        None, "https://x/v.mp4", None, None, "sync", None, stems=False
    )
    assert data["mode"] == "sync"
    assert data["stems"] == "false"


# --- the result: parsing ------------------------------------------------------

def _body(**overrides):
    body = {
        "task_id": "t1",
        "type": "text_to_music",
        "status": "succeeded",
        "audio": [
            {"stream_index": 0, "url": "https://r2.example.com/a0.m4a"},
            {"stream_index": 1, "url": "https://r2.example.com/a1.m4a"},
        ],
    }
    body.update(overrides)
    return body


def _stems_entry(i):
    return {
        "stream_index": i,
        "drums": {"url": f"https://r2.example.com/{i}.drums.m4a",
                  "content_type": "audio/mp4", "file_size": 4},
        "bass": {"url": f"https://r2.example.com/{i}.bass.m4a"},
        "vocals": {"url": f"https://r2.example.com/{i}.vocals.m4a"},
        "other": {"url": f"https://r2.example.com/{i}.other.m4a"},
    }


def test_parse_music_result_parses_stems():
    result = parse_music_result(_body(stems=[_stems_entry(0), _stems_entry(1)]))
    assert result.stems is not None and len(result.stems) == 2
    entry = result.stems[0]
    assert isinstance(entry, MusicStems)
    assert entry.stream_index == 0
    assert isinstance(entry.drums, SfxMedia)
    assert entry.drums.url == "https://r2.example.com/0.drums.m4a"
    assert entry.drums.content_type == "audio/mp4"
    assert entry.bass.url == "https://r2.example.com/0.bass.m4a"
    assert result.stems_error is None


def test_parse_music_result_without_stems_fields():
    result = parse_music_result(_body())
    assert result.stems is None
    assert result.stems_error is None


def test_stems_error_alongside_partial_stems():
    """The two fields are independent: a stems_error must never hide the
    entries that DID separate."""
    result = parse_music_result(
        _body(stems=[_stems_entry(1)], stems_error="stream 0 failed to separate")
    )
    assert result.stems_error == "stream 0 failed to separate"
    assert result.stems is not None and len(result.stems) == 1
    assert result.stems[0].stream_index == 1


def test_malformed_stems_entries_are_dropped():
    # Same coercion policy as parse_dubbing_result's outputs: a
    # differently-shaped entry from a later backend change surfaces as a
    # missing item, not an AttributeError deep in the caller's loop.
    result = parse_music_result(
        _body(stems=["nope", {"no_stream_index": True}, _stems_entry(0)])
    )
    assert [e.stream_index for e in result.stems] == [0]


def test_non_list_stems_parses_as_none():
    result = parse_music_result(_body(stems={"stream_index": 0}))
    assert result.stems is None


# --- the result: stream_index lookup and save_stem ---------------------------

def _partial_result():
    """Only stream 1 separated — the list is shorter than audio, so a
    positional stems[0] would silently hand back the wrong stream's stems."""
    return parse_music_result(
        _body(stems=[_stems_entry(1)], stems_error="stream 0 failed to separate")
    )


def test_stems_for_matches_stream_index_not_position():
    result = _partial_result()
    assert result.stems_for(1) is result.stems[0]
    assert result.stems_for(0) is None


@respx.mock
def test_save_stem_looks_up_by_stream_index(tmp_path):
    respx.get("https://r2.example.com/1.drums.m4a").mock(
        return_value=httpx.Response(200, content=b"drumbytes")
    )
    out = _partial_result().save_stem(
        tmp_path / "drums.m4a", which="drums", stream_index=1
    )
    assert out.read_bytes() == b"drumbytes"
    assert "authorization" not in respx.calls.last.request.headers


def test_save_stem_missing_stream_names_the_stems_error(tmp_path):
    with pytest.raises(SoniloError, match="stream 0 failed to separate"):
        _partial_result().save_stem(tmp_path / "x.m4a", which="drums", stream_index=0)


def test_save_stem_rejects_unknown_which(tmp_path):
    with pytest.raises(SoniloError, match="drums, bass, vocals, other"):
        _partial_result().save_stem(tmp_path / "x.m4a", which="mux", stream_index=1)


def test_save_stem_missing_media_raises(tmp_path):
    result = MusicResult(
        task_id="t1", status="succeeded",
        stems=[MusicStems(stream_index=0)],
    )
    with pytest.raises(SoniloError, match="No drums stem"):
        result.save_stem(tmp_path / "x.m4a", which="drums")


async def test_asave_stem_matches_save_stem(tmp_path):
    with respx.mock:
        respx.get("https://r2.example.com/1.vocals.m4a").mock(
            return_value=httpx.Response(200, content=b"vox")
        )
        out = await _partial_result().asave_stem(
            tmp_path / "vocals.m4a", which="vocals", stream_index=1
        )
    assert out.read_bytes() == b"vox"


# --- the public signatures ----------------------------------------------------

def test_music_async_paths_expose_stems():
    for cls in (TextToMusic, AsyncTextToMusic, VideoToMusic, AsyncVideoToMusic):
        for method in ("submit", "generate_async"):
            params = inspect.signature(getattr(cls, method)).parameters
            assert "stems" in params, f"{cls.__name__}.{method}"


def test_streaming_paths_do_not_expose_stems():
    """stems is finalize-time and async-only — the streaming methods must not
    grow it."""
    for cls in (TextToMusic, AsyncTextToMusic, VideoToMusic, AsyncVideoToMusic):
        for method in ("stream", "generate"):
            params = inspect.signature(getattr(cls, method)).parameters
            assert "stems" not in params, f"{cls.__name__}.{method}"


def test_other_endpoints_do_not_expose_stems():
    """The API accepts stems on text-to-music and video-to-music only — not
    the video-out endpoints, not the sound combos, not dubbing or ducking.
    Asserted on the public signatures so adding it by reflex would fail
    here."""
    for cls in (
        VideoToSfx,
        AsyncVideoToSfx,
        VideoToSound,
        AsyncVideoToSound,
        VideoToVideoMusic,
        AsyncVideoToVideoMusic,
        VideoToVideoSound,
        AsyncVideoToVideoSound,
        Dubbing,
        AsyncDubbing,
        AudioDucking,
        AsyncAudioDucking,
    ):
        for method in ("submit", "generate"):
            params = inspect.signature(getattr(cls, method)).parameters
            assert "stems" not in params, f"{cls.__name__}.{method}"
