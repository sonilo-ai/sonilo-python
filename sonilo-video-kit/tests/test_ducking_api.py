import httpx
import pytest
import respx
from sonilo import Sonilo
from sonilo_video_kit._ducking_api import (
    assert_safe_download_url, submit_ducking_job, await_ducking_result, download_ducked_mix,
)
from sonilo_video_kit.errors import DuckingFailedError, VideoKitError


def _client():
    return Sonilo(api_key="test-key")  # no network at construction


@respx.mock
def test_submit_returns_task_id(tmp_path):
    route = respx.post("https://api.sonilo.com/v1/audio-ducking").mock(
        return_value=httpx.Response(200, json={"task_id": "t_123"})
    )
    voice = tmp_path / "v.wav"; voice.write_bytes(b"RIFFvoice")
    music = tmp_path / "m.wav"; music.write_bytes(b"RIFFmusic")
    tid = submit_ducking_job(_client(), voice, music)
    assert tid == "t_123"
    assert route.called


@respx.mock
def test_poll_until_succeeded():
    respx.get("https://api.sonilo.com/v1/tasks/t_1").mock(
        side_effect=[
            httpx.Response(200, json={"status": "processing"}),
            httpx.Response(200, json={"status": "succeeded",
                                      "output_url": "https://cdn.example.com/x.wav",
                                      "output_type": "audio", "output_bytes": 10}),
        ]
    )
    res = await_ducking_result(_client(), "t_1", poll_interval=0.0, timeout=5.0,
                               sleep=lambda *_: None)
    assert res.output_type == "audio"
    assert res.output_url == "https://cdn.example.com/x.wav"
    assert res.output_bytes == 10


@respx.mock
def test_poll_failed_raises():
    respx.get("https://api.sonilo.com/v1/tasks/t_2").mock(
        return_value=httpx.Response(200, json={"status": "failed", "code": "QUOTA",
                                               "message": "QUOTA: no credits",
                                               "refunded": True})
    )
    with pytest.raises(DuckingFailedError) as ei:
        await_ducking_result(_client(), "t_2", poll_interval=0.0, timeout=5.0,
                             sleep=lambda *_: None)
    assert ei.value.code == "QUOTA"
    assert ei.value.refunded is True


@pytest.mark.parametrize("bad", [
    "http://cdn.example.com/x.wav",       # not https
    "https://127.0.0.1/x.wav",            # IP literal
    "https://localhost/x.wav",
    "https://thing.local/x.wav",
    "https://svc.internal/x.wav",
])
def test_ssrf_guard_rejects(bad):
    with pytest.raises(VideoKitError):
        assert_safe_download_url(bad)


def test_ssrf_guard_allows_normal_https():
    assert_safe_download_url("https://cdn.example.com/mix.wav")  # no raise


@respx.mock
def test_download_enforces_byte_cap(tmp_path):
    respx.get("https://cdn.example.com/big.wav").mock(
        return_value=httpx.Response(200, content=b"x" * 5000)
    )
    dest = tmp_path / "out.wav"
    with pytest.raises(VideoKitError):
        download_ducked_mix("https://cdn.example.com/big.wav", dest, max_bytes=1000,
                            sleep=lambda *_: None)
