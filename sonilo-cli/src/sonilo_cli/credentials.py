"""The credential file written by `sonilo login`.

Format and location are shared with the JS CLI (`packages/cli/src/credentials.ts`
in sonilo-js) and read by sonilo-mcp, so the path, the JSON shape and the
0600/0700 modes are a cross-repo contract — change them in all three or not at
all.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_API_BASE = "https://api.sonilo.com"
FORMAT_VERSION = 1


class CredentialFormatError(Exception):
    """The file was written by a newer client than this one understands."""


def credentials_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path(os.environ.get("HOME", str(Path.home()))) / ".config"
    return root / "sonilo" / "credentials.json"


def _empty() -> Dict[str, Any]:
    return {"version": FORMAT_VERSION, "credentials": {}}


def _load(path: Path) -> Dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return _empty()
    try:
        parsed = json.loads(raw)
    except ValueError:
        # Corrupt file reads as "no credential"; `login` will replace it.
        return _empty()
    if not isinstance(parsed, dict):
        return _empty()
    version = parsed.get("version")
    if isinstance(version, int) and version > FORMAT_VERSION:
        raise CredentialFormatError(
            f"{path} was written by a newer sonilo CLI (format {version}). "
            "Upgrade the CLI or delete the file."
        )
    creds = parsed.get("credentials")
    return {
        "version": FORMAT_VERSION,
        "credentials": creds if isinstance(creds, dict) else {},
    }


def _save(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_name(path.name + ".{}.tmp".format(os.getpid()))
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    try:
        # Rename last: an interrupted write can never replace a whole
        # credential with half of one.
        os.replace(tmp, path)
    except OSError:
        # Never leave the temp file behind holding a live key.
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def read_credential(api_base: str, path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    entry = _load(path or credentials_path())["credentials"].get(api_base)
    if isinstance(entry, dict) and isinstance(entry.get("api_key"), str) and entry["api_key"]:
        return entry
    return None


def write_credential(
    api_base: str, cred: Dict[str, Any], path: Optional[Path] = None
) -> None:
    target = path or credentials_path()
    data = _load(target)
    data["credentials"][api_base] = cred
    _save(target, data)


def remove_credential(api_base: str, path: Optional[Path] = None) -> None:
    target = path or credentials_path()
    data = _load(target)
    if api_base not in data["credentials"]:
        return
    del data["credentials"][api_base]
    if not data["credentials"]:
        try:
            target.unlink()
        except OSError:
            pass
        return
    _save(target, data)
