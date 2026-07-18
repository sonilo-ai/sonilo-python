import pytest
from sonilo_video_kit.errors import (
    VideoKitError, FfmpegNotFoundError, FfmpegError, DuckingFailedError,
)


def test_hierarchy():
    assert issubclass(FfmpegNotFoundError, VideoKitError)
    assert issubclass(FfmpegError, VideoKitError)
    assert issubclass(DuckingFailedError, VideoKitError)
    assert issubclass(VideoKitError, Exception)


def test_ffmpeg_error_carries_context():
    e = FfmpegError("boom", exit_code=1, stderr_tail="last lines")
    assert e.exit_code == 1
    assert e.stderr_tail == "last lines"
    assert isinstance(e, VideoKitError)


def test_ducking_failed_carries_code_and_refund():
    e = DuckingFailedError("nope", code="QUOTA", refunded=True)
    assert e.code == "QUOTA"
    assert e.refunded is True


def test_cause_is_optional():
    inner = ValueError("x")
    e = VideoKitError("wrap", cause=inner)
    assert e.cause is inner
