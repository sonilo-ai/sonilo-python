"""duck_music_under_speech: orchestration + rescue (ported from duck.ts).

Ducks generated/supplied music under the speech already present in a video.
The ducking itself runs on the Sonilo API — a PAID endpoint, metered on the
uploaded voice track's duration. Only the extracted audio track is uploaded
(trimmed to the picture's length, so the billed duration equals the
delivered one); the picture stays local and is copied, never re-encoded.

Preconditions the API cannot satisfy (no audio track, no picture, a video or
music track longer than MAX_DUCKING_DURATION_SECONDS) — and preconditions
the local mux and filesystem cannot satisfy (an `output` with no extension,
or in a directory that does not exist or is not writable) — throw before
anything is uploaded, and so before anything is charged. There is
deliberately no fallback to mix_with_video: a caller who asked for ducking
must never silently receive an un-ducked file.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import NoReturn, Optional, Union

from ._ducking_api import (
    DuckingClient,
    await_ducking_result,
    download_ducked_mix,
    submit_ducking_job,
)
from ._ffmpeg import StrPath, extract_audio, mux_video_with_audio, probe_mux_feasibility, probe_video
from .errors import DuckingFailedError, VideoKitError

# The ducking API rejects voice, video, and music tracks longer than this.
MAX_DUCKING_DURATION_SECONDS = 360

# Absolute hard ceiling on the ducked-mix download — the anti-DoS floor that a
# hostile/compromised/MITM'd R2 host CANNOT raise. The kit only ever uploads
# an extracted audio track (<= MAX_DUCKING_DURATION_SECONDS), so the finished
# artifact is always an audio wav of at most a few dozen MB; 300 MB is
# generous headroom. The server's own expected size (output_bytes) is
# additionally clamped UNDER this ceiling in effective_download_cap; this
# constant is the last-resort bound that holds even when output_bytes is
# absent or the server itself is lying.
MAX_DUCKED_MIX_BYTES = 300 * 1024 * 1024

# Slack allowed above the server's exact `output_bytes` before a download is
# treated as an anomaly. A FIXED 64 KB, not a percentage: the authenticated
# channel gave us the EXACT artifact size, so the only legitimate excess is
# negligible container/transfer framing overhead.
_OUTPUT_BYTES_MARGIN = 64 * 1024

_DEFAULT_POLL_INTERVAL_SECONDS = 2.0
_DEFAULT_TIMEOUT_SECONDS = 10 * 60.0

AudioInput = Union[bytes, bytearray, StrPath]


def effective_download_cap(output_bytes: Optional[int]) -> int:
    """The cap actually enforced on the download. With the server's
    authenticated `output_bytes`, a body more than a hair over it is an
    anomaly and is rejected even though it sits under the hard ceiling;
    without it (older backend, or a non-positive/wrong-typed value), only
    the hard ceiling applies."""
    if isinstance(output_bytes, int) and not isinstance(output_bytes, bool) and output_bytes > 0:
        return min(output_bytes + _OUTPUT_BYTES_MARGIN, MAX_DUCKED_MIX_BYTES)
    return MAX_DUCKED_MIX_BYTES


def _default_client() -> DuckingClient:
    from sonilo import Sonilo

    from sonilo_video_kit._version import __version__

    # Only the kit's own default client is tagged; a caller-supplied client
    # keeps whatever identity its owner gave it.
    return Sonilo(client_name="kit-python-video", client_version=__version__)


def _paid_note(task_id: str) -> str:
    """Plain words for "the API has run, you have been billed, and the mix
    is still yours" — the sentence every post-submit failure has to end
    with."""
    return (
        f"You have ALREADY BEEN CHARGED for ducking task {task_id}: the API bills at submit, "
        "and the task keeps running to completion server-side no matter what happens to this "
        "call. Do not call duck_music_under_speech again for this video -- that submits a NEW "
        f"task and charges you a second time. Poll GET /v1/tasks/{task_id} instead (with the "
        'same client) until it reports "succeeded", and download the output_url it hands back: '
        "that is a re-fetch of the mix you have paid for, not a new charge."
    )


def _rethrow_with_task_id(err: BaseException, task_id: str) -> BaseException:
    """Anything that goes wrong after a successful submit has to carry the
    task id out with it — the mix is paid for, finished, and sitting in R2;
    losing the id would leave re-running (and re-charging) as the only way
    forward. DuckingFailedError is passed through untouched: there the
    SERVER's own processing failed, so there is no finished mix to re-fetch
    and its own `refunded` flag already reports the charge."""
    if isinstance(err, DuckingFailedError):
        return err
    reason = str(err)
    return VideoKitError(
        f"The ducking API ran, but the finished mix could not be collected: {reason}. "
        f"{_paid_note(task_id)}",
        cause=err,
    )


def _free_rescue_path(output: Path) -> Path:
    """Where to rescue the paid mix to, without ever clobbering a rescued
    mix from an EARLIER failed run: `<output>.ducked.wav` may already hold
    an irreplaceable, paid-for mix this call did not write."""
    candidates = [output.with_name(f"{output.name}.ducked.wav")]
    for n in range(1, 51):
        candidates.append(output.with_name(f"{output.name}.ducked.{n}.wav"))
    candidates.append(output.with_name(f"{output.name}.ducked.{uuid.uuid4().hex}.wav"))
    for candidate in candidates:
        if not candidate.exists():
            return candidate
    return candidates[-1]


def _place_atomically(source_path: "StrPath", dest_path: Path) -> None:
    """Copy `source_path` to `dest_path` without ever leaving a truncated
    file at `dest_path`: copy to a sibling temp file in the same directory
    (same filesystem, so the rename can't EXDEV) and rename it into place."""
    tmp_path = dest_path.parent / f".{dest_path.name}.{uuid.uuid4().hex}.tmp"
    try:
        shutil.copyfile(source_path, tmp_path)
        os.replace(tmp_path, dest_path)
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def _rescue_and_raise(
    stage: str, cause: BaseException, ducked_path: Path, output: Path, task_id: str
) -> NoReturn:
    """The ducking API call that produced `ducked_path` has already been
    billed on the video's duration, so any failure between "the mix is
    downloaded" and "the mix is safely at `output`" (a mux that can't hold
    the video's codec, a full disk, a missing/read-only output directory)
    must not also destroy that paid-for mix. Copy it next to `output`
    before re-raising, and say so in the thrown error."""
    reason = str(cause)
    recovered_path = output.with_name(f"{output.name}.ducked.wav")
    try:
        recovered_path = _free_rescue_path(output)
        _place_atomically(ducked_path, recovered_path)
        rescue_note = (
            f"The ducked audio was saved to {recovered_path} so you can recover it locally "
            "(e.g. retry the mux, or move the file into place yourself) instead of calling "
            "duck_music_under_speech again, which would incur another charge. You have already "
            f"been charged for ducking task {task_id}."
        )
    except Exception as rescue_err:  # noqa: BLE001 - folded into the raised error below
        rescue_reason = str(rescue_err)
        rescue_note = (
            f"Attempting to also save the ducked audio to {recovered_path} ALSO failed "
            f"({rescue_reason}), so the mix could not be recovered locally. {_paid_note(task_id)}"
        )
    raise VideoKitError(
        f"{stage} failed, after the ducking API had already run and been billed for this "
        f"video's duration. {rescue_note} Original error: {reason}",
        cause=cause,
    ) from cause


def duck_music_under_speech(
    *,
    video: StrPath,
    audio: AudioInput,
    output: StrPath,
    client: Optional[DuckingClient] = None,
    poll_interval: float = _DEFAULT_POLL_INTERVAL_SECONDS,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ffmpeg_path: str = "ffmpeg",
    ffprobe_path: str = "ffprobe",
) -> str:
    if not video:
        raise VideoKitError("video is required")
    if not output:
        raise VideoKitError("output is required")

    output_path = Path(output)
    # A `output` with no extension leaves ffmpeg with no way to infer a
    # muxer for the temp mux target later. Knowable now — and only now is
    # it free: by mux time the API call has already been billed.
    output_extension = output_path.suffix
    if len(output_extension) < 2:
        suggestion = str(output_path).rstrip(".")
        raise VideoKitError(
            f'output "{output}" has no file extension, so ffmpeg cannot tell which container '
            f'to write. Give it one (e.g. "{suggestion}.mp4").'
        )

    # `output`'s directory has to exist and be writable, and this is the
    # moment it is free to say so: without this guard the job would be
    # submitted, the account CHARGED, the mux would succeed -- and only then
    # would placement (and the rescue, which writes next to `output`) fail.
    output_dir = output_path.parent
    if not os.path.isdir(output_dir) or not os.access(output_dir, os.W_OK):
        raise VideoKitError(
            f'output "{output}" is in a directory that does not exist or cannot be written to '
            f'({output_dir}). Create it first (e.g. `mkdir -p {output_dir}`): the ducking API '
            "is billed at submit, so discovering this after the call would cost you the charge "
            "AND leave nowhere to put the mix you paid for."
        )

    if isinstance(audio, (bytes, bytearray)):
        if len(audio) == 0:
            raise VideoKitError("audio is required")
    elif not audio:
        raise VideoKitError("audio is required")

    # Guards run before the client is constructed: an unusable video reports
    # the real problem even when SONILO_API_KEY is unset, and nothing is
    # uploaded or charged for an input the API would reject anyway.
    probe = probe_video(video, ffprobe_path)
    if not probe.has_audio:
        raise VideoKitError(
            f"{video} has no audio track, so there is no speech to duck under. "
            "Use mix_with_video to lay music over a silent video."
        )
    video_duration = probe.video_duration_seconds
    if video_duration is None:
        raise VideoKitError(
            f"{video} has no video stream (embedded cover art does not count), so there is no "
            "picture to mux the ducked audio back onto. Duck an audio-only file with the "
            "ducking API directly, or pass a real video."
        )
    # Guard, bill, and mux on the PICTURE's duration, never the container's
    # (format.duration is the maximum over all streams): the server bills
    # the uploaded voice track, and the deliverable is only as long as the
    # picture.
    if video_duration > MAX_DUCKING_DURATION_SECONDS:
        raise VideoKitError(
            f"{video} runs {video_duration:.1f}s; the ducking API accepts at most "
            f"{MAX_DUCKING_DURATION_SECONDS}s. Use mix_with_video for longer videos."
        )

    work_dir = Path(tempfile.mkdtemp(prefix="sonilo-video-kit-duck-"))
    try:
        # Can the picture actually be stream-copied into the caller's
        # container? probe_video succeeding does not prove it: dry-run the
        # real mux shape here, BEFORE the client is constructed, so an
        # unmuxable video is reported before anything is charged.
        feasibility = probe_mux_feasibility(
            video, work_dir / f"feasibility{output_extension}", ffmpeg_path
        )
        if not feasibility.ok:
            codec = probe.video_codec or "its video stream"
            raise VideoKitError(
                f'{video}\'s picture ({codec}) cannot be stream-copied into a '
                f'"{output_extension}" container, so muxing the ducked audio back onto it '
                "would fail. duck_music_under_speech never re-encodes your picture, so the "
                "container has to be able to hold it as it is. Try a different output "
                'extension (e.g. ".mkv" or ".mp4"), or re-encode the video first '
                "(e.g. `ffmpeg -i in -c:v libx264 -c:a copy fixed.mp4`). Refused before the "
                f"ducking API was called, so you have NOT been charged. ffmpeg said: "
                f"{feasibility.reason}"
            )

        # The music obeys the same cap as the video (the server applies it
        # too), so probe it here rather than uploading up to 300 MB the
        # server would only reject.
        if isinstance(audio, (str, os.PathLike)):
            music_path: StrPath = audio
        else:
            music_path = work_dir / "music.mp3"
            Path(music_path).write_bytes(bytes(audio))

        music_probe = probe_video(music_path, ffprobe_path)
        music_duration = music_probe.duration_seconds or 0.0
        if music_duration > MAX_DUCKING_DURATION_SECONDS:
            raise VideoKitError(
                f"The music runs {music_duration:.1f}s; the ducking API accepts at most "
                f"{MAX_DUCKING_DURATION_SECONDS}s. Use a shorter music track."
            )

        active_client: DuckingClient = client if client is not None else _default_client()

        # Upload the audio track, never the picture. Trimmed to the
        # picture's length: the server bills exactly what it is given, and
        # the deliverable stays as long as the picture, so trimming here
        # makes the billed duration equal the delivered duration.
        voice_path = work_dir / "voice.m4a"
        extract_audio(video, voice_path, probe.audio_codec, ffmpeg_path, video_duration)

        # THE ACCOUNT IS CHARGED HERE. From this line on, every failure
        # (a poll that errors, a download that stays broken, a timeout) is a
        # failure that costs the customer money while the task keeps
        # running server-side. Nothing below may throw away the task id.
        task_id = submit_ducking_job(active_client, voice_path, music_path)

        ducked_path = work_dir / "ducked.wav"
        try:
            # ONE deadline governs the WHOLE post-submit collection: the
            # caller's timeout is the budget for polling AND the download
            # together, not a fresh full timeout for each.
            overall_deadline = time.monotonic() + timeout
            result = await_ducking_result(
                active_client,
                task_id,
                poll_interval=poll_interval,
                timeout=timeout,
                deadline=overall_deadline,
            )
            # Only an extracted audio track is ever uploaded, so the server
            # should never answer with anything but "audio".
            if result.output_type != "audio":
                raise VideoKitError(
                    f'The ducking API returned output_type "{result.output_type}" for task '
                    f'{task_id}, but only "audio" is expected: this client always uploads '
                    "just the extracted audio track, never the picture."
                )
            download_ducked_mix(
                result.output_url,
                ducked_path,
                max_bytes=effective_download_cap(result.output_bytes),
                expected_bytes=result.output_bytes,
                deadline=overall_deadline,
            )
        except Exception as err:
            raise _rethrow_with_task_id(err, task_id) from err

        # Mux into work_dir first, never straight to `output`: a failure
        # partway through would otherwise leave a truncated file where the
        # caller expects a deliverable.
        muxed_path = work_dir / f"muxed{output_extension}"
        stage = f"Muxing the ducked audio onto {video}"
        try:
            mux_video_with_audio(video, ducked_path, muxed_path, video_duration, ffmpeg_path)
            stage = f"Placing the finished mix at {output}"
            _place_atomically(muxed_path, output_path)
        except Exception as err:
            _rescue_and_raise(stage, err, ducked_path, output_path, task_id)

        return str(output_path)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
