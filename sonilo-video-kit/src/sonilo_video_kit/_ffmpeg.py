"""ffmpeg/ffprobe subprocess layer (ported from ffmpeg.ts)."""
from __future__ import annotations

import json
import math
import re
import subprocess
from dataclasses import dataclass
from os import PathLike
from typing import Any, Union

from .errors import FfmpegError, FfmpegNotFoundError, VideoKitError

_STDERR_TAIL_CHARS = 4096
DEFAULT_TIMEOUT_SECONDS = 1200.0

StrPath = Union[str, "PathLike[str]"]


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


# ============================================================================
# probe_video — ported from ffmpeg.ts::probeVideo and its helpers.
#
# See the JS source (packages/sonilo-video-kit/src/ffmpeg.ts) for the full
# rationale — "THE TIME MODEL" comment block there is the spec this section
# implements. Summary kept here only as an index into that reasoning:
#
#   D = E - O
#   D = the picture's end on the OUTPUT timeline (what we bill/mux to).
#   E = the picture's end on the INPUT timeline: max(timestamp + duration)
#       over the picture's own packets.
#   O = the REBASE ORIGIN: the input timestamp ffmpeg maps to output zero.
#       MPEG-TS/PS: the picture stream's own start_time (discontinuous clock).
#       Every file-based container: format.start_time.
#
# Tiers (cheapest first, each applied ONLY where its conversion into E is the
# IDENTITY — i.e. no nonzero correction is trusted from a source's stated
# convention; a nonzero correction is always MEASURED instead):
#   1. Matroska/WebM per-track DURATION tag (only when origin == 0).
#   2. The streams[].duration FIELD (only when start_time - origin == 0, and
#      the field isn't backfilled wholesale from the container's duration).
#   3. Measure E directly from the picture's own packets and rebase by O.
#   There is deliberately no tier 4: an undeterminable picture end raises.
# ============================================================================

_START_AT_ORIGIN_EPSILON = 1e-3


def _js_number(value: "str | None") -> float:
    """Mimic JS `Number(value)`: NaN on unparsable, 0 on empty string, NaN on None."""
    if value is None:
        return math.nan
    text = value.strip()
    if text == "":
        return 0.0
    try:
        return float(text)
    except ValueError:
        return math.nan


def _positive_seconds(value: "str | None") -> "float | None":
    if value is None:
        return None
    seconds = _js_number(value)
    return seconds if math.isfinite(seconds) and seconds > 0 else None


def _finite_seconds(value: "str | None") -> "float | None":
    """Any finite number of seconds, including zero and negatives — unlike
    `_positive_seconds`. `start_time` is legitimately 0 on almost every file."""
    if value is None:
        return None
    seconds = _js_number(value)
    return seconds if math.isfinite(seconds) else None


_DURATION_TAG_RE = re.compile(r"^(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)$")


def _parse_duration_value(value: str) -> "float | None":
    """`HH:MM:SS.nnnnnnnnn` (Matroska's per-stream DURATION tag) or plain seconds."""
    match = _DURATION_TAG_RE.match(value.strip())
    if match is None:
        return _positive_seconds(value)
    seconds = float(match.group(1)) * 3600 + float(match.group(2)) * 60 + float(match.group(3))
    return seconds if math.isfinite(seconds) and seconds > 0 else None


def _duration_tag_seconds(tags: "dict[str, Any] | None") -> "float | None":
    """Matroska/WebM carry each track's own length as a TAG (`DURATION`, or a
    language-suffixed `DURATION-eng`), authored per-track by the muxer — unlike
    the `duration` field, never synthesized from the container."""
    if tags is None:
        return None
    for key, value in tags.items():
        name = key.upper()
        if name != "DURATION" and not name.startswith("DURATION-"):
            continue
        seconds = _parse_duration_value(value) if isinstance(value, str) else None
        if seconds is not None:
            return seconds
    return None


def _parse_rational(value: "str | None") -> "float | None":
    if value is None:
        return None
    parts = value.split("/")
    numerator = parts[0]
    denominator = parts[1] if len(parts) > 1 else None
    n = _js_number(numerator)
    d = 1.0 if denominator is None else _js_number(denominator)
    if not math.isfinite(n) or not math.isfinite(d) or n <= 0 or d <= 0:
        return None
    return n / d


def _frame_tolerance(stream: dict) -> float:
    """How far a duration may legitimately sit from another measure of the same
    picture: the last frame is displayed for 1/fps. 0.5s when fps is unknown
    (itself a symptom — MPEG-TS reports avg_frame_rate=0/0)."""
    fps = _parse_rational(stream.get("avg_frame_rate")) or _parse_rational(stream.get("r_frame_rate"))
    if fps is None:
        return 0.5
    return min(max(1 / fps + 0.05, 0.05), 2)


def _frames_accounted_per_track(stream: dict) -> bool:
    """Does the demuxer account for this track's frames individually? A
    presence check only — see the JS comment for why `nb_frames /
    avg_frame_rate` is not a usable cross-check on the duration field."""
    return _positive_seconds(stream.get("nb_frames")) is not None


def _rebase_origin_seconds(format_: dict, stream: dict) -> float:
    """O: the input timestamp ffmpeg maps to output zero."""
    names = (format_.get("format_name") or "").split(",")
    discontinuous = any(n in ("mpegts", "mpegtsraw", "mpeg") for n in names)
    declared = (
        _finite_seconds(stream.get("start_time"))
        if discontinuous
        else _finite_seconds(format_.get("start_time"))
    )
    return declared if declared is not None else 0.0


def _is_zero(seconds: float) -> bool:
    return abs(seconds) <= _START_AT_ORIGIN_EPSILON


def _measure_picture_end(video: StrPath, stream_index: "int | None", ffprobe_path: str) -> "float | None":
    """E, measured: the picture's end on the input timeline, from its own
    packets. Demuxes, never decodes. Selects the picture by ABSOLUTE index,
    not `v:0`, so attached cover art in `v:0`'s slot cannot be selected
    instead of the genuine picture stream."""
    selector = str(stream_index) if stream_index is not None else "v:0"
    result = run_process(
        ffprobe_path,
        [
            "-v", "error",
            "-select_streams", selector,
            "-show_entries", "packet=pts_time,dts_time,duration_time",
            "-of", "csv=p=0",
            str(video),
        ],
    )
    end: "float | None" = None
    for line in result.stdout.split("\n"):
        if line == "":
            continue
        parts = line.split(",")
        pts_text = parts[0] if len(parts) > 0 else None
        dts_text = parts[1] if len(parts) > 1 else None
        dur_text = parts[2] if len(parts) > 2 else None
        pts = _js_number(pts_text)
        dts = _js_number(dts_text)
        # "N/A" -> NaN. AVI has no pts; prefer pts, fall back to dts.
        at = pts if math.isfinite(pts) else (dts if math.isfinite(dts) else None)
        if at is None:
            continue
        dur = _js_number(dur_text)
        until = at + (dur if math.isfinite(dur) and dur > 0 else 0)
        if end is None or until > end:
            end = until
    return end


def _picture_duration_seconds(
    video: StrPath,
    stream: dict,
    format_: dict,
    container_seconds: float,
    ffprobe_path: str,
) -> "float | None":
    """D: the picture's end on the output timeline. See the module-level time
    model comment. There is deliberately no tier 4 — callers raise instead of
    guessing when this returns None."""
    origin = _rebase_origin_seconds(format_, stream)
    tolerance = _frame_tolerance(stream)

    def plausible(seconds: "float | None") -> bool:
        # The picture can never outlive the container: format.duration is the
        # maximum over ALL streams, this one included.
        return seconds is not None and seconds > 0 and seconds <= container_seconds + tolerance

    # TIER 1 — the Matroska/WebM DURATION tag. Applied only when the origin is
    # zero, so the tag's "end position from container zero" convention needs
    # no correction.
    if _is_zero(origin):
        tag_end = _duration_tag_seconds(stream.get("tags"))
        if plausible(tag_end):
            return tag_end

    # TIER 2 — the per-stream `duration` FIELD. Applied only when
    # `start_time - origin == 0` (the identity correction), and the field
    # isn't a wholesale backfill from the container's own duration (a picture
    # whose packets are too sparse for libavformat to time individually).
    field = _positive_seconds(stream.get("duration"))
    stream_start = _finite_seconds(stream.get("start_time"))
    if stream_start is None:
        stream_start = 0.0
    field_correction = stream_start - origin
    backfilled_from_container = (
        field is not None
        and abs(field - container_seconds) <= tolerance
        and not _frames_accounted_per_track(stream)
    )
    if _is_zero(field_correction) and not backfilled_from_container and plausible(field):
        return field

    # TIER 3 — measure E from the picture's own packets, and rebase it.
    end = _measure_picture_end(video, stream.get("index"), ffprobe_path)
    if end is None:
        return None
    duration = end - origin
    return duration if duration > 0 else None


@dataclass
class VideoProbe:
    duration_seconds: "float | None"
    has_audio: bool
    audio_codec: "str | None"
    video_codec: "str | None"
    video_duration_seconds: "float | None"


def probe_video(video: StrPath, ffprobe_path: str = "ffprobe") -> VideoProbe:
    """Probe a video's container/stream metadata and the picture's own true
    duration (see the time-model comment above `_picture_duration_seconds`).

    Raises VideoKitError when the container's duration is invalid, or when a
    genuine picture stream is present but its duration cannot be determined —
    never guesses from another stream's timing."""
    result = run_process(
        ffprobe_path,
        ["-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(video)],
    )
    parsed = json.loads(result.stdout)
    format_ = parsed.get("format") or {}
    duration_seconds = _js_number(format_.get("duration"))
    # Non-positive/unreadable duration: fail loudly rather than let ffmpeg
    # exit 0 on a silent empty file.
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise VideoKitError(f"Could not determine a valid duration for {video}; refusing to render")

    streams = parsed.get("streams") or []
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    # A genuine picture, not embedded cover art (disposition.attached_pic=1,
    # the standard ID3/MP4 album-art tag). Must agree with mux_video_with_audio's
    # `-map 0:V` selector, which excludes exactly those streams too.
    video_stream = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video" and (s.get("disposition") or {}).get("attached_pic") != 1
        ),
        None,
    )

    video_duration_seconds: "float | None" = None
    if video_stream is not None:
        video_duration_seconds = _picture_duration_seconds(
            video, video_stream, format_, duration_seconds, ffprobe_path
        )
        if video_duration_seconds is None:
            raise VideoKitError(
                f"Could not determine how long the picture in {video} runs (its video stream "
                "carries no usable duration, no DURATION tag, and no timestamped packets). "
                "Refusing to guess: the ducking API bills on this figure, and the container's "
                "own duration is the longest of ALL its streams, so guessing from it can "
                "overcharge you. Re-encode the file (e.g. `ffmpeg -i in -c copy out.mp4`) and "
                "try again."
            )

    return VideoProbe(
        duration_seconds=duration_seconds,
        has_audio=audio_stream is not None,
        audio_codec=audio_stream.get("codec_name") if audio_stream is not None else None,
        video_codec=video_stream.get("codec_name") if video_stream is not None else None,
        video_duration_seconds=video_duration_seconds,
    )
