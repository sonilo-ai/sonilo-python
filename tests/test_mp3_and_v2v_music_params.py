"""Covers the three API changes synced in this branch: the mp3 container, the
audio-only output_format on video-to-sound, and ducking/segments on
video-to-video-music."""
import pytest

from sonilo._requests import build_v2s_parts, build_v2v_music_parts, _resolve_music_mode
from sonilo.errors import SoniloError


# --- mp3 / the widened async gate -------------------------------------------

@pytest.mark.parametrize("fmt", ["wav", "mp3"])
def test_non_m4a_formats_force_async(fmt):
    """Both wav and mp3 are finalize-time transcodes. The gate used to name
    'wav' specifically, which would have let mp3 through as a plain stream."""
    assert _resolve_music_mode(None, None, output_format=fmt) == "async"
    with pytest.raises(SoniloError):
        _resolve_music_mode("stream", None, output_format=fmt)


def test_m4a_still_streams():
    assert _resolve_music_mode("stream", None, output_format="m4a") == "stream"


# --- video-to-sound output_format (audio endpoint only) ----------------------

def test_v2s_emits_output_format_when_given():
    data, _, _ = build_v2s_parts(
        None, "https://x/v.mp4", None, None, None, None, None, output_format="mp3"
    )
    assert data["output_format"] == "mp3"


def test_v2s_omits_output_format_when_unset():
    """The server defaults the combined track to wav; an unset value must not
    go out. video-to-video-sound never passes it at all -- that endpoint
    always returns an mp4."""
    data, _, _ = build_v2s_parts(
        None, "https://x/v.mp4", None, None, None, None, None
    )
    assert "output_format" not in data


# --- video-to-video-music ducking + segments --------------------------------

def test_v2v_music_omits_ducking_when_unset():
    """ducking is default-ON server-side, so an unset value must not become an
    explicit 'false' on the wire."""
    data, _, _ = build_v2v_music_parts(None, "https://x/v.mp4", None, None, None)
    assert "ducking" not in data


def test_v2v_music_sends_ducking_false_when_opted_out():
    data, _, _ = build_v2v_music_parts(
        None, "https://x/v.mp4", None, None, None, ducking=False
    )
    assert data["ducking"] == "false"


def test_v2v_music_serializes_segments():
    segments = [
        {"start": 0, "prompt": "sparse pads", "label": "intro"},
        {"start": 30, "prompt": "add drums", "label": "verse"},
    ]
    data, _, _ = build_v2v_music_parts(
        None, "https://x/v.mp4", None, None, None, segments=segments
    )
    import json

    assert json.loads(data["segments"]) == segments
