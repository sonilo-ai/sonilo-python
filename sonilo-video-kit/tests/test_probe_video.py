import subprocess
import pytest
from sonilo_video_kit._ffmpeg import probe_video


def _make(path, args):
    subprocess.run(["ffmpeg", "-y", *args, str(path)], check=True,
                   capture_output=True)


def test_probe_video_with_audio(tmp_path):
    v = tmp_path / "av.mp4"
    _make(v, ["-f", "lavfi", "-i", "testsrc=duration=2:size=128x128:rate=15",
              "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
              "-shortest", "-pix_fmt", "yuv420p"])
    p = probe_video(v)
    assert p.has_audio is True
    assert p.video_codec is not None
    assert p.audio_codec is not None
    assert p.video_duration_seconds == pytest.approx(2.0, abs=0.5)


def test_probe_video_without_audio(tmp_path):
    v = tmp_path / "v.mp4"
    _make(v, ["-f", "lavfi", "-i", "testsrc=duration=1:size=128x128:rate=15",
              "-pix_fmt", "yuv420p"])
    p = probe_video(v)
    assert p.has_audio is False
