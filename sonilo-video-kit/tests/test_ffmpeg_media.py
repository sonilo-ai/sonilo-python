import subprocess
import pytest
from sonilo_video_kit._ffmpeg import (
    measure_integrated_lufs, extract_audio, probe_mux_feasibility, mux_video_with_audio,
)


def _ff(args):
    subprocess.run(["ffmpeg", "-y", *args], check=True, capture_output=True)


def test_measure_lufs_returns_float(tmp_path):
    a = tmp_path / "a.wav"
    _ff(["-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(a)])
    val = measure_integrated_lufs(a)
    assert isinstance(val, float)


def test_measure_lufs_none_on_bad_input(tmp_path):
    bad = tmp_path / "nope.wav"
    bad.write_bytes(b"not audio")
    assert measure_integrated_lufs(bad) is None


def test_extract_audio(tmp_path):
    v = tmp_path / "av.mp4"
    _ff(["-f", "lavfi", "-i", "testsrc=duration=2:size=128x128:rate=15",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-shortest", "-pix_fmt", "yuv420p", str(v)])
    out = tmp_path / "out.m4a"
    extract_audio(v, out, "aac")
    assert out.exists() and out.stat().st_size > 0


def test_mux_feasibility_ok(tmp_path):
    v = tmp_path / "av.mp4"
    _ff(["-f", "lavfi", "-i", "testsrc=duration=1:size=128x128:rate=15",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-shortest", "-pix_fmt", "yuv420p", str(v)])
    res = probe_mux_feasibility(v, tmp_path / "probe.mp4")
    assert res.ok is True


def test_mux_video_with_audio(tmp_path):
    v = tmp_path / "av.mp4"
    _ff(["-f", "lavfi", "-i", "testsrc=duration=2:size=128x128:rate=15",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-shortest", "-pix_fmt", "yuv420p", str(v)])
    a = tmp_path / "music.wav"
    _ff(["-f", "lavfi", "-i", "sine=frequency=220:duration=2", str(a)])
    out = tmp_path / "final.mp4"
    mux_video_with_audio(v, a, out, 2.0)
    assert out.exists() and out.stat().st_size > 0
