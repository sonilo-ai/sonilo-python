from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sonilo.errors import SoniloError
from sonilo.types import Segment, SfxSegment

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
    variants_num: Optional[int] = None,
) -> Dict[str, str]:
    data = build_t2m_data(prompt, duration, segments)
    resolved = mode or "async"
    if resolved != "async":
        raise SoniloError("text-to-music submit() requires mode='async'")
    data["mode"] = resolved
    if output_format is not None:
        data["output_format"] = output_format
    if variants_num is not None:
        data["variants_num"] = str(variants_num)
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
    *,
    prompt_influence: Optional[float] = None,
) -> Tuple[Dict[str, str], Optional[Dict[str, tuple]], bool]:
    """`prompt_influence` is keyword-only with a None default because this
    builder is shared: only the two music endpoints (video-to-music and, via
    build_v2v_music_parts, video-to-video-music) accept it, and every other
    caller simply never passes it — the same pattern as output_format /
    keep_original_sound on build_v2s_parts."""
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
    # Omitted when unset so the API's own default (0.5) applies. `is not None`,
    # not truthiness: 0.0 is a meaningful value ("let the video lead entirely")
    # and must go on the wire.
    if prompt_influence is not None:
        data["prompt_influence"] = str(prompt_influence)

    # Now open files (only after data is fully assembled)
    files: Optional[Dict[str, tuple]] = None
    opened = False
    if video is not None:
        filename, fileobj, opened = normalize_video(video)
        files = {"video": (filename, fileobj, "video/mp4")}

    return data, files, opened


def build_dubbing_parts(
    video: Any,
    video_url: Optional[str],
    languages: Optional[List[str]],
    ducking: Optional[bool] = None,
) -> Tuple[Dict[str, str], Optional[Dict[str, tuple]], bool]:
    """Build the multipart parts for POST /v1/dubbing.

    `languages` travels as one opaque form field holding a JSON array string —
    that is the shape the backend parses. It is omitted entirely when unset so
    the server default (["zh_cn", "es", "fr"]) applies; an empty array would be
    rejected as a malformed payload instead.

    The https check is local because it is a guaranteed server-side 422: the
    dubbing pipeline fetches the source URL itself and requires https
    specifically, unlike the fal-backed endpoints, which also accept plain
    http. Language codes are deliberately NOT checked here — the backend owns
    that list, and a hardcoded copy would make this SDK reject codes added
    later.
    """
    if (video is None) == (video_url is None):
        raise SoniloError("Provide exactly one of video or video_url")

    # Assemble data dict completely before opening any files
    data: Dict[str, str] = {}
    if video_url is not None:
        if not video_url.lower().startswith("https://"):
            raise SoniloError(
                "video_url must use https — the dubbing pipeline requires an https URL"
            )
        data["video_url"] = video_url
    if languages is not None:
        data["languages"] = json.dumps(languages)
    # Default-OFF server-side, like every other endpoint's ducking: omitted
    # when unset so the server default applies.
    if ducking is not None:
        data["ducking"] = "true" if ducking else "false"

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
    variants_num: Optional[int] = None,
) -> str:
    """isolate_vocals/preserve_speech/ducking/a non-m4a output_format/
    variants_num>1 only work with async processing: auto-select mode "async"
    when the caller didn't specify one, but fail fast if they explicitly
    asked for anything else. submit() also needs an async response (a
    task_id ack, not a stream), so "async" is the default regardless.
    """
    needs_async = (
        bool(isolate_vocals)
        or bool(preserve_speech)
        # Any non-m4a container is a finalize-time transcode, so it needs
        # async. Testing != "m4a" rather than == "wav" keeps this correct as
        # formats are added (mp3 landed after the original check).
        or (output_format is not None and output_format != "m4a")
        or ducking is not None
        or (variants_num is not None and variants_num > 1)
    )
    if needs_async and mode is not None and mode != "async":
        raise SoniloError(
            "isolate_vocals/preserve_speech/ducking/output_format other "
            "than 'm4a'/variants_num>1 require mode='async'"
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
    variants_num: Optional[int] = None,
    prompt_influence: Optional[float] = None,
) -> Tuple[Dict[str, str], Optional[Dict[str, tuple]], bool]:
    """Like build_v2m_parts, plus the async-only fields for the
    video-to-music submit()/generate_async() path.

    `prompt_influence` is NOT async-only — it is an upstream generation
    parameter, valid on stream and async alike — so it lives in
    build_v2m_parts and takes no part in _resolve_music_mode."""
    resolved_mode = _resolve_music_mode(
        mode, isolate_vocals, preserve_speech, output_format, ducking, variants_num
    )
    data, files, opened = build_v2m_parts(
        video, video_url, prompt, segments, prompt_influence=prompt_influence
    )
    data["mode"] = resolved_mode
    if isolate_vocals is not None:
        data["isolate_vocals"] = "true" if isolate_vocals else "false"
    if preserve_speech is not None:
        data["preserve_speech"] = "true" if preserve_speech else "false"
    if output_format is not None:
        data["output_format"] = output_format
    if ducking is not None:
        data["ducking"] = "true" if ducking else "false"
    if output_format is not None:
        data["output_format"] = output_format
    if variants_num is not None:
        data["variants_num"] = str(variants_num)
    return data, files, opened


def build_v2v_music_parts(
    video: Any,
    video_url: Optional[str],
    prompt: Optional[str],
    preserve_speech: Optional[bool],
    isolate_vocals: Optional[bool],
    variants_num: Optional[int] = None,
    segments: Optional[List[Segment]] = None,
    ducking: Optional[bool] = None,
    keep_original_sound: Optional[bool] = None,
    prompt_influence: Optional[float] = None,
) -> Tuple[Dict[str, str], Optional[Dict[str, tuple]], bool]:
    # video-to-video-music is 202/async-only by design (there is no streaming
    # mode to fall back to), so variants_num travels straight through with no
    # mode guard — unlike text-to-music/video-to-music.
    data, files, opened = build_v2m_parts(
        video, video_url, prompt, segments, prompt_influence=prompt_influence
    )
    # Every boolean is emitted only when explicitly passed, so the server's own
    # default stands. `ducking` and `keep_original_sound` are both default-OFF
    # today, but neither is pinned here — hardcoding either is what would have
    # to change the next time a server default moves.
    if keep_original_sound is not None:
        data["keep_original_sound"] = "true" if keep_original_sound else "false"
    if ducking is not None:
        data["ducking"] = "true" if ducking else "false"
    if preserve_speech is not None:
        data["preserve_speech"] = "true" if preserve_speech else "false"
    if isolate_vocals is not None:
        data["isolate_vocals"] = "true" if isolate_vocals else "false"
    if variants_num is not None:
        data["variants_num"] = str(variants_num)
    return data, files, opened


def build_v2v_sfx_parts(
    video: Any,
    video_url: Optional[str],
    prompt: Optional[str],
    segments: Optional[List[Segment]],
) -> Tuple[Dict[str, str], Optional[Dict[str, tuple]], bool]:
    # build_v2m_parts JSON-serializes `segments` — fine for SFX start/end segments too.
    return build_v2m_parts(video, video_url, prompt, segments)


def build_v2s_parts(
    video: Any,
    video_url: Optional[str],
    music_prompt: Optional[str],
    sfx_prompt: Optional[str],
    segments: Optional[List[SfxSegment]],
    preserve_speech: Optional[bool],
    ducking: Optional[bool],
    variants_num: Optional[int] = None,
    output_format: Optional[str] = None,
    keep_original_sound: Optional[bool] = None,
) -> Tuple[Dict[str, str], Optional[Dict[str, tuple]], bool]:
    """Multipart parts shared by /v1/video-to-sound and
    /v1/video-to-video-sound.

    Two fields they do NOT share, one in each direction. Both are keyword-only
    with a None default here, and the resource that must not send one simply
    never passes it:

    * `output_format` is audio-only — video-to-video-sound always muxes the mix
      into an mp4 — so VideoToVideoSound never passes it.
    * `keep_original_sound` is video-only — it only means something when the
      deliverable is a video whose own audio could be preserved — so
      VideoToSound never passes it.

    These endpoints take `music_prompt`/`sfx_prompt` instead of a single
    `prompt`, so build_v2m_parts is called with prompt=None. Booleans are only
    emitted when explicitly passed, so the server's own default stands;
    `ducking` and `keep_original_sound` are both default-OFF today and neither
    is pinned here. Note `ducking` means more on /v1/video-to-sound than on the
    video endpoint: with no `keep_original_sound` field there, it picks the
    voice source as well as the mix, so leaving it unset keeps the source's own
    speech out of the deliverable entirely. Both endpoints are async-only (202
    + poll), so — like
    video-to-video-music — variants_num travels straight through with no mode
    guard.
    """
    data, files, opened = build_v2m_parts(video, video_url, None, segments)
    if music_prompt is not None:
        data["music_prompt"] = music_prompt
    if sfx_prompt is not None:
        data["sfx_prompt"] = sfx_prompt
    if keep_original_sound is not None:
        data["keep_original_sound"] = "true" if keep_original_sound else "false"
    if preserve_speech is not None:
        data["preserve_speech"] = "true" if preserve_speech else "false"
    if ducking is not None:
        data["ducking"] = "true" if ducking else "false"
    if output_format is not None:
        data["output_format"] = output_format
    if variants_num is not None:
        data["variants_num"] = str(variants_num)
    return data, files, opened


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
