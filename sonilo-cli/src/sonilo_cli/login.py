"""`sonilo login` — the device-code flow, and the three commands built on it.

Behaviour is deliberately identical to the JS CLI (`packages/cli/src/login.ts`
in sonilo-js) down to the message wording: the two share one credential file, so
a user who signs in with either is signed in for both, and support answers must
not depend on which one they ran.

The device-code grant (RFC 8628 shaped) is used rather than a loopback redirect
because this has to work over SSH and inside containers, where nothing can bind
a local port the browser could reach.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import webbrowser
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

import httpx

from sonilo_cli import __version__, credentials

_TOO_MANY_ATTEMPTS = (
    "too many sign-in attempts right now — wait a minute and run sonilo login again"
)
_DENIED = "sign-in was denied in the browser — nothing was granted"
_EXPIRED = "that sign-in code expired — run sonilo login again"

_KEYS_URL = "https://platform.sonilo.com/dashboard/api-keys"


class LoginError(Exception):
    """A sign-in failure with a message meant for the user, not a traceback."""


def _api_base(args: argparse.Namespace) -> str:
    base = (
        getattr(args, "api_base", None)
        or os.environ.get("SONILO_API_URL")
        or credentials.DEFAULT_API_BASE
    )
    # Trailing slashes are stripped before the store is keyed, in every client:
    # `https://api.sonilo.com/` and `https://api.sonilo.com` are one account.
    return base.rstrip("/")


def _error_code(response: httpx.Response) -> Optional[str]:
    """The `error` field, or None. Only ever reads that one field — a response
    body can carry a key, and nothing here should risk printing it."""
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, dict) and isinstance(body.get("error"), str):
        return body["error"]
    return None


def start_device(
    api_base: str,
    *,
    client_version: str,
    hostname: str,
    os_name: str,
    http: httpx.Client,
) -> Dict[str, Any]:
    """Register this CLI instance and get the codes the user approves."""
    response = http.post(
        api_base + "/cli/auth/device/start",
        json={
            "client": "sonilo-cli-py",
            "client_version": client_version,
            "hostname": hostname,
            "os": os_name,
        },
    )
    if response.status_code == 429:
        raise LoginError(_TOO_MANY_ATTEMPTS)
    if response.status_code != 200:
        raise LoginError(
            "could not start sign-in (HTTP {}) — check your connection to {}".format(
                response.status_code, api_base
            )
        )
    try:
        start = response.json()
    except ValueError:
        raise LoginError("could not start sign-in — the server sent an unreadable response")
    for field in ("device_code", "user_code", "verification_uri_complete"):
        if not isinstance(start.get(field), str):
            raise LoginError("could not start sign-in — the server response was missing data")
    return start


def poll_for_token(
    api_base: str,
    start: Dict[str, Any],
    *,
    http: httpx.Client,
    sleep: Callable[[float], None],
    now: Callable[[], float],
) -> Dict[str, Any]:
    """Poll until the user approves, or the code dies.

    Polls first, then sleeps between attempts — matching the JS CLI exactly.
    The two clients share one credential file and talk to one throttle, so a
    cadence that differed between them would make the same sign-in behave
    differently depending on which CLI ran it. On `slow_down` the interval grows
    by a second and keeps it: the server's grace is `interval - 1`, so a client
    polling at the interval it was handed is never punished for it.
    """
    interval = float(start.get("interval") or 5)
    expires_in = float(start.get("expires_in") or 600)
    started = now()

    while True:
        if now() - started > expires_in:
            raise LoginError(_EXPIRED)

        response = http.post(
            api_base + "/cli/auth/device/token",
            json={"device_code": start["device_code"]},
        )
        if response.status_code == 200:
            try:
                token = response.json()
            except ValueError:
                raise LoginError("sign-in returned an unreadable response")
            # Every field is required, not just the key: `key_id` is what
            # logout and re-login revoke by, so accepting a response without
            # one would store a credential that can never be cleaned up.
            for field in ("api_key", "key_id", "account_id", "expires_at"):
                if not isinstance(token.get(field), str) or not token[field]:
                    raise LoginError("sign-in token response was missing required fields")
            if not (token.get("account_name") is None
                    or isinstance(token.get("account_name"), str)):
                raise LoginError("sign-in token response was missing required fields")
            return token

        code = _error_code(response)
        if code == "access_denied":
            raise LoginError(_DENIED)
        if code in ("expired_token", "invalid_grant"):
            raise LoginError(_EXPIRED)
        if code == "slow_down":
            interval += 1
        elif code != "authorization_pending":
            raise LoginError(
                "sign-in failed ({})".format(code or "HTTP {}".format(response.status_code))
            )

        sleep(interval)


# ---------- the three commands ----------


def _expiry_date(iso: str) -> str:
    """Just the date. Long enough to act on, short enough to read."""
    return iso[:10]


def _account_label(cred: Dict[str, Any]) -> str:
    """The account name, or its id when the backend has none on file."""
    name = cred.get("account_name")
    return name if isinstance(name, str) and name else str(cred.get("account_id", "your account"))


def _revoke(api_base: str, api_key: str, http: httpx.Client) -> bool:
    """Revoke the key that signs the request. True on success."""
    try:
        response = http.delete(
            api_base + "/v1/account/keys/self",
            headers={"Authorization": "Bearer " + api_key},
        )
    except httpx.HTTPError:
        return False
    return response.status_code in (200, 204)


def cmd_login(args: argparse.Namespace) -> None:
    api_base = _api_base(args)
    previous = credentials.read_credential(api_base)
    # An expired stored credential counts as not signed in: build_client tells
    # the user to run `sonilo login` again, and refusing here with "already
    # signed in, use --force" would send them in a circle.
    expired = previous is not None and _is_expired(previous.get("expires_at", ""))

    if previous and not expired and not getattr(args, "force", False):
        print(
            "Already signed in as {} (cli: {}, expires {}). "
            "Re-authenticate with --force.".format(
                _account_label(previous), socket.gethostname(),
                _expiry_date(previous.get("expires_at", "")),
            )
        )
        return

    http = httpx.Client(timeout=30)
    try:
        start = start_device(
            api_base,
            client_version=__version__,
            hostname=socket.gethostname(),
            os_name=sys.platform,
            http=http,
        )
        print("First copy your one-time code: " + start["user_code"])
        print("Then open this URL to confirm: " + start["verification_uri_complete"])
        if not getattr(args, "no_browser", False):
            try:
                webbrowser.open(start["verification_uri_complete"])
            except Exception:
                # A headless box has no browser to open; the URL is printed
                # above and polling continues either way.
                pass

        token = poll_for_token(api_base, start, http=http, sleep=_sleep, now=_now)

        credentials.write_credential(
            api_base,
            {
                "api_key": token["api_key"],
                "key_id": token.get("key_id"),
                "account_id": token.get("account_id"),
                "account_name": token.get("account_name"),
                "expires_at": token.get("expires_at"),
                # timezone.utc, not datetime.UTC: the latter is 3.11+ and this
                # package supports 3.9. utcnow() is deprecated on 3.12+.
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "created_by": "sonilo-cli-py/{}".format(__version__),
            },
        )

        # Save first, then revoke the key being replaced: the reverse order
        # would leave a --force run that fails mid-way with no working key at
        # all. Revoked by the id recorded locally, never by name.
        if previous and previous.get("api_key"):
            if not _revoke(api_base, previous["api_key"], http):
                print("Note: could not revoke the previous key. Remove it at " + _KEYS_URL)

        print(
            "Signed in as {}. Key expires {}.".format(
                _account_label(token), _expiry_date(token.get("expires_at", ""))
            )
        )
    finally:
        http.close()


def cmd_whoami(args: argparse.Namespace) -> None:
    api_base = _api_base(args)
    env_key = os.environ.get("SONILO_API_KEY")
    cred = credentials.read_credential(api_base)

    # Truthiness, matching build_client: SONILO_API_KEY="" must not claim to be
    # the active source when the CLI would fall through it to the credential.
    if env_key:
        print(
            "source: SONILO_API_KEY (the stored credential is being ignored)"
            if cred
            else "source: SONILO_API_KEY"
        )
        return

    if not cred:
        print("Not signed in. Run sonilo login.")
        return

    expires_at = cred.get("expires_at", "")
    print("account: " + _account_label(cred))
    # Prefix only — enough to match against the dashboard, useless if copied.
    print("key: {}...".format(cred["api_key"][:8]))
    print(
        "expires: {}{}".format(
            _expiry_date(expires_at), " (expired)" if _is_expired(expires_at) else ""
        )
    )
    print("source: credential file")


def cmd_logout(args: argparse.Namespace) -> None:
    api_base = _api_base(args)
    cred = credentials.read_credential(api_base)
    if not cred:
        print("Not signed in.")
        return

    if getattr(args, "local_only", False):
        credentials.remove_credential(api_base)
        print("Removed the local credential. The key is still valid — revoke it at " + _KEYS_URL)
        return

    http = httpx.Client(timeout=30)
    try:
        revoked = _revoke(api_base, cred["api_key"], http)
    finally:
        http.close()

    if not revoked:
        # Keep the credential: forgetting it here would leave a live key with
        # nothing left locally to revoke it by.
        print(
            "Could not revoke the key, so it is still valid and still stored. "
            "Revoke it at {} , or run `sonilo logout --local-only` to forget it "
            "here anyway.".format(_KEYS_URL)
        )
        raise SystemExit(1)

    credentials.remove_credential(api_base)
    print("Signed out.")


def _is_expired(iso: str) -> bool:
    """True only when the timestamp definitely parses and is in the past.

    `datetime.fromisoformat` cannot read a trailing `Z` on Python 3.9, which
    this package still supports, hence strptime. An unparseable timestamp is
    treated as *not* expired: the API is the authority on whether a key works,
    and locking someone out over a formatting quirk would be worse than letting
    a dead key earn its own 401.
    """
    if not iso:
        return False
    try:
        parsed = datetime.strptime(iso.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        try:
            parsed = datetime.strptime(iso.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S.%f%z")
        except ValueError:
            return False
    return parsed.timestamp() < _now()


def _now() -> float:
    import time

    return time.time()


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)
