import base64
import json

import httpx
import pytest
import respx

from sonilo import Sonilo
from sonilo._version import __version__
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


def make_client() -> Sonilo:
    return Sonilo(api_key="sk_test_123")


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("SONILO_API_KEY", raising=False)
    with pytest.raises(SoniloError):
        Sonilo()


def test_env_api_key_used(monkeypatch):
    monkeypatch.setenv("SONILO_API_KEY", "sk_env")
    client = Sonilo()
    assert client._http.headers["authorization"] == "Bearer sk_env"


@respx.mock
def test_text_to_music_generate_posts_form_and_buffers():
    route = respx.post(f"{BASE}/v1/text-to-music").mock(
        return_value=httpx.Response(200, content=ndjson(*STREAM_EVENTS))
    )
    with make_client() as client:
        track = client.text_to_music.generate(prompt="cinematic", duration=60)
    assert track.audio == b"abc"
    assert track.title == "Skyline"

    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer sk_test_123"
    assert request.headers["x-sonilo-client"] == "sdk-python"
    assert request.headers["x-sonilo-client-version"] == __version__
    body = request.content.decode()
    assert "cinematic" in body
    assert "60" in body


@respx.mock
def test_text_to_music_stream_yields_events():
    respx.post(f"{BASE}/v1/text-to-music").mock(
        return_value=httpx.Response(200, content=ndjson(*STREAM_EVENTS))
    )
    with make_client() as client:
        events = list(client.text_to_music.stream(prompt="p", duration=10))
    assert [e["type"] for e in events] == ["title", "audio_chunk", "complete"]
    assert events[1]["data"] == b"abc"


@respx.mock
def test_generate_raises_generation_error_on_error_event():
    respx.post(f"{BASE}/v1/text-to-music").mock(
        return_value=httpx.Response(
            200, content=ndjson({"type": "error", "code": "PROXY_ERROR", "message": "boom"})
        )
    )
    with make_client() as client:
        with pytest.raises(GenerationError):
            client.text_to_music.generate(prompt="p", duration=10)


@respx.mock
def test_generate_raises_generation_error_on_padding_preserving_corrupted_audio_chunk():
    """A corrupted chunk whose padding still lines up (e.g. 4 characters
    clobbered to `!!!!`) must not silently decode to fewer, wrong bytes: it
    must surface as a typed GenerationError, not a successful Track."""
    good = b64(b"This is a longer audio payload for testing, twenty bytes")
    corrupted = good[:10] + "!!!!" + good[14:]
    respx.post(f"{BASE}/v1/text-to-music").mock(
        return_value=httpx.Response(
            200, content=ndjson({"type": "audio_chunk", "data": corrupted}, {"type": "complete"})
        )
    )
    with make_client() as client:
        with pytest.raises(GenerationError) as excinfo:
            client.text_to_music.generate(prompt="p", duration=10)
    assert type(excinfo.value) is GenerationError


@respx.mock
def test_http_error_maps_to_typed_error():
    respx.post(f"{BASE}/v1/text-to-music").mock(
        return_value=httpx.Response(401, json={"detail": "Invalid API key"})
    )
    with make_client() as client:
        with pytest.raises(AuthenticationError):
            client.text_to_music.generate(prompt="p", duration=10)


@respx.mock
def test_video_to_music_uploads_multipart(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"fakevideo")
    route = respx.post(f"{BASE}/v1/video-to-music").mock(
        return_value=httpx.Response(200, content=ndjson(*STREAM_EVENTS))
    )
    with make_client() as client:
        track = client.video_to_music.generate(video=str(path), prompt="upbeat")
    assert track.audio == b"abc"
    body = route.calls.last.request.content
    assert b"clip.mp4" in body
    assert b"fakevideo" in body
    assert b"upbeat" in body


@respx.mock
def test_video_to_music_url_variant():
    route = respx.post(f"{BASE}/v1/video-to-music").mock(
        return_value=httpx.Response(200, content=ndjson(*STREAM_EVENTS))
    )
    with make_client() as client:
        client.video_to_music.generate(video_url="https://example.com/v.mp4")
    assert b"video_url" in route.calls.last.request.content


def test_video_xor_validation():
    with make_client() as client:
        with pytest.raises(SoniloError):
            list(client.video_to_music.stream(video=b"x", video_url="https://e.com/v.mp4"))
        with pytest.raises(SoniloError):
            list(client.video_to_music.stream())


@respx.mock
def test_stream_yields_error_event_without_raising():
    respx.post(f"{BASE}/v1/text-to-music").mock(
        return_value=httpx.Response(
            200, content=ndjson({"type": "error", "code": "PROXY_ERROR", "message": "boom"})
        )
    )
    with make_client() as client:
        events = list(client.text_to_music.stream(prompt="p", duration=10))
    assert events == [{"type": "error", "code": "PROXY_ERROR", "message": "boom"}]


@respx.mock
def test_account_endpoints():
    respx.get(f"{BASE}/v1/account/services").mock(
        return_value=httpx.Response(200, json={"rpm_limit": 60})
    )
    usage_route = respx.get(f"{BASE}/v1/account/usage", params={"days": 7}).mock(
        return_value=httpx.Response(200, json={"summary": {}, "daily": []})
    )
    with make_client() as client:
        assert client.account.services()["rpm_limit"] == 60
        assert client.account.usage(days=7) == {"summary": {}, "daily": []}
    assert usage_route.called


# --- audio_chunk base64 decoding parity with the JS SDK's atob() ---------
#
# atob() implements WHATWG "forgiving-base64 decode": padding is optional,
# only ASCII whitespace (space/tab/LF/FF/CR) is stripped before decoding
# (not full Unicode \s), and anything else invalid must raise. These cases
# are driven through the real public API (client.text_to_music.generate(),
# which goes through stream() -> collect_track()) rather than the private
# decode helper, so a regression here is caught the same way a real
# consumer would hit it.

_GOOD_LONG = b64(b"This is a longer audio payload for testing, twenty bytes")

DECODES_TO = [
    pytest.param(b64(b"abc"), b"abc", id="valid-padded-base64"),
    pytest.param("SGVsbG8", b"Hello", id="unpadded-remainder-3"),
    pytest.param("SGVsbA", b"Hell", id="unpadded-remainder-2"),
    pytest.param("SGVs bG8=", b"Hello", id="ascii-space-inside"),
    pytest.param("SGVs\tbG8=\n", b"Hello", id="ascii-tab-and-trailing-newline"),
    pytest.param("", b"", id="empty-string"),
]

RAISES_GENERATION_ERROR = [
    pytest.param(
        _GOOD_LONG[:10] + "!!!!" + _GOOD_LONG[14:], id="padding-preserving-corrupted"
    ),
    pytest.param("SGVsbG!8=", id="invalid-char-bang"),
    pytest.param("U29tZSBhdWRpbyBkYXRh_-", id="url-safe-alphabet-not-accepted"),
    pytest.param("!!!!", id="all-invalid-chars"),
    pytest.param("not-valid-base64!!!", id="not-valid-base64"),
    pytest.param("SGVsbG8h5", id="remainder-1-length"),
    pytest.param("SGVs bG8=", id="nbsp-inside"),
    pytest.param("SGVsbG8=", id="vertical-tab-inside"),
    pytest.param("SGVs bG8=", id="line-separator-inside"),
]


@pytest.mark.parametrize("payload, expected_audio", DECODES_TO)
@respx.mock
def test_generate_decodes_audio_chunk_matching_atob(payload, expected_audio):
    respx.post(f"{BASE}/v1/text-to-music").mock(
        return_value=httpx.Response(
            200, content=ndjson({"type": "audio_chunk", "data": payload}, {"type": "complete"})
        )
    )
    with make_client() as client:
        track = client.text_to_music.generate(prompt="p", duration=10)
    assert track.audio == expected_audio


@pytest.mark.parametrize("payload", RAISES_GENERATION_ERROR)
@respx.mock
def test_generate_raises_generation_error_for_atob_rejected_payload(payload):
    respx.post(f"{BASE}/v1/text-to-music").mock(
        return_value=httpx.Response(
            200, content=ndjson({"type": "audio_chunk", "data": payload}, {"type": "complete"})
        )
    )
    with make_client() as client:
        with pytest.raises(GenerationError):
            client.text_to_music.generate(prompt="p", duration=10)


@respx.mock
def test_generate_passes_through_unknown_event_types_untouched():
    """Forward-compatible: an event type the SDK doesn't recognize yet must
    not break generate() -- it's ignored, and the rest of the stream is
    still processed normally."""
    respx.post(f"{BASE}/v1/text-to-music").mock(
        return_value=httpx.Response(
            200,
            content=ndjson(
                {"type": "stage_start", "stage": "analyze"},
                {"type": "audio_chunk", "data": b64(b"abc")},
                {"type": "future_event_type", "some": "payload"},
                {"type": "complete"},
            ),
        )
    )
    with make_client() as client:
        track = client.text_to_music.generate(prompt="p", duration=10)
    assert track.audio == b"abc"
