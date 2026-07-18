from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sonilo.errors import SoniloError
from sonilo.types import Segment

DEFAULT_FILENAME = "video.mp4"


def build_t2m_data(
    prompt: str, duration: int, segments: Optional[List[Segment]]
) -> Dict[str, str]:
    data = {"prompt": prompt, "duration": str(duration)}
    if segments is not None:
        data["segments"] = json.dumps(segments)
    return data


def build_t2m_async_data(
    prompt: str,
    duration: int,
    segments: Optional[List[Segment]],
    mode: Optional[str],
    output_format: Optional[str],
) -> Dict[str, str]:
    data = build_t2m_data(prompt, duration, segments)
    resolved = mode or "async"
    if resolved != "async":
        raise SoniloError("text-to-music submit() requires mode='async'")
    data["mode"] = resolved
    if output_format is not None:
        data["output_format"] = output_format
    return data


def normalize_video(video: Any) -> Tuple[str, Any, bool]:
    """Normalize a video input into (filename, httpx-uploadable, opened_here).

    Accepts a filesystem path (str/Path — opened for streaming upload; the
    caller must close it, signalled by opened_here=True), raw bytes, or a
    binary file-like object.
    """
    if isinstance(video, (str, Path)):
        path = Path(video)
        return path.name or DEFAULT_FILENAME, path.open("rb"), True
    if isinstance(video, bytes):
        return DEFAULT_FILENAME, video, False
    if hasattr(video, "read"):
        raw_name = getattr(video, "name", None)
        filename = Path(raw_name).name if isinstance(raw_name, str) and raw_name else DEFAULT_FILENAME
        return filename, video, False
    raise SoniloError("Unsupported video input: pass a path, bytes, or a binary file object")


def build_v2m_parts(
    video: Any,
    video_url: Optional[str],
    prompt: Optional[str],
    segments: Optional[List[Segment]],
) -> Tuple[Dict[str, str], Optional[Dict[str, tuple]], bool]:
    if (video is None) == (video_url is None):
        raise SoniloError("Provide exactly one of video or video_url")

    # Assemble data dict completely before opening any files
    data: Dict[str, str] = {}
    if video_url is not None:
        data["video_url"] = video_url  # type: ignore[assignment]
    if prompt is not None:
        data["prompt"] = prompt
    if segments is not None:
        data["segments"] = json.dumps(segments)

    # Now open files (only after data is fully assembled)
    files: Optional[Dict[str, tuple]] = None
    opened = False
    if video is not None:
        filename, fileobj, opened = normalize_video(video)
        files = {"video": (filename, fileobj, "video/mp4")}

    return data, files, opened


def _resolve_music_mode(
    mode: Optional[str],
    isolate_vocals: Optional[bool],
    preserve_speech: Optional[bool] = None,
    output_format: Optional[str] = None,
    ducking: Optional[bool] = None,
) -> str:
    """isolate_vocals/preserve_speech/ducking/output_format='wav' only work
    with async processing: auto-select mode "async" when the caller didn't
    specify one, but fail fast if they explicitly asked for anything else.
    submit() also needs an async response (a task_id ack, not a stream), so
    "async" is the default regardless.
    """
    needs_async = (
        bool(isolate_vocals)
        or bool(preserve_speech)
        or output_format == "wav"
        or ducking is not None
    )
    if needs_async and mode is not None and mode != "async":
        raise SoniloError(
            "isolate_vocals/preserve_speech/ducking/output_format='wav' "
            "require mode='async'"
        )
    return "async" if needs_async else (mode or "async")


def build_v2m_async_parts(
    video: Any,
    video_url: Optional[str],
    prompt: Optional[str],
    segments: Optional[List[Segment]],
    mode: Optional[str],
    isolate_vocals: Optional[bool],
    preserve_speech: Optional[bool] = None,
    output_format: Optional[str] = None,
    ducking: Optional[bool] = None,
) -> Tuple[Dict[str, str], Optional[Dict[str, tuple]], bool]:
    """Like build_v2m_parts, plus the async-only fields for the
    video-to-music submit()/generate_async() path."""
    resolved_mode = _resolve_music_mode(
        mode, isolate_vocals, preserve_speech, output_format, ducking
    )
    data, files, opened = build_v2m_parts(video, video_url, prompt, segments)
    data["mode"] = resolved_mode
    if isolate_vocals is not None:
        data["isolate_vocals"] = "true" if isolate_vocals else "false"
    if preserve_speech is not None:
        data["preserve_speech"] = "true" if preserve_speech else "false"
    if output_format is not None:
        data["output_format"] = output_format
    if ducking is not None:
        data["ducking"] = "true" if ducking else "false"
    return data, files, opened


def build_v2v_music_parts(
    video: Any,
    video_url: Optional[str],
    prompt: Optional[str],
    preserve_speech: Optional[bool],
    isolate_vocals: Optional[bool],
) -> Tuple[Dict[str, str], Optional[Dict[str, tuple]], bool]:
    data, files, opened = build_v2m_parts(video, video_url, prompt, None)
    if preserve_speech is not None:
        data["preserve_speech"] = "true" if preserve_speech else "false"
    if isolate_vocals is not None:
        data["isolate_vocals"] = "true" if isolate_vocals else "false"
    return data, files, opened


def build_v2v_sfx_parts(
    video: Any,
    video_url: Optional[str],
    prompt: Optional[str],
    segments: Optional[List[Segment]],
) -> Tuple[Dict[str, str], Optional[Dict[str, tuple]], bool]:
    # build_v2m_parts JSON-serializes `segments` — fine for SFX start/end segments too.
    return build_v2m_parts(video, video_url, prompt, segments)


def build_sfx_t2s_data(
    prompt: str, duration: int, audio_format: Optional[str]
) -> Dict[str, str]:
    data = {"prompt": prompt, "duration": str(duration)}
    if audio_format is not None:
        data["audio_format"] = audio_format
    return data


def build_sfx_v2s_parts(
    video: Any,
    video_url: Optional[str],
    prompt: Optional[str],
    segments: Optional[List[Segment]],
    audio_format: Optional[str],
) -> Tuple[Dict[str, str], Optional[Dict[str, tuple]], bool]:
    data, files, opened = build_v2m_parts(video, video_url, prompt, segments)
    if audio_format is not None:
        data["audio_format"] = audio_format
    return data, files, opened
