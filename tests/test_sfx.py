import json

import httpx
import pytest
import respx

import sonilo.resources.tasks as tasks_module
from sonilo import Sonilo
from sonilo._requests import build_sfx_t2s_data, build_sfx_v2s_parts
from sonilo.errors import PaymentRequiredError, SoniloError, TaskFailedError, TaskTimeoutError
from sonilo.types import SfxMedia

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


@respx.mock
def test_tasks_get_parses_succeeded():
    respx.get(f"{BASE}/v1/tasks/t1").mock(return_value=httpx.Response(200, json=SUCCEEDED))
    with make_client() as client:
        result = client.tasks.get("t1")
    assert result.status == "succeeded"
    assert result.type == "text_to_sfx"
    assert result.audio == SfxMedia(
        url="https://r2.example.com/audio.m4a", content_type="audio/mp4", file_size=123
    )
    assert result.video is None
    assert result.cost is None


@respx.mock
def test_tasks_get_returns_failed_as_data():
    respx.get(f"{BASE}/v1/tasks/t1").mock(
        return_value=httpx.Response(
            200,
            json={
                "task_id": "t1",
                "type": "text_to_sfx",
                "status": "failed",
                "error": {"code": "UPSTREAM_MALFORMED", "message": "boom"},
                "refunded": True,
            },
        )
    )
    with make_client() as client:
        result = client.tasks.get("t1")
    assert result.status == "failed"
    assert result.error == {"code": "UPSTREAM_MALFORMED", "message": "boom"}
    assert result.refunded is True


@respx.mock
def test_tasks_get_url_encodes_task_id():
    route = respx.get(f"{BASE}/v1/tasks/t1%2F..%2Fother").mock(
        return_value=httpx.Response(200, json={"task_id": "t1/../other", "status": "processing"})
    )
    with make_client() as client:
        result = client.tasks.get("t1/../other")
    assert route.called
    assert result.status == "processing"


@respx.mock
def test_tasks_wait_polls_until_succeeded(monkeypatch):
    sleeps = []
    monkeypatch.setattr(tasks_module, "_sleep", sleeps.append)
    processing = {"task_id": "t1", "type": "text_to_sfx", "status": "processing"}
    respx.get(f"{BASE}/v1/tasks/t1").mock(
        side_effect=[
            httpx.Response(200, json=processing),
            httpx.Response(200, json=processing),
            httpx.Response(200, json=SUCCEEDED),
        ]
    )
    with make_client() as client:
        result = client.tasks.wait("t1")
    assert result.status == "succeeded"
    assert sleeps == [2.0, 2.0]


@respx.mock
def test_tasks_wait_raises_task_failed(monkeypatch):
    monkeypatch.setattr(tasks_module, "_sleep", lambda s: None)
    respx.get(f"{BASE}/v1/tasks/t1").mock(
        return_value=httpx.Response(
            200,
            json={
                "task_id": "t1",
                "status": "failed",
                "error": {"code": "GENERATION_FAILED", "message": "boom"},
                "refunded": True,
            },
        )
    )
    with make_client() as client:
        with pytest.raises(TaskFailedError) as exc_info:
            client.tasks.wait("t1")
    assert exc_info.value.code == "GENERATION_FAILED"
    assert exc_info.value.task_id == "t1"
    assert exc_info.value.refunded is True


@respx.mock
def test_tasks_wait_times_out(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(tasks_module, "_monotonic", lambda: clock["t"])

    def advance(seconds):
        clock["t"] += seconds

    monkeypatch.setattr(tasks_module, "_sleep", advance)
    respx.get(f"{BASE}/v1/tasks/t1").mock(
        return_value=httpx.Response(200, json={"task_id": "t1", "status": "processing"})
    )
    with make_client() as client:
        with pytest.raises(TaskTimeoutError) as exc_info:
            client.tasks.wait("t1", poll_interval=1.0, timeout=3.0)
    assert exc_info.value.task_id == "t1"


@respx.mock
def test_text_to_sfx_submit_posts_form():
    route = respx.post(f"{BASE}/v1/text-to-sfx").mock(
        return_value=httpx.Response(202, json={"task_id": "t1", "status": "processing"})
    )
    with make_client() as client:
        task = client.text_to_sfx.submit(prompt="glass breaking", duration=5, audio_format="wav")
    assert task.task_id == "t1"
    assert task.status == "processing"
    body = route.calls.last.request.content.decode()
    assert "glass+breaking" in body
    assert "wav" in body


@respx.mock
def test_text_to_sfx_submit_http_error_maps():
    respx.post(f"{BASE}/v1/text-to-sfx").mock(
        return_value=httpx.Response(402, json={"detail": "Insufficient balance"})
    )
    with make_client() as client:
        with pytest.raises(PaymentRequiredError):
            client.text_to_sfx.submit(prompt="p", duration=5)


@respx.mock
def test_video_to_sfx_submit_uploads_multipart(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"fakevideo")
    route = respx.post(f"{BASE}/v1/video-to-sfx").mock(
        return_value=httpx.Response(202, json={"task_id": "t2", "status": "processing"})
    )
    with make_client() as client:
        task = client.video_to_sfx.submit(
            video=str(path), segments=[{"start": 0, "end": 1.0, "prompt": "pop"}]
        )
    assert task.task_id == "t2"
    body = route.calls.last.request.content
    assert b"clip.mp4" in body
    assert b"fakevideo" in body
    assert b"segments" in body


@respx.mock
def test_video_to_sfx_submit_url_variant():
    route = respx.post(f"{BASE}/v1/video-to-sfx").mock(
        return_value=httpx.Response(202, json={"task_id": "t2", "status": "processing"})
    )
    with make_client() as client:
        client.video_to_sfx.submit(video_url="https://e.com/v.mp4", audio_format="mp3")
    body = route.calls.last.request.content
    assert b"video_url" in body
    assert b"mp3" in body


def test_video_to_sfx_xor_validation():
    with make_client() as client:
        with pytest.raises(SoniloError):
            client.video_to_sfx.submit(video=b"x", video_url="https://e.com/v.mp4")
        with pytest.raises(SoniloError):
            client.video_to_sfx.submit()


@respx.mock
def test_text_to_sfx_generate_submits_and_waits(monkeypatch):
    monkeypatch.setattr(tasks_module, "_sleep", lambda s: None)
    respx.post(f"{BASE}/v1/text-to-sfx").mock(
        return_value=httpx.Response(202, json={"task_id": "t1", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/t1").mock(
        side_effect=[
            httpx.Response(200, json={"task_id": "t1", "status": "processing"}),
            httpx.Response(200, json=SUCCEEDED),
        ]
    )
    with make_client() as client:
        result = client.text_to_sfx.generate(prompt="glass", duration=5)
    assert result.status == "succeeded"
    assert result.audio is not None
