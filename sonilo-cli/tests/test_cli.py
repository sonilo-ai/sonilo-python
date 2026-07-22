import json

import httpx
import pytest
import respx

from sonilo_cli.__main__ import main

BASE = "https://api.sonilo.com"


def run(argv, api_key="sk-test"):
    full = (["--api-key", api_key] if api_key is not None else []) + argv
    main(full)


@respx.mock
def test_account_prints_json(capsys):
    respx.get(f"{BASE}/v1/account/services").mock(
        return_value=httpx.Response(200, json={"plan": "pro"})
    )
    run(["account"])
    out = json.loads(capsys.readouterr().out)
    assert out == {"plan": "pro"}


@respx.mock
def test_usage_passes_days(capsys):
    route = respx.get(f"{BASE}/v1/account/usage").mock(
        return_value=httpx.Response(200, json={"days": 7})
    )
    run(["usage", "--days", "7"])
    assert route.calls.last.request.url.params["days"] == "7"


def test_missing_api_key_exits_1(capsys, monkeypatch):
    monkeypatch.delenv("SONILO_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        main(["account"])  # no --api-key, no env
    assert exc.value.code == 1
    assert "no API key" in capsys.readouterr().err


def test_unknown_command_exits_1(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--api-key", "sk-test", "frobnicate"])
    assert exc.value.code == 1
    assert "sonilo:" in capsys.readouterr().err


@respx.mock
def test_api_error_has_no_traceback(capsys):
    respx.get(f"{BASE}/v1/account/services").mock(
        return_value=httpx.Response(401, json={"error": {"message": "bad key"}})
    )
    with pytest.raises(SystemExit) as exc:
        run(["account"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("sonilo:")
    assert "Traceback" not in err
