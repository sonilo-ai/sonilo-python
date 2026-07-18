"""Video helpers for the Sonilo API (ffmpeg-based)."""

__all__: list[str] = []

from .generate import VideoMusicClient, generate_music_for_video
__all__ += ["generate_music_for_video", "VideoMusicClient"]

from .mix import mix_with_video
__all__ += ["mix_with_video"]

from .duck import (
    duck_music_under_speech, MAX_DUCKING_DURATION_SECONDS, MAX_DUCKED_MIX_BYTES,
)
__all__ += ["duck_music_under_speech", "MAX_DUCKING_DURATION_SECONDS", "MAX_DUCKED_MIX_BYTES"]
