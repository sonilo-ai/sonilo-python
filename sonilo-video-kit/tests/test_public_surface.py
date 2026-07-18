import sonilo_video_kit as vk


def test_public_exports_present():
    expected = {
        "generate_music_for_video", "mix_with_video", "duck_music_under_speech",
        "VideoKitError", "FfmpegError", "FfmpegNotFoundError", "DuckingFailedError",
        "DELIVERY_TARGET_LUFS", "FALLBACK_MUSIC_LUFS", "GAP_BELOW_VOICE_LU",
        "OUTPUT_CEILING_DBFS", "MAX_DUCKING_DURATION_SECONDS", "MAX_DUCKED_MIX_BYTES",
        "VideoMusicClient",
    }
    assert expected <= set(vk.__all__)
    for name in expected:
        assert hasattr(vk, name)


def test_all_is_sorted():
    assert vk.__all__ == sorted(vk.__all__)
