from __future__ import annotations

import json
import stat

import pytest

from sonilo_cli import credentials as store

BASE = "https://api.sonilo.com"


def sample(**overrides):
    cred = {
        "api_key": "sk-abc",
        "key_id": "key-1",
        "account_id": "acct-1",
        "account_name": "Acme",
        "expires_at": "2026-11-09T04:12:00Z",
        "created_at": "2026-08-11T04:12:00Z",
        "created_by": "sonilo-cli-py/0.11.0",
    }
    cred.update(overrides)
    return cred


def test_path_honours_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "x"))
    assert store.credentials_path() == tmp_path / "x" / "sonilo" / "credentials.json"


def test_path_falls_back_to_dot_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert store.credentials_path() == tmp_path / ".config" / "sonilo" / "credentials.json"


def test_missing_file_reads_as_none(tmp_path):
    assert store.read_credential(BASE, tmp_path / "nope.json") is None


def test_round_trip(tmp_path):
    p = tmp_path / "c.json"
    store.write_credential(BASE, sample(), p)
    assert store.read_credential(BASE, p)["api_key"] == "sk-abc"


def test_keyed_by_api_base(tmp_path):
    p = tmp_path / "c.json"
    store.write_credential(BASE, sample(api_key="sk-prod"), p)
    store.write_credential("https://api.staging.sonilo.com", sample(api_key="sk-stg"), p)

    assert store.read_credential(BASE, p)["api_key"] == "sk-prod"
    assert store.read_credential("https://api.staging.sonilo.com", p)["api_key"] == "sk-stg"


def test_file_is_0600_and_dir_0700(tmp_path):
    p = tmp_path / "nested" / "c.json"
    store.write_credential(BASE, sample(), p)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert stat.S_IMODE(p.parent.stat().st_mode) == 0o700


def test_remove_leaves_siblings(tmp_path):
    p = tmp_path / "c.json"
    store.write_credential(BASE, sample(), p)
    store.write_credential("https://other", sample(api_key="sk-other"), p)

    store.remove_credential(BASE, p)

    assert store.read_credential(BASE, p) is None
    assert store.read_credential("https://other", p)["api_key"] == "sk-other"


def test_remove_deletes_the_file_when_empty(tmp_path):
    p = tmp_path / "c.json"
    store.write_credential(BASE, sample(), p)
    store.remove_credential(BASE, p)
    assert not p.exists()


def test_remove_is_a_no_op_when_nothing_is_stored(tmp_path):
    """logout on a machine that never logged in must not raise."""
    store.remove_credential(BASE, tmp_path / "nope.json")


def test_newer_format_raises(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"version": 99, "credentials": {}}))
    with pytest.raises(store.CredentialFormatError):
        store.read_credential(BASE, p)


def test_corrupt_json_reads_as_none(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{ not json")
    assert store.read_credential(BASE, p) is None


def test_unknown_fields_survive_a_rewrite(tmp_path):
    p = tmp_path / "c.json"
    cred = sample()
    cred["future"] = 1
    p.write_text(json.dumps({"version": 1, "credentials": {BASE: cred}}))

    store.write_credential("https://other", sample(), p)

    assert json.loads(p.read_text())["credentials"][BASE]["future"] == 1


def test_write_leaves_no_temp_file_behind(tmp_path):
    """The write is temp-then-rename; a leftover .tmp would carry a live key
    with no owner."""
    p = tmp_path / "c.json"
    store.write_credential(BASE, sample(), p)
    assert [f.name for f in tmp_path.iterdir()] == ["c.json"]


def test_file_written_by_the_js_cli_reads_identically(tmp_path):
    """Cross-client contract: the JS CLI writes this exact shape (2-space
    indent, `sonilo-cli/<version>` in created_by). Both CLIs must read one
    file, so a fixture written the other client's way has to work here."""
    p = tmp_path / "c.json"
    p.write_text(
        json.dumps(
            {
                "version": 1,
                "credentials": {
                    BASE: {
                        "api_key": "sk-from-js",
                        "key_id": "key-9",
                        "account_id": "acct-9",
                        "account_name": None,
                        "expires_at": "2026-11-09T04:12:00Z",
                        "created_at": "2026-08-11T04:12:00Z",
                        "created_by": "sonilo-cli/0.12.0",
                    }
                },
            },
            indent=2,
        )
        + "\n"
    )
    cred = store.read_credential(BASE, p)
    assert cred["api_key"] == "sk-from-js"
    assert cred["account_name"] is None  # a POC-style account with no name
