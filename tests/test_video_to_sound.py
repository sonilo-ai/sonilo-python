import httpx
import pytest
import respx

from sonilo import AsyncSonilo, Sonilo
from sonilo._requests import build_v2s_parts
from sonilo.errors import SoniloError
from sonilo.resources.tasks import parse_sound_result

SUCCESS_BODY = {
    "task_id": "sd1",
    "type": "video_to_sound",
    "status": "succeeded",
    "output_url": "https://r2/sound.wav",
    "output_type": "audio",
    "output_bytes": 12,
    "music": {"url": "https://r2/music.m4a", "content_type": "audio/mp4", "file_size": 5},
    "sfx": {"url": "https://r2/sfx.wav", "content_type": "audio/wav", "file_size": 4},
    "duration_seconds": 8.5,
}


def test_build_v2s_parts_emits_every_field():
    data, files, opened = build_v2s_parts(
        None,
        "https://x/v.mp4",
        "uplifting orchestral",
        "match the action",
        [{"start": 0, "end": 2, "prompt": "whoosh"}],
        True,
        False,
    )
    assert files is None and opened is False
    assert data["video_url"] == "https://x/v.mp4"
    assert data["music_prompt"] == "uplifting orchestral"
    assert data["sfx_prompt"] == "match the action"
    assert '"prompt": "whoosh"' in data["segments"]
    assert data["preserve_speech"] == "true"
    assert data["ducking"] == "false"
    assert "prompt" not in data
    assert "isolate_vocals" not in data


def test_build_v2s_parts_omits_unset_booleans():
    data, _, _ = build_v2s_parts(None, "https://x/v.mp4", None, None, None, None, None)
    assert data == {"video_url": "https://x/v.mp4"}


def test_build_v2s_parts_requires_exactly_one_input():
    with pytest.raises(SoniloError):
        build_v2s_parts(None, None, None, None, None, None, None)
    with pytest.raises(SoniloError):
        build_v2s_parts(b"bytes", "https://x/v.mp4", None, None, None, None, None)


def test_parse_sound_result_reads_output_and_stems():
    result = parse_sound_result(SUCCESS_BODY)
    assert result.output_url == "https://r2/sound.wav"
    assert result.output_type == "audio"
    assert result.output_bytes == 12
    assert result.music.url == "https://r2/music.m4a"
    assert result.sfx.content_type == "audio/wav"
    assert result.music_processed is None
    assert result.duration_seconds == 8.5


@respx.mock
def test_sound_result_save_and_save_stem(tmp_path):
    respx.get("https://r2/sound.wav").mock(
        return_value=httpx.Response(200, content=b"mixed")
    )
    respx.get("https://r2/music.m4a").mock(
        return_value=httpx.Response(200, content=b"music")
    )
    result = parse_sound_result(SUCCESS_BODY)
    assert result.save(tmp_path / "out.wav").read_bytes() == b"mixed"
    assert result.save_stem(tmp_path / "music.m4a", which="music").read_bytes() == b"music"


def test_sound_result_raises_for_missing_artifacts():
    result = parse_sound_result({"task_id": "sd2", "status": "processing"})
    with pytest.raises(SoniloError):
        result.save("unused.wav")
    with pytest.raises(SoniloError):
        result.save_stem("unused.wav", which="music")
    with pytest.raises(SoniloError):
        result.save_stem("unused.wav", which="nonsense")
