import base64
import json

import httpx
import pytest
import respx

import sonilo.resources.tasks as tasks_module
from sonilo import AsyncSonilo
from sonilo.errors import AuthenticationError, GenerationError, SoniloError
from sonilo.resources.tasks import parse_music_result
from sonilo.types import MusicResult, SfxMedia

BASE = "https://api.sonilo.com"

MUSIC_SUCCEEDED = {
    "task_id": "m1",
    "type": "video_to_music",
    "status": "succeeded",
    "audio": [
        {
            "stream_index": 0,
            "url": "https://r2.example.com/audio0.m4a",
            "content_type": "audio/mp4",
            "sample_rate": 44100,
            "channels": 2,
            "file_size": 123,
        }
    ],
    "vocals": {
        "url": "https://r2.example.com/vocals.m4a",
        "content_type": "audio/mp4",
        "file_size": 456,
    },
    "mux": [
        {
            "stream_index": 0,
            "url": "https://r2.example.com/mux0.mp4",
            "content_type": "audio/mp4",
            "file_size": 789,
        }
    ],
    "title": {
        "title": "Skyline",
        "summary": "An upbeat track",
        "display_tags": ["upbeat", "cinematic"],
    },
    "duration_seconds": 92.5,
}


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def ndjson(*events) -> bytes:
    return ("".join(json.dumps(e) + "\n" for e in events)).encode()


STREAM_EVENTS = (
    {"type": "title", "title": "Skyline"},
    {"type": "audio_chunk", "data": b64(b"abc")},
    {"type": "complete"},
)


@respx.mock
async def test_generate_buffers_track():
    respx.post(f"{BASE}/v1/text-to-music").mock(
        return_value=httpx.Response(200, content=ndjson(*STREAM_EVENTS))
    )
    async with AsyncSonilo(api_key="sk_test") as client:
        track = await client.text_to_music.generate(prompt="p", duration=10)
    assert track.audio == b"abc"
    assert track.title == "Skyline"


@respx.mock
async def test_stream_yields_events():
    respx.post(f"{BASE}/v1/text-to-music").mock(
        return_value=httpx.Response(200, content=ndjson(*STREAM_EVENTS))
    )
    async with AsyncSonilo(api_key="sk_test") as client:
        events = [e async for e in client.text_to_music.stream(prompt="p", duration=10)]
    assert [e["type"] for e in events] == ["title", "audio_chunk", "complete"]
    assert events[1]["data"] == b"abc"


@respx.mock
async def test_error_event_raises_generation_error():
    respx.post(f"{BASE}/v1/text-to-music").mock(
        return_value=httpx.Response(200, content=ndjson({"type": "error", "message": "boom"}))
    )
    async with AsyncSonilo(api_key="sk_test") as client:
        with pytest.raises(GenerationError):
            await client.text_to_music.generate(prompt="p", duration=10)


@respx.mock
async def test_http_error_maps():
    respx.post(f"{BASE}/v1/video-to-music").mock(
        return_value=httpx.Response(401, json={"detail": "Invalid API key"})
    )
    async with AsyncSonilo(api_key="sk_test") as client:
        with pytest.raises(AuthenticationError):
            await client.video_to_music.generate(video=b"x")


async def test_video_xor_validation():
    async with AsyncSonilo(api_key="sk_test") as client:
        with pytest.raises(SoniloError):
            await client.video_to_music.generate()


# --- video-to-music async (isolate_vocals) --------------------------------


async def test_async_video_to_music_submit_xor_validation():
    async with AsyncSonilo(api_key="sk_test") as client:
        with pytest.raises(SoniloError):
            await client.video_to_music.submit(video=b"x", video_url="https://e.com/v.mp4")
        with pytest.raises(SoniloError):
            await client.video_to_music.submit()


@respx.mock
async def test_async_video_to_music_submit_serializes_mode_and_isolate_vocals():
    route = respx.post(f"{BASE}/v1/video-to-music").mock(
        return_value=httpx.Response(202, json={"task_id": "m1", "status": "processing"})
    )
    async with AsyncSonilo(api_key="sk_test") as client:
        task = await client.video_to_music.submit(
            video_url="https://e.com/v.mp4", isolate_vocals=True
        )
    assert task.task_id == "m1"
    body = route.calls.last.request.content.decode()
    assert "mode=async" in body
    assert "isolate_vocals=true" in body


async def test_async_video_to_music_isolate_vocals_requires_async_mode():
    async with AsyncSonilo(api_key="sk_test") as client:
        with pytest.raises(SoniloError):
            await client.video_to_music.submit(
                video_url="https://e.com/v.mp4", isolate_vocals=True, mode="stream"
            )
        with pytest.raises(SoniloError):
            await client.video_to_music.generate_async(
                video_url="https://e.com/v.mp4", isolate_vocals=True, mode="stream"
            )


@respx.mock
async def test_async_video_to_music_generate_async_submits_and_waits(monkeypatch):
    async def no_sleep(seconds):
        return None

    monkeypatch.setattr(tasks_module, "_async_sleep", no_sleep)
    respx.post(f"{BASE}/v1/video-to-music").mock(
        return_value=httpx.Response(202, json={"task_id": "m1", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/m1").mock(
        side_effect=[
            httpx.Response(200, json={"task_id": "m1", "status": "processing"}),
            httpx.Response(200, json=MUSIC_SUCCEEDED),
        ]
    )
    async with AsyncSonilo(api_key="sk_test") as client:
        result = await client.video_to_music.generate_async(
            video_url="https://e.com/v.mp4", isolate_vocals=True
        )
    assert isinstance(result, MusicResult)
    assert result.status == "succeeded"
    assert result.vocals == SfxMedia(
        url="https://r2.example.com/vocals.m4a", content_type="audio/mp4", file_size=456
    )
    assert result.mux[0].stream_index == 0
    assert result.title.title == "Skyline"


@respx.mock
async def test_async_tasks_get_accepts_custom_parser_for_music():
    respx.get(f"{BASE}/v1/tasks/m1").mock(return_value=httpx.Response(200, json=MUSIC_SUCCEEDED))
    async with AsyncSonilo(api_key="sk_test") as client:
        result = await client.tasks.get("m1", parser=parse_music_result)
    assert isinstance(result, MusicResult)
    assert result.audio[0].sample_rate == 44100


@respx.mock
async def test_async_music_result_asave_downloads_vocals(tmp_path):
    respx.get("https://r2.example.com/vocals.m4a").mock(
        return_value=httpx.Response(200, content=b"vocalbytes")
    )
    result = parse_music_result(MUSIC_SUCCEEDED)
    out = await result.asave(tmp_path / "v.m4a", which="vocals")
    assert out.read_bytes() == b"vocalbytes"


@respx.mock
async def test_account_endpoints():
    respx.get(f"{BASE}/v1/account/services").mock(
        return_value=httpx.Response(200, json={"rpm_limit": 60})
    )
    respx.get(f"{BASE}/v1/account/usage").mock(
        return_value=httpx.Response(200, json={"summary": {}, "daily": []})
    )
    async with AsyncSonilo(api_key="sk_test") as client:
        assert (await client.account.services())["rpm_limit"] == 60
        assert await client.account.usage() == {"summary": {}, "daily": []}
