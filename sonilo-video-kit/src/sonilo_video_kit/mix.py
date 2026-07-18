"""mix_with_video (ported from mix.ts) — local ffmpeg loudness-matched mix."""
from __future__ import annotations

import math
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Union

from ._ffmpeg import StrPath, extract_audio, measure_integrated_lufs, probe_video, run_process
from .errors import VideoKitError
from .loudness import (
    DELIVERY_TARGET_LUFS,
    FALLBACK_MUSIC_LUFS,
    GAP_BELOW_VOICE_LU,
    MAX_DELIVERY_BOOST_DB,
    OUTPUT_CEILING_DBFS,
    db_to_linear,
    gap_gain,
    original_final_gain,
)

# ebur128 reports digital silence around its gate floor (-70 LUFS on modern
# ffmpeg) rather than -inf. An anchor that quiet means "no usable original
# signal" — anchoring to it would mute the music, so fall back to the same
# reference used when the video has no audio track at all.
_SILENCE_FLOOR_LUFS = -60.0

AudioInput = Union[StrPath, bytes, bytearray]


def _assert_slider(name: str, value: float) -> None:
    if not math.isfinite(value) or value < 0 or value > 1:
        raise VideoKitError(f"{name} must be between 0 and 1 (got {value})")


def mix_with_video(
    *,
    video: StrPath,
    audio: AudioInput,
    output: StrPath,
    music_volume: float = 0.5,
    original_volume: float = 1.0,
    loudness_match: bool = True,
    normalize: bool = True,
    ffmpeg_path: str = "ffmpeg",
    ffprobe_path: str = "ffprobe",
) -> str:
    if not video:
        raise VideoKitError("video is required")
    if not output:
        raise VideoKitError("output is required")
    _assert_slider("music_volume", music_volume)
    _assert_slider("original_volume", original_volume)

    output_path = Path(output)
    # Placed under the output's own parent dir (not the system temp dir) so a
    # leak here would show up right next to the render — and so cleanup is
    # never left to a shared tmp filesystem.
    work_dir = Path(tempfile.mkdtemp(prefix="sonilo-video-kit-", dir=str(output_path.parent)))
    try:
        # Music input: bytes are written to a temp file (ffmpeg needs a seekable input).
        if isinstance(audio, (str, os.PathLike)):
            music_path: StrPath = audio
        else:
            music_path = work_dir / "music.mp3"
            Path(music_path).write_bytes(bytes(audio))

        probe = probe_video(video, ffprobe_path)

        # Pre-extract original audio (never mix straight from the video input —
        # muxer deadlock risk on large files; see _ffmpeg.py::extract_audio).
        original_path: Optional[Path] = None
        if probe.has_audio and original_volume > 0:
            original_path = work_dir / "original.m4a"
            extract_audio(video, original_path, probe.audio_codec, ffmpeg_path)

        # Gains: matched path measures LUFS; any failure degrades to legacy
        # (slider = absolute gain), mirroring sonilo-web's never-throw analyzer.
        music_gain = music_volume
        original_gain = original_volume
        if loudness_match:
            music_lufs = measure_integrated_lufs(music_path, ffmpeg_path)
            raw_anchor = (
                measure_integrated_lufs(original_path, ffmpeg_path)
                if original_path is not None
                else FALLBACK_MUSIC_LUFS
            )
            anchor_lufs = (
                FALLBACK_MUSIC_LUFS
                if raw_anchor is not None and raw_anchor <= _SILENCE_FLOOR_LUFS
                else raw_anchor
            )
            if music_lufs is not None and anchor_lufs is not None:
                music_gain = gap_gain(anchor_lufs - GAP_BELOW_VOICE_LU, music_lufs, music_volume)
                original_gain = original_final_gain(original_volume)

        ceiling = f"{db_to_linear(OUTPUT_CEILING_DBFS):.6f}"
        limiter = f"alimiter=limit={ceiling}:level=disabled"
        mixed_path = work_dir / "mixed.mp4" if normalize else output_path
        # Cap audio to the probed video duration instead of -shortest: -shortest
        # truncates the picture to whichever input is shorter, which cuts the
        # video down to a too-short music track. atrim/apad instead pad short
        # music with silence and let ffmpeg cut only excess audio.
        dur = f"{probe.duration_seconds:.3f}"

        if original_path is not None:
            inputs = ["-i", str(video), "-i", str(music_path), "-i", str(original_path)]
            filter_ = (
                f"[1:a]volume={music_gain:.6f}[m];"
                f"[2:a]volume={original_gain:.6f}[o];"
                f"[m][o]amix=inputs=2:duration=longest:normalize=0,"
                f"atrim=end={dur},asetpts=N/SR/TB,apad=whole_dur={dur},{limiter}[aout]"
            )
        else:
            inputs = ["-i", str(video), "-i", str(music_path)]
            filter_ = (
                f"[1:a]volume={music_gain:.6f},atrim=end={dur},asetpts=N/SR/TB,"
                f"apad=whole_dur={dur},{limiter}[aout]"
            )

        run_process(
            ffmpeg_path,
            [
                "-y", *inputs,
                "-filter_complex", filter_,
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac",
                str(mixed_path),
            ],
        )

        if normalize:
            _delivery_normalize(mixed_path, output_path, ffmpeg_path)
        return str(output_path)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _delivery_normalize(in_path: Path, out_path: Path, ffmpeg_path: str) -> None:
    """One static gain pass to land the finished file on DELIVERY_TARGET_LUFS.
    Static volume, never dynamic loudnorm (it would breathe). Best-effort:
    any failure keeps the un-normalized render."""
    try:
        lufs = measure_integrated_lufs(in_path, ffmpeg_path)
        if lufs is None:
            shutil.copyfile(in_path, out_path)
            return
        gain_db = min(DELIVERY_TARGET_LUFS - lufs, MAX_DELIVERY_BOOST_DB)
        if abs(gain_db) < 0.1:
            shutil.copyfile(in_path, out_path)
            return
        ceiling = f"{db_to_linear(OUTPUT_CEILING_DBFS):.6f}"
        run_process(
            ffmpeg_path,
            [
                "-y", "-i", str(in_path),
                "-c:v", "copy",
                "-af", f"volume={gain_db:.2f}dB,alimiter=limit={ceiling}:level=disabled",
                "-c:a", "aac",
                str(out_path),
            ],
        )
    except Exception:
        shutil.copyfile(in_path, out_path)
