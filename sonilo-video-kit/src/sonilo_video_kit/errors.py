"""Error types for sonilo-video-kit (ported from errors.ts)."""
from __future__ import annotations

from typing import Optional


class VideoKitError(Exception):
    """Base class for all sonilo-video-kit errors."""

    def __init__(self, message: str, *, cause: Optional[BaseException] = None) -> None:
        super().__init__(message)
        self.cause = cause


class FfmpegNotFoundError(VideoKitError):
    """Raised when the ffmpeg/ffprobe binary cannot be found on PATH."""


class FfmpegError(VideoKitError):
    """Raised when ffmpeg/ffprobe exits non-zero or times out."""

    def __init__(
        self,
        message: str,
        *,
        exit_code: Optional[int] = None,
        stderr_tail: str = "",
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.exit_code = exit_code
        self.stderr_tail = stderr_tail


class DuckingFailedError(VideoKitError):
    """Raised when the server marks a ducking task as failed."""

    def __init__(
        self, message: str, *, code: str = "", refunded: bool = False,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.code = code
        self.refunded = refunded
