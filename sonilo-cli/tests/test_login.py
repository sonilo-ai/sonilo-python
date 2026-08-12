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


# ---------- the three commands, through main() so dispatch is covered ----------

import stat  # noqa: E402

from sonilo_cli import credentials as store  # noqa: E402
from sonilo_cli.__main__ import main  # noqa: E402


def _mock_flow(user_code="K7QM-3FDX", token=None):
    respx.post(f"{BASE}/cli/auth/device/start").mock(
        return_value=httpx.Response(200, json={**START, "user_code": user_code})
    )
    respx.post(f"{BASE}/cli/auth/device/token").mock(
        return_value=httpx.Response(200, json=token or TOKEN)
    )


@respx.mock
def test_login_writes_the_credential_and_reports(capsys):
    _mock_flow()
    main(["login", "--no-browser"])
    out = capsys.readouterr().out

    cred = store.read_credential(BASE)
    assert cred["api_key"] == "sk-new"
    assert cred["key_id"] == "key-1"
    assert cred["created_by"].startswith("sonilo-cli-py/")
    assert "Signed in as Acme" in out
    assert "2026-11-09" in out
    assert "sk-new" not in out  # the key never reaches stdout


@respx.mock
def test_login_stores_with_0600_permissions():
    _mock_flow()
    main(["login", "--no-browser"])
    p = store.credentials_path()
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


@respx.mock
def test_second_login_reports_and_rewrites_nothing(capsys):
    _mock_flow()
    main(["login", "--no-browser"])
    capsys.readouterr()

    _mock_flow(token={**TOKEN, "api_key": "sk-second"})
    main(["login"])
    out = capsys.readouterr().out

    assert "Already signed in as Acme" in out
    assert store.read_credential(BASE)["api_key"] == "sk-new"


@respx.mock
def test_force_replaces_the_credential_and_revokes_the_previous():
    _mock_flow()
    main(["login", "--no-browser"])

    revoke = respx.delete(f"{BASE}/v1/account/keys/self").mock(
        return_value=httpx.Response(204)
    )
    _mock_flow(token={**TOKEN, "api_key": "sk-second", "key_id": "key-2"})
    main(["login", "--force", "--no-browser"])

    assert store.read_credential(BASE)["api_key"] == "sk-second"
    # Revoked by presenting the *previous* key, which is what identifies it.
    assert revoke.calls.last.request.headers["authorization"] == "Bearer sk-new"


@respx.mock
def test_expired_credential_does_not_dead_end(capsys):
    """build_client says "run sonilo login"; login must not answer "already
    signed in, use --force". Every user reaches this at day 90."""
    store.write_credential(
        BASE,
        {
            "api_key": "sk-old",
            "key_id": "key-0",
            "account_id": "acct-1",
            "account_name": "Acme",
            "expires_at": "2020-01-01T00:00:00Z",
            "created_at": "2019-10-03T00:00:00Z",
            "created_by": "sonilo-cli-py/0.10.0",
        },
    )
    respx.delete(f"{BASE}/v1/account/keys/self").mock(return_value=httpx.Response(204))
    _mock_flow(token={**TOKEN, "api_key": "sk-renewed"})

    main(["login", "--no-browser"])

    assert store.read_credential(BASE)["api_key"] == "sk-renewed"
    assert "Already signed in" not in capsys.readouterr().out


@respx.mock
def test_api_base_keeps_environments_apart():
    staging = "https://api.staging.sonilo.com"
    respx.post(f"{staging}/cli/auth/device/start").mock(
        return_value=httpx.Response(200, json=START)
    )
    respx.post(f"{staging}/cli/auth/device/token").mock(
        return_value=httpx.Response(200, json={**TOKEN, "api_key": "sk-staging"})
    )
    _mock_flow()
    main(["login", "--no-browser"])
    main(["login", "--api-base", staging, "--no-browser"])

    assert store.read_credential(BASE)["api_key"] == "sk-new"
    assert store.read_credential(staging)["api_key"] == "sk-staging"


@respx.mock
def test_whoami_shows_the_source_and_only_a_prefix(capsys):
    # A realistic key length matters here: with a 6-character fixture, "the
    # first 8 characters" *is* the whole key and the assertion proves nothing.
    real_length = "sk-" + "a1b2c3d4" * 6
    _mock_flow(token={**TOKEN, "api_key": real_length})
    main(["login", "--no-browser"])
    capsys.readouterr()

    main(["whoami"])
    out = capsys.readouterr().out
    assert "account: Acme" in out
    assert "source: credential file" in out
    assert real_length not in out
    assert real_length[:8] + "..." in out


@respx.mock
def test_whoami_says_when_the_env_var_is_overriding(capsys, monkeypatch):
    _mock_flow()
    main(["login", "--no-browser"])
    capsys.readouterr()

    monkeypatch.setenv("SONILO_API_KEY", "sk-env")
    main(["whoami"])
    assert "the stored credential is being ignored" in capsys.readouterr().out


def test_whoami_when_not_signed_in(capsys):
    main(["whoami"])
    assert "Not signed in. Run sonilo login." in capsys.readouterr().out


@respx.mock
def test_logout_revokes_then_forgets(capsys):
    _mock_flow()
    main(["login", "--no-browser"])
    capsys.readouterr()

    revoke = respx.delete(f"{BASE}/v1/account/keys/self").mock(
        return_value=httpx.Response(204)
    )
    main(["logout"])

    assert revoke.called
    assert store.read_credential(BASE) is None
    assert "Signed out." in capsys.readouterr().out


@respx.mock
def test_logout_keeps_the_credential_when_the_revoke_fails(capsys):
    _mock_flow()
    main(["login", "--no-browser"])
    capsys.readouterr()

    respx.delete(f"{BASE}/v1/account/keys/self").mock(return_value=httpx.Response(500))
    with pytest.raises(SystemExit) as excinfo:
        main(["logout"])

    assert excinfo.value.code == 1
    # Forgetting it here would leave a live key with nothing left to revoke it by.
    assert store.read_credential(BASE)["api_key"] == "sk-new"
    assert "still valid and still stored" in capsys.readouterr().out


@respx.mock
def test_logout_local_only_skips_the_request(capsys):
    _mock_flow()
    main(["login", "--no-browser"])
    capsys.readouterr()

    revoke = respx.delete(f"{BASE}/v1/account/keys/self").mock(
        return_value=httpx.Response(204)
    )
    main(["logout", "--local-only"])

    assert not revoke.called
    assert store.read_credential(BASE) is None
    assert "still valid" in capsys.readouterr().out


def test_logout_when_not_signed_in(capsys):
    main(["logout"])
    assert "Not signed in." in capsys.readouterr().out


@respx.mock
def test_login_errors_print_as_sonilo_messages(capsys):
    """A denied sign-in is an expected outcome, not a crash — it must read as
    `sonilo: <message>` and exit 1, never as a traceback."""
    respx.post(f"{BASE}/cli/auth/device/start").mock(
        return_value=httpx.Response(200, json=START)
    )
    respx.post(f"{BASE}/cli/auth/device/token").mock(
        return_value=httpx.Response(400, json={"error": "access_denied"})
    )
    with pytest.raises(SystemExit) as excinfo:
        main(["login", "--no-browser"])
    assert excinfo.value.code == 1
    assert "sonilo: sign-in was denied" in capsys.readouterr().err
