from __future__ import annotations

import json

import httpx
import pytest
import respx

from sonilo_cli import login as mod

BASE = "https://api.sonilo.com"
START = {
    "device_code": "dev-1",
    "user_code": "K7QM-3FDX",
    "verification_uri": "https://platform.sonilo.com/dashboard/cli-auth",
    "verification_uri_complete": "https://platform.sonilo.com/dashboard/cli-auth?code=K7QM-3FDX",
    "expires_in": 600,
    "interval": 5,
}
TOKEN = {
    "api_key": "sk-new",
    "key_id": "key-1",
    "account_id": "acct-1",
    "account_name": "Acme",
    "expires_at": "2026-11-09T04:12:00Z",
}


@respx.mock
def test_start_device_posts_metadata():
    route = respx.post(f"{BASE}/cli/auth/device/start").mock(
        return_value=httpx.Response(200, json=START)
    )
    with httpx.Client() as http:
        out = mod.start_device(
            BASE, client_version="0.11.0", hostname="spencer-mbp", os_name="darwin", http=http
        )
    body = json.loads(route.calls.last.request.read())
    assert body["hostname"] == "spencer-mbp"
    assert body["os"] == "darwin"
    assert body["client_version"] == "0.11.0"
    assert out["user_code"] == "K7QM-3FDX"


@respx.mock
def test_start_device_identifies_the_python_client():
    """The backend attributes traffic by `client`; both CLIs must be
    distinguishable in that data."""
    route = respx.post(f"{BASE}/cli/auth/device/start").mock(
        return_value=httpx.Response(200, json=START)
    )
    with httpx.Client() as http:
        mod.start_device(BASE, client_version="0.11.0", hostname="h", os_name="darwin", http=http)
    assert json.loads(route.calls.last.request.read())["client"] == "sonilo-cli-py"


@respx.mock
def test_start_device_explains_429():
    respx.post(f"{BASE}/cli/auth/device/start").mock(
        return_value=httpx.Response(429, json={"error": "too_many_requests"})
    )
    with httpx.Client() as http:
        with pytest.raises(mod.LoginError, match="too many sign-in attempts"):
            mod.start_device(
                BASE, client_version="0.11.0", hostname="h", os_name="darwin", http=http
            )


@respx.mock
def test_start_device_names_an_unexpected_status():
    respx.post(f"{BASE}/cli/auth/device/start").mock(return_value=httpx.Response(503, text="down"))
    with httpx.Client() as http:
        with pytest.raises(mod.LoginError, match="503"):
            mod.start_device(
                BASE, client_version="0.11.0", hostname="h", os_name="darwin", http=http
            )


@respx.mock
def test_poll_waits_one_interval_then_returns():
    respx.post(f"{BASE}/cli/auth/device/token").mock(
        side_effect=[
            httpx.Response(400, json={"error": "authorization_pending"}),
            httpx.Response(200, json=TOKEN),
        ]
    )
    sleeps = []
    with httpx.Client() as http:
        out = mod.poll_for_token(
            BASE, START, http=http, sleep=sleeps.append, now=lambda: 0.0
        )
    assert out["api_key"] == "sk-new"
    assert sleeps == [5.0]


@respx.mock
def test_slow_down_adds_a_second_permanently():
    respx.post(f"{BASE}/cli/auth/device/token").mock(
        side_effect=[
            httpx.Response(400, json={"error": "slow_down"}),
            httpx.Response(400, json={"error": "authorization_pending"}),
            httpx.Response(200, json=TOKEN),
        ]
    )
    sleeps = []
    with httpx.Client() as http:
        mod.poll_for_token(BASE, START, http=http, sleep=sleeps.append, now=lambda: 0.0)
    assert sleeps == [6.0, 6.0]


@respx.mock
@pytest.mark.parametrize(
    "code,message",
    [
        ("access_denied", "denied"),
        ("expired_token", "expired"),
        ("invalid_grant", "expired"),
    ],
)
def test_terminal_errors_are_explained(code, message):
    respx.post(f"{BASE}/cli/auth/device/token").mock(
        return_value=httpx.Response(400, json={"error": code})
    )
    with httpx.Client() as http:
        with pytest.raises(mod.LoginError, match=message):
            mod.poll_for_token(BASE, START, http=http, sleep=lambda s: None, now=lambda: 0.0)


@respx.mock
def test_poll_gives_up_when_the_code_expires():
    respx.post(f"{BASE}/cli/auth/device/token").mock(
        return_value=httpx.Response(400, json={"error": "authorization_pending"})
    )
    ticks = iter([0.0, 700.0, 1400.0])
    with httpx.Client() as http:
        with pytest.raises(mod.LoginError, match="expired"):
            mod.poll_for_token(
                BASE, START, http=http, sleep=lambda s: None, now=lambda: next(ticks)
            )


@respx.mock
def test_poll_never_prints_the_key_in_an_error():
    """Whatever goes wrong, the key must not reach a message. An unknown error
    code is the path most likely to echo a response body verbatim."""
    respx.post(f"{BASE}/cli/auth/device/token").mock(
        return_value=httpx.Response(400, json={"error": "something_new", "api_key": "sk-leak"})
    )
    with httpx.Client() as http:
        with pytest.raises(mod.LoginError) as excinfo:
            mod.poll_for_token(BASE, START, http=http, sleep=lambda s: None, now=lambda: 0.0)
    assert "sk-leak" not in str(excinfo.value)
