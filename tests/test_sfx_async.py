import httpx
import pytest
import respx

import sonilo.resources.tasks as tasks_module
from sonilo import AsyncSonilo
from sonilo.errors import TaskFailedError

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


def make_client() -> AsyncSonilo:
    return AsyncSonilo(api_key="sk_test_123")


@respx.mock
async def test_async_generate_polls_to_success(monkeypatch):
    async def no_sleep(seconds):
        return None

    monkeypatch.setattr(tasks_module, "_async_sleep", no_sleep)
    respx.post(f"{BASE}/v1/text-to-sfx").mock(
        return_value=httpx.Response(202, json={"task_id": "t1", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/t1").mock(
        side_effect=[
            httpx.Response(200, json={"task_id": "t1", "status": "processing"}),
            httpx.Response(200, json=SUCCEEDED),
        ]
    )
    async with make_client() as client:
        result = await client.text_to_sfx.generate(prompt="glass", duration=5)
    assert result.status == "succeeded"


@respx.mock
async def test_async_wait_raises_task_failed(monkeypatch):
    async def no_sleep(seconds):
        return None

    monkeypatch.setattr(tasks_module, "_async_sleep", no_sleep)
    respx.get(f"{BASE}/v1/tasks/t1").mock(
        return_value=httpx.Response(
            200,
            json={
                "task_id": "t1",
                "status": "failed",
                "error": {"code": "GENERATION_FAILED", "message": "boom"},
                "refunded": False,
            },
        )
    )
    async with make_client() as client:
        with pytest.raises(TaskFailedError) as exc_info:
            await client.tasks.wait("t1")
    assert exc_info.value.refunded is False


@respx.mock
async def test_async_video_to_sfx_submit_url():
    route = respx.post(f"{BASE}/v1/video-to-sfx").mock(
        return_value=httpx.Response(202, json={"task_id": "t2", "status": "processing"})
    )
    async with make_client() as client:
        task = await client.video_to_sfx.submit(
            video_url="https://e.com/v.mp4", audio_format="mp3"
        )
    assert task.task_id == "t2"
    body = route.calls.last.request.content
    assert b"video_url" in body
    assert b"mp3" in body
