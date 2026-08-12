"""Test isolation for anything that reads the user's environment.

`test_cli.py` has always passed `--api-key` explicitly, so nothing here used to
matter. Credential-file support changes that: without these fixtures the CLI
under test would read the developer's real `~/.config/sonilo/credentials.json`
and a passing suite would depend on whether they happen to be logged in.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.delenv("SONILO_API_KEY", raising=False)
    monkeypatch.delenv("SONILO_API_URL", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    return tmp_path
