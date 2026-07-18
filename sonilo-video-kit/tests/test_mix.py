import subprocess
from pathlib import Path
from sonilo_video_kit import mix_with_video
from sonilo_video_kit._ffmpeg import probe_video


def _ff(args):
    subprocess.run(["ffmpeg", "-y", *args], check=True, capture_output=True)


def _video_with_audio(p):
    _ff(["-f", "lavfi", "-i", "testsrc=duration=3:size=160x120:rate=15",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-shortest", "-pix_fmt", "yuv420p", str(p)])


def test_mix_produces_video_with_audio(tmp_path):
    v = tmp_path / "in.mp4"; _video_with_audio(v)
    music = tmp_path / "music.wav"
    _ff(["-f", "lavfi", "-i", "sine=frequency=220:duration=3", str(music)])
    out = tmp_path / "out.mp4"
    res = mix_with_video(video=v, audio=music, output=out)
    assert Path(res) == out and out.exists()
    p = probe_video(out)
    assert p.has_audio is True
    assert p.video_codec is not None  # picture preserved (stream-copied)


def test_mix_accepts_audio_bytes(tmp_path):
    v = tmp_path / "in.mp4"; _video_with_audio(v)
    music = tmp_path / "music.wav"
    _ff(["-f", "lavfi", "-i", "sine=frequency=330:duration=3", str(music)])
    out = tmp_path / "out2.mp4"
    mix_with_video(video=v, audio=music.read_bytes(), output=out)
    assert out.exists()


def test_temp_files_cleaned(tmp_path):
    v = tmp_path / "in.mp4"; _video_with_audio(v)
    music = tmp_path / "m.wav"
    _ff(["-f", "lavfi", "-i", "sine=frequency=200:duration=3", str(music)])
    out = tmp_path / "o.mp4"
    mix_with_video(video=v, audio=music.read_bytes(), output=out)
    leftover = [x for x in tmp_path.iterdir() if x.name not in {"in.mp4", "m.wav", "o.mp4"}]
    assert leftover == []
