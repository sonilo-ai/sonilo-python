import sys
import pytest
from sonilo_video_kit._ffmpeg import run_process
from sonilo_video_kit.errors import FfmpegNotFoundError, FfmpegError


def test_success_captures_stdout():
    r = run_process(sys.executable, ["-c", "print('hello')"])
    assert "hello" in r.stdout


def test_missing_binary_raises_not_found():
    with pytest.raises(FfmpegNotFoundError):
        run_process("definitely-not-a-real-binary-xyz", ["--version"])


def test_nonzero_exit_raises_ffmpeg_error():
    with pytest.raises(FfmpegError) as ei:
        run_process(sys.executable, ["-c", "import sys; sys.stderr.write('bad\\n'); sys.exit(3)"])
    assert ei.value.exit_code == 3
    assert "bad" in ei.value.stderr_tail


def test_timeout_raises_ffmpeg_error():
    with pytest.raises(FfmpegError):
        run_process(sys.executable, ["-c", "import time; time.sleep(5)"], timeout=0.2)
