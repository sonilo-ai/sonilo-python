"""ffmpeg/ffprobe subprocess layer (ported from ffmpeg.ts)."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .errors import FfmpegError, FfmpegNotFoundError

_STDERR_TAIL_CHARS = 4096
DEFAULT_TIMEOUT_SECONDS = 1200.0


@dataclass
class ProcessResult:
    stdout: str
    stderr: str


def run_process(
    binary: str, args: list[str], *, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> ProcessResult:
    try:
        proc = subprocess.run(
            [binary, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise FfmpegNotFoundError(
            f"'{binary}' not found. Install ffmpeg or pass an explicit path.",
            cause=exc,
        ) from exc
    except subprocess.TimeoutExpired as exc:
        tail = (exc.stderr or b"")[-_STDERR_TAIL_CHARS:] if isinstance(exc.stderr, bytes) else ""
        raise FfmpegError(
            f"'{binary}' timed out after {timeout}s",
            exit_code=None,
            stderr_tail=str(tail),
        ) from exc

    if proc.returncode != 0:
        tail = (proc.stderr or "")[-_STDERR_TAIL_CHARS:]
        raise FfmpegError(
            f"'{binary}' exited with {proc.returncode}",
            exit_code=proc.returncode,
            stderr_tail=tail,
        )
    return ProcessResult(stdout=proc.stdout or "", stderr=proc.stderr or "")
