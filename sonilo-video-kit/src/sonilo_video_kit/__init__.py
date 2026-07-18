"""Video helpers for the Sonilo API (ffmpeg-based)."""

__all__: list[str] = []

from .generate import VideoMusicClient, generate_music_for_video
__all__ += ["generate_music_for_video", "VideoMusicClient"]
