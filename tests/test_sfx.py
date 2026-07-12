import json

import httpx
import pytest
import respx

# import sonilo.resources.tasks as tasks_module  # restored in Task 3
from sonilo import Sonilo
from sonilo._requests import build_sfx_t2s_data, build_sfx_v2s_parts
from sonilo.errors import SoniloError

BASE = "https://api.sonilo.com"

SUCCEEDED = {
    "task_id": "t1",
    "type": "text_to_sfx",
    "status": "succeeded",
    "audio": {
        "url": "https://r2.example.com/audio.m4a",
        "content_type": "audio/mp4",
        "file_size": 123,
    },
}


def make_client() -> Sonilo:
    return Sonilo(api_key="sk_test_123")


def test_build_sfx_t2s_data():
    assert build_sfx_t2s_data("boom", 5, None) == {"prompt": "boom", "duration": "5"}
    assert build_sfx_t2s_data("boom", 5, "wav") == {
        "prompt": "boom",
        "duration": "5",
        "audio_format": "wav",
    }


def test_build_sfx_v2s_parts_serializes_segments_and_format():
    segments = [{"start": 0, "end": 2.5, "prompt": "glass"}]
    data, files, opened = build_sfx_v2s_parts(
        None, "https://e.com/v.mp4", None, segments, "mp3"
    )
    assert files is None and opened is False
    assert data["video_url"] == "https://e.com/v.mp4"
    assert data["audio_format"] == "mp3"
    assert json.loads(data["segments"]) == segments


def test_build_sfx_v2s_parts_requires_exactly_one_source():
    with pytest.raises(SoniloError):
        build_sfx_v2s_parts(None, None, None, None, None)
    with pytest.raises(SoniloError):
        build_sfx_v2s_parts(b"x", "https://e.com/v.mp4", None, None, None)
