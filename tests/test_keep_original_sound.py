"""Covers `keep_original_sound` on the two video-output endpoints.

The server flipped both endpoints' defaults: a request that does not set this
flag now returns the generated audio alone, where it previously returned the
source video's speech with the generated music ducked underneath. These tests
pin the two things that keep the SDK honest about that — the flag is omitted
from the wire unless explicitly passed (so an unset value never becomes an
explicit "true"), and it never reaches the audio-only endpoint at all.
"""
import inspect

from sonilo._requests import build_v2s_parts, build_v2v_music_parts
from sonilo.resources.video_to_sound import AsyncVideoToSound, VideoToSound
from sonilo.resources.video_to_video_music import (
    AsyncVideoToVideoMusic,
    VideoToVideoMusic,
)
from sonilo.resources.video_to_video_sound import (
    AsyncVideoToVideoSound,
    VideoToVideoSound,
)


# --- video-to-video-music ----------------------------------------------------

def test_v2v_music_omits_keep_original_sound_when_none():
    """Default-OFF server-side, so an unset value must not go out as "true" —
    and must not go out as "false" either, which would pin a default the server
    owns."""
    data, _, _ = build_v2v_music_parts(None, "https://x/v.mp4", None, None, None)
    assert "keep_original_sound" not in data


def test_v2v_music_sends_keep_original_sound():
    data, _, _ = build_v2v_music_parts(
        None, "https://x/v.mp4", None, None, None,
        keep_original_sound=True,
    )
    assert data["keep_original_sound"] == "true"


def test_v2v_music_static_mix_row():
    """`keep_original_sound` + `ducking=False` is the new static-mix row: the
    whole original track, mixed at a fixed offset instead of ducked."""
    data, _, _ = build_v2v_music_parts(
        None, "https://x/v.mp4", None, None, None,
        keep_original_sound=True, ducking=False,
    )
    assert data["keep_original_sound"] == "true"
    assert data["ducking"] == "false"


def test_v2v_music_sends_both_flags_leaving_precedence_to_the_server():
    """Deliberately not resolved client-side: the server supersedes
    preserve_speech with keep_original_sound and logs that it did. Resolving it
    here would hide the override and desync from the other SDKs."""
    data, _, _ = build_v2v_music_parts(
        None, "https://x/v.mp4", None, True, None,
        keep_original_sound=True,
    )
    assert data["keep_original_sound"] == "true"
    assert data["preserve_speech"] == "true"


def test_v2v_music_explicit_false_is_sent():
    """An explicit False is a real request ("do not keep it"), distinct from
    unset, so it does go on the wire."""
    data, _, _ = build_v2v_music_parts(
        None, "https://x/v.mp4", None, None, None,
        keep_original_sound=False,
    )
    assert data["keep_original_sound"] == "false"


# --- video-to-video-sound ----------------------------------------------------

def test_v2s_omits_keep_original_sound_when_none():
    data, _, _ = build_v2s_parts(
        None, "https://x/v.mp4", None, None, None, None, None,
    )
    assert "keep_original_sound" not in data


def test_v2s_sends_keep_original_sound():
    data, _, _ = build_v2s_parts(
        None, "https://x/v.mp4", None, None, None, None, None,
        keep_original_sound=True,
    )
    assert data["keep_original_sound"] == "true"


# --- the audio endpoint must never expose or send it -------------------------

def test_audio_endpoint_does_not_expose_keep_original_sound():
    """`keep_original_sound` is video-only: it only means something when the
    deliverable is a video whose own audio could be preserved. The audio
    resource simply never passes it to the shared builder — the mirror of how
    `output_format` is kept off video-to-video-sound. Asserted on the public
    signatures so adding it by reflex would fail here."""
    for cls in (VideoToSound, AsyncVideoToSound):
        for method in ("submit", "generate"):
            params = inspect.signature(getattr(cls, method)).parameters
            assert "keep_original_sound" not in params, f"{cls.__name__}.{method}"


def test_video_endpoints_do_expose_keep_original_sound():
    for cls in (
        VideoToVideoMusic,
        AsyncVideoToVideoMusic,
        VideoToVideoSound,
        AsyncVideoToVideoSound,
    ):
        for method in ("submit", "generate"):
            params = inspect.signature(getattr(cls, method)).parameters
            assert "keep_original_sound" in params, f"{cls.__name__}.{method}"
