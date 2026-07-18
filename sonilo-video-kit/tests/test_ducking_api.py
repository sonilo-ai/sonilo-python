import time

import httpx
import pytest
import respx
from sonilo import Sonilo
from sonilo_video_kit import _ducking_api as ducking_api_module
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
    "https://0x7f000001/x",               # hex-integer 127.0.0.1
    "https://2130706433/x",               # decimal-integer 127.0.0.1
    "https://017700000001/x",             # legacy-octal-integer 127.0.0.1
    "https://127.0.0.1./x",               # trailing-dot dotted-quad
    "https://0xA9FEA9FE/x",               # hex-integer 169.254.169.254 (metadata)
    "https://0x7f.0.0.1/x",               # dotted, first label hex
    "https://0177.0.0.1/x",               # dotted, first label legacy octal
])
def test_ssrf_guard_rejects(bad):
    with pytest.raises(VideoKitError):
        assert_safe_download_url(bad)


def test_ssrf_guard_allows_normal_https():
    assert_safe_download_url("https://cdn.example.com/mix.wav")  # no raise


def test_ssrf_guard_allows_domain_with_numeric_labels():
    # A domain whose labels merely CONTAIN digits must not be misclassified
    # as an IP-literal encoding just because _parse_ipv4_number is lenient
    # about hex/octal-looking labels.
    assert_safe_download_url("https://sub.domain-with-numbers123.com/x")  # no raise


@respx.mock
def test_download_enforces_byte_cap(tmp_path):
    respx.get("https://cdn.example.com/big.wav").mock(
        return_value=httpx.Response(200, content=b"x" * 5000)
    )
    dest = tmp_path / "out.wav"
    with pytest.raises(VideoKitError):
        download_ducked_mix("https://cdn.example.com/big.wav", dest, max_bytes=1000,
                            sleep=lambda *_: None)


@respx.mock
def test_download_rejects_redirect_response(tmp_path):
    # follow_redirects=False means a 3xx comes back as an ordinary response,
    # not an exception; it must still be treated as a download failure (like
    # JS's redirect:"error"), never written to disk as the "mix".
    respx.get("https://cdn.example.com/mix.wav").mock(
        return_value=httpx.Response(
            302, headers={"Location": "https://internal.example/secret"}
        )
    )
    dest = tmp_path / "out.wav"
    with pytest.raises(VideoKitError):
        download_ducked_mix("https://cdn.example.com/mix.wav", dest, max_bytes=1000,
                            sleep=lambda *_: None)
    assert not dest.exists()


def test_download_timeout_guard_trips_on_slow_stream(tmp_path, monkeypatch):
    """A server dribbling small chunks slower than the per-attempt deadline
    (but each one arriving, so httpx's own inter-chunk read timeout never
    fires) must still be bounded by the wall-clock check inside the
    streaming loop -- not stream forever. Uses a custom transport (rather
    than respx, which buffers mocked content) so each chunk is actually
    yielded with a small real sleep between them, and a near-zero per-attempt
    `timeout` so the guard trips almost immediately -- fast and deterministic,
    no real hang."""

    class _SlowStream(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(50):
                time.sleep(0.01)
                yield b"x"

        def close(self) -> None:
            pass

    class _SlowTransport(httpx.BaseTransport):
        def handle_request(self, request):  # noqa: ANN001
            return httpx.Response(200, stream=_SlowStream())

    real_client_cls = httpx.Client

    def _client_factory(*args, **kwargs):
        kwargs["transport"] = _SlowTransport()
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr(ducking_api_module.httpx, "Client", _client_factory)

    dest = tmp_path / "out.wav"
    start = time.monotonic()
    with pytest.raises(VideoKitError):
        download_ducked_mix(
            "https://cdn.example.com/slow.wav",
            dest,
            max_bytes=10_000,
            timeout=0.02,  # near-zero per-attempt wall-clock cap
            sleep=lambda *_: None,
        )
    elapsed = time.monotonic() - start
    # If the guard didn't trip, all 50 chunks * 0.01s ~= 0.5s per attempt,
    # times up to 4 retried attempts ~= 2s. Bounding elapsed well under that
    # proves the wall-clock check -- not the stream simply finishing -- is
    # what stopped the download.
    assert elapsed < 1.0
    assert not dest.exists()
