"""Covers `prompt_influence` on the two music-from-video endpoints.

The field sets how strongly the generated music follows the prompt (0-1; the
API's own default is 0.5, the long-standing behavior). These tests pin the
three things that keep the SDK honest about it — the field is omitted from the
wire unless explicitly passed (so an unset value never pins the API default),
an explicit 0.0 IS sent (`is not None`, never truthiness — 0.0 means "let the
video lead entirely"), and no other endpoint exposes it at all. Range checking
is deliberately left to the API's 422, same as variants_num.
"""
import inspect

from sonilo._requests import (
    build_v2m_async_parts,
    build_v2m_parts,
    build_v2v_music_parts,
)
from sonilo.resources.dubbing import AsyncDubbing, Dubbing
from sonilo.resources.text_to_music import AsyncTextToMusic, TextToMusic
from sonilo.resources.video_to_music import AsyncVideoToMusic, VideoToMusic
from sonilo.resources.video_to_sfx import AsyncVideoToSfx, VideoToSfx
from sonilo.resources.video_to_sound import AsyncVideoToSound, VideoToSound
from sonilo.resources.video_to_video_music import (
    AsyncVideoToVideoMusic,
    VideoToVideoMusic,
)
from sonilo.resources.video_to_video_sfx import (
    AsyncVideoToVideoSfx,
    VideoToVideoSfx,
)
from sonilo.resources.video_to_video_sound import (
    AsyncVideoToVideoSound,
    VideoToVideoSound,
)


# --- video-to-music (the stream builder, shared by stream()/generate()) ------

def test_v2m_omits_prompt_influence_when_none():
    """Unset must stay off the wire entirely: sending an explicit 0.5 would
    pin a default the API owns."""
    data, _, _ = build_v2m_parts(None, "https://x/v.mp4", None, None)
    assert "prompt_influence" not in data


def test_v2m_sends_prompt_influence():
    data, _, _ = build_v2m_parts(
        None, "https://x/v.mp4", None, None, prompt_influence=0.8,
    )
    assert data["prompt_influence"] == "0.8"


def test_v2m_sends_zero_prompt_influence():
    """0.0 is a meaningful value ("let the video lead entirely"), so it must
    go on the wire — this is the truthiness trap the builder guards with
    `is not None`."""
    data, _, _ = build_v2m_parts(
        None, "https://x/v.mp4", None, None, prompt_influence=0.0,
    )
    assert data["prompt_influence"] == "0.0"


# --- video-to-music async (submit()/generate_async()) ------------------------

def test_v2m_async_forwards_prompt_influence_without_touching_mode():
    """prompt_influence is a generation parameter, valid on stream and async
    alike, so it must not participate in the async-mode resolution the
    finalize-time params go through."""
    data, _, _ = build_v2m_async_parts(
        None, "https://x/v.mp4", None, None, None, None,
        prompt_influence=0.3,
    )
    assert data["prompt_influence"] == "0.3"


def test_v2m_async_omits_prompt_influence_when_none():
    data, _, _ = build_v2m_async_parts(
        None, "https://x/v.mp4", None, None, None, None,
    )
    assert "prompt_influence" not in data


# --- video-to-video-music -----------------------------------------------------

def test_v2v_music_omits_prompt_influence_when_none():
    data, _, _ = build_v2v_music_parts(None, "https://x/v.mp4", None, None, None)
    assert "prompt_influence" not in data


def test_v2v_music_sends_prompt_influence():
    data, _, _ = build_v2v_music_parts(
        None, "https://x/v.mp4", None, None, None,
        prompt_influence=0.8,
    )
    assert data["prompt_influence"] == "0.8"


def test_v2v_music_sends_zero_prompt_influence():
    data, _, _ = build_v2v_music_parts(
        None, "https://x/v.mp4", None, None, None,
        prompt_influence=0.0,
    )
    assert data["prompt_influence"] == "0.0"


# --- the public signatures ----------------------------------------------------

def test_music_endpoints_expose_prompt_influence_everywhere():
    """On video-to-music it is valid on the streaming path too — the API takes
    it with no mode guard — so stream() and generate() must expose it, not
    just the async pair."""
    for cls in (VideoToMusic, AsyncVideoToMusic):
        for method in ("stream", "generate", "submit", "generate_async"):
            params = inspect.signature(getattr(cls, method)).parameters
            assert "prompt_influence" in params, f"{cls.__name__}.{method}"
    for cls in (VideoToVideoMusic, AsyncVideoToVideoMusic):
        for method in ("submit", "generate"):
            params = inspect.signature(getattr(cls, method)).parameters
            assert "prompt_influence" in params, f"{cls.__name__}.{method}"


def test_other_endpoints_do_not_expose_prompt_influence():
    """The API accepts prompt_influence nowhere else — not text-to-music, not
    the sfx endpoints, not the sound combos, not dubbing. Asserted on the
    public signatures so adding it by reflex would fail here."""
    for cls in (
        TextToMusic,
        AsyncTextToMusic,
        VideoToSfx,
        AsyncVideoToSfx,
        VideoToSound,
        AsyncVideoToSound,
        VideoToVideoSfx,
        AsyncVideoToVideoSfx,
        VideoToVideoSound,
        AsyncVideoToVideoSound,
        Dubbing,
        AsyncDubbing,
    ):
        for method in ("submit", "generate"):
            params = inspect.signature(getattr(cls, method)).parameters
            assert "prompt_influence" not in params, f"{cls.__name__}.{method}"
