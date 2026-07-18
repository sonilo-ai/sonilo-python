"""Video helpers for the Sonilo API (ffmpeg-based)."""
from .duck import (
    MAX_DUCKED_MIX_BYTES, MAX_DUCKING_DURATION_SECONDS, duck_music_under_speech,
)
from .errors import (
    DuckingFailedError, FfmpegError, FfmpegNotFoundError, VideoKitError,
)
from .generate import VideoMusicClient, generate_music_for_video
from .loudness import (
    DELIVERY_TARGET_LUFS, FALLBACK_MUSIC_LUFS, GAP_BELOW_VOICE_LU, OUTPUT_CEILING_DBFS,
)
from .mix import mix_with_video

__all__ = sorted([
    "DELIVERY_TARGET_LUFS", "DuckingFailedError", "FALLBACK_MUSIC_LUFS", "FfmpegError",
    "FfmpegNotFoundError", "GAP_BELOW_VOICE_LU", "MAX_DUCKED_MIX_BYTES",
    "MAX_DUCKING_DURATION_SECONDS", "OUTPUT_CEILING_DBFS", "VideoKitError",
    "VideoMusicClient", "duck_music_under_speech", "generate_music_for_video",
    "mix_with_video",
])
