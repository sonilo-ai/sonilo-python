import pytest
from sonilo_video_kit import (
    duck_music_under_speech, MAX_DUCKING_DURATION_SECONDS, MAX_DUCKED_MIX_BYTES,
)
from sonilo_video_kit.duck import effective_download_cap


def test_constants():
    assert MAX_DUCKING_DURATION_SECONDS == 360
    assert MAX_DUCKED_MIX_BYTES == 300 * 1024 * 1024


def test_effective_cap_clamps_to_server_bytes():
    # min(output_bytes + 64KB, MAX)
    assert effective_download_cap(1000) == 1000 + 64 * 1024
    assert effective_download_cap(None) == MAX_DUCKED_MIX_BYTES
    assert effective_download_cap(10**12) == MAX_DUCKED_MIX_BYTES


def test_missing_output_extension_rejected_before_charge(tmp_path):
    v = tmp_path / "in.mp4"; v.write_bytes(b"x")
    with pytest.raises(Exception):
        duck_music_under_speech(video=v, audio=b"music", output=tmp_path / "noext",
                                client=object())  # must fail on validation, never touch client
