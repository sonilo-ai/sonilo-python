import base64
import json

import httpx
import pytest
import respx

from sonilo import AsyncSonilo
from sonilo.errors import AuthenticationError, GenerationError, SoniloError

BASE = "https://api.sonilo.com"


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
