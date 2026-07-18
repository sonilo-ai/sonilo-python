"""Ducking API transport: submit / poll / download (ported from ducking-api.ts).

Self-contained HTTP layer for the async `/v1/audio-ducking` endpoint. Three
concerns live here, matching the JS reference:

  - submit_ducking_job: POSTs the voice+music tracks. This is what CHARGES
    the account, so it is deliberately NEVER retried (see its docstring).
  - await_ducking_result: polls GET /v1/tasks/{id} until the task leaves
    "processing", retrying transient (5xx / network) failures — the task
    keeps running server-side no matter what happens to this client.
  - download_ducked_mix: fetches the finished mix from its presigned URL
    (a DIFFERENT, unauthenticated host — never routed through client._http,
    so the customer's API key never reaches it), guarded against SSRF and
    bounded by a byte cap / exact-size check.
"""
from __future__ import annotations

import ipaddress
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Protocol
from urllib.parse import quote, urlsplit

import httpx
from sonilo.errors import error_from_response

from ._ffmpeg import StrPath
from .errors import DuckingFailedError, VideoKitError

Sleep = Callable[[float], None]


class DuckingClient(Protocol):
    """The minimal client surface the ducking calls need — satisfied by
    `sonilo.Sonilo`, whose `_http` is a configured httpx.Client (base_url
    https://api.sonilo.com, Authorization header already set)."""

    _http: httpx.Client


@dataclass
class DuckingResult:
    output_url: str
    output_type: str
    output_bytes: Optional[int] = None


# One initial try plus three retries.
_MAX_ATTEMPTS = 4
_RETRY_BASE_SECONDS = 0.5
_RETRY_MAX_SECONDS = 4.0

# Task/submit JSON envelopes are a few hundred bytes; 1 MB is orders of
# magnitude of headroom while still capping a compromised API trying to OOM
# the client.
MAX_JSON_BYTES = 1024 * 1024

# Per-attempt wall-clock cap for the mix download, mirroring ducking-api.ts's
# DEFAULT_DOWNLOAD_TIMEOUT_MS.
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 120.0


class _HttpStatusError(VideoKitError):
    """A non-2xx from the (unauthed) download host. Carries `status_code` so
    `_is_transient` classifies it exactly like the sonilo SDK's own
    APIError (which also carries `status_code`)."""

    def __init__(self, status_code: int, what: str) -> None:
        super().__init__(f"{what} (HTTP {status_code})")
        self.status_code = status_code


def _retry_delay_seconds(attempt: int) -> float:
    return min(_RETRY_BASE_SECONDS * (2 ** (attempt - 1)), _RETRY_MAX_SECONDS)


def _is_transient(err: BaseException) -> bool:
    """Worth another go? Mirrors ducking-api.ts's isTransient: a numeric
    status >= 500 is transient (covers both the sonilo SDK's APIError and our
    own _HttpStatusError); any other VideoKitError is terminal; anything else
    (a network-level failure — connection reset, DNS, TLS) is transient."""
    status = getattr(err, "status_code", None)
    if isinstance(status, int):
        return status >= 500
    if isinstance(err, VideoKitError):
        return False
    return isinstance(err, Exception)


def _with_retry(op: "Callable[[], Any]", *, sleep: Sleep) -> Any:
    attempt = 1
    while True:
        try:
            return op()
        except Exception as err:  # noqa: BLE001 - reclassified below
            if attempt >= _MAX_ATTEMPTS or not _is_transient(err):
                raise
            sleep(_retry_delay_seconds(attempt))
            attempt += 1


def _parse_json_capped(response: httpx.Response, what: str) -> Any:
    """`response.json()`, but refusing to trust a body over MAX_JSON_BYTES."""
    if len(response.content) > MAX_JSON_BYTES:
        raise VideoKitError(
            f"The ducking API's {what} response exceeded {MAX_JSON_BYTES} bytes; "
            "refusing to buffer it."
        )
    return response.json()


# ---------------------------------------------------------------------------
# submit_ducking_job
# ---------------------------------------------------------------------------


def submit_ducking_job(client: DuckingClient, voice_path: StrPath, music_path: StrPath) -> str:
    """POST the voice and music tracks to /v1/audio-ducking. Returns the task
    id; the endpoint is async (submit + poll).

    Deliberately NOT retried, unlike the poll and the download below: the
    POST is what CHARGES the account (the backend charges in the request
    handler, before the background job is even spawned), and it carries no
    idempotency key. A retry after a response we failed to read would risk
    submitting — and paying for — the same job twice. Failing here is safe;
    failing after here is what has to be recovered (see duck.py's rescue
    path)."""
    voice = Path(voice_path)
    music = Path(music_path)
    files = {
        "voice_file": (voice.name, voice.read_bytes()),
        "music_file": (music.name, music.read_bytes()),
    }
    response = client._http.post("/v1/audio-ducking", files=files)
    if response.status_code >= 400:
        raise error_from_response(response)
    body = _parse_json_capped(response, "submit")
    task_id = body.get("task_id") if isinstance(body, dict) else None
    if not task_id:
        raise VideoKitError("The ducking API accepted the request but returned no task_id")
    return task_id


# ---------------------------------------------------------------------------
# await_ducking_result
# ---------------------------------------------------------------------------


def _extract_error_fields(body: "dict[str, Any]") -> "tuple[str, str]":
    """The task's failure code/message. The backend's documented envelope
    nests them under `error: {code, message}` (matching the sonilo SDK's
    other task endpoints and ducking-api.ts's TaskBody); tolerate a flat
    top-level `code`/`message` too, in case an older or alternate envelope
    omits the wrapper."""
    error = body.get("error")
    if isinstance(error, dict):
        code = error.get("code") or "DUCKING_FAILED"
        message = error.get("message") or "the ducking task failed"
    else:
        code = body.get("code") or "DUCKING_FAILED"
        message = body.get("message") or "the ducking task failed"
    return str(code), str(message)


def _dedup_failed_message(message: str, code: str, refunded: bool) -> str:
    """Compose the final DuckingFailedError message, ported from errors.ts's
    DuckingFailedError constructor (kept here rather than in errors.py: the
    Python DuckingFailedError, ported earlier, stores its message as given —
    this is the one call site that needs the composed text).

    The server derives `code` by splitting its own error_message on ":"
    (error_message = "DUCKING_FAILED: audio processing failed"), so both
    fields carry the code and a naive compose renders it twice. Strip the
    "{code}:" prefix from `message` first."""
    prefix = f"{code}:"
    detail = message[len(prefix):].strip() if message.startswith(prefix) else message
    detail = detail or message
    note = (
        " — the charge was refunded"
        if refunded
        else (
            " — the charge had not been reversed yet when the task was polled; the server "
            "reverses it after marking the task failed, and retries a reversal that fails, "
            "so it may still land. Check your usage before assuming you were billed for this."
        )
    )
    return f"Ducking failed [{code}]: {detail}{note}"


def _poll_task(client: DuckingClient, task_id: str) -> "dict[str, Any]":
    response = client._http.get(f"/v1/tasks/{quote(task_id, safe='')}")
    if response.status_code >= 400:
        raise error_from_response(response)
    body = _parse_json_capped(response, "task")
    if not isinstance(body, dict):
        raise VideoKitError(f"Ducking task {task_id} returned a malformed response")
    return body


def _sanitize_output_bytes(value: Any) -> Optional[int]:
    """Only ever a POSITIVE integer or None. A real ducking artifact is never
    0 bytes, and a fractional/negative/wrong-typed value is not a byte
    count — see the extensive comment on this exact check in ducking-api.ts."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def await_ducking_result(
    client: DuckingClient,
    task_id: str,
    *,
    poll_interval: float,
    timeout: float,
    deadline: Optional[float] = None,
    sleep: Sleep = time.sleep,
) -> DuckingResult:
    """Poll GET /v1/tasks/{id} until the task leaves `processing`.

    `deadline` is an absolute `time.monotonic()` ceiling; when omitted it is
    computed from `timeout`. duck.py passes the same deadline into both this
    call and download_ducked_mix, so one budget governs polling AND the
    download together (see duck.ts's "ONE deadline governs the WHOLE
    post-submit collection")."""
    effective_deadline = deadline if deadline is not None else time.monotonic() + timeout

    while True:
        body = _with_retry(lambda: _poll_task(client, task_id), sleep=sleep)
        status = body.get("status")

        if status == "succeeded":
            output_url = body.get("output_url")
            if not output_url:
                raise VideoKitError(f"Ducking task {task_id} succeeded but carried no output_url")
            return DuckingResult(
                output_url=output_url,
                output_type=body.get("output_type") or "audio",
                output_bytes=_sanitize_output_bytes(body.get("output_bytes")),
            )

        if status == "failed":
            code, message = _extract_error_fields(body)
            refunded = bool(body.get("refunded", False))
            raise DuckingFailedError(
                _dedup_failed_message(message, code, refunded), code=code, refunded=refunded
            )

        if time.monotonic() + poll_interval >= effective_deadline:
            raise VideoKitError(f"Ducking task {task_id} did not finish within {timeout}s")
        sleep(poll_interval)


# ---------------------------------------------------------------------------
# assert_safe_download_url / download_ducked_mix
# ---------------------------------------------------------------------------


def assert_safe_download_url(url: str) -> None:
    """Validate the presigned download URL before fetching it.

    `output_url` arrives in the task body, i.e. from the API — which a
    compromise could turn hostile. Unchecked, it is an SSRF primitive. This
    raises the bar against the obvious payloads:
      - only `https` is allowed (a presigned R2 GET always is);
      - IP-literal hosts (v4/v6), `localhost`, and `*.local` / `*.internal`
        are refused — the cloud-metadata (169.254.169.254), loopback, and
        internal-DNS targets an SSRF aims at, never a real presigned host.

    What it does NOT stop: a public hostname that resolves to a private
    address (DNS rebinding) — out of scope for a zero-dependency kit; the
    download additionally disables redirects so a 200-looking URL cannot
    302 into internal infrastructure.

    On rejection: name only the scheme or host, never the full URL — its
    query string carries the signing signature (a capability), and errors
    get logged."""
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise VideoKitError(
            "The ducking API returned an output_url that is not a valid URL."
        ) from exc
    if parsed.scheme != "https":
        raise VideoKitError(
            f'The ducking API\'s output_url uses an unsupported scheme "{parsed.scheme}"; '
            "only https is allowed for the presigned download."
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise VideoKitError("The ducking API returned an output_url with no host.")

    is_ip_literal = False
    try:
        ipaddress.ip_address(host)
        is_ip_literal = True
    except ValueError:
        is_ip_literal = False

    # Strip the DNS-root trailing dot(s) before the named-host blocklist, so
    # "localhost." (which resolves identically to "localhost") cannot sneak
    # through. Comparison-only: the fetch below still uses the original URL.
    named_host = host.rstrip(".")
    if (
        is_ip_literal
        or named_host == "localhost"
        or named_host.endswith(".local")
        or named_host.endswith(".internal")
    ):
        raise VideoKitError(
            f'The ducking API\'s output_url points at a non-public host "{host}", which is '
            "never a legitimate presigned download location; refusing to fetch it."
        )


def download_ducked_mix(
    url: str,
    dest_path: StrPath,
    *,
    max_bytes: int,
    expected_bytes: Optional[int] = None,
    timeout: Optional[float] = None,
    deadline: Optional[float] = None,
    sleep: Sleep = time.sleep,
) -> None:
    """Download the finished mix, streamed to `dest_path` without ever
    leaving partial bytes there.

    Deliberately uses a FRESH, unauthenticated httpx.Client, never
    `client._http`: `url` is a presigned link on a different host, and
    routing it through the authenticated client would put the customer's
    API key on a request to that host. Redirects are disabled (a presigned
    GET never legitimately 302s). Retried through transient failures — by
    the time there is something to download, the task has succeeded and the
    account has been charged, so losing the mix to one 503 would mean
    paying twice for it."""
    assert_safe_download_url(url)
    per_attempt = timeout if timeout is not None else DEFAULT_DOWNLOAD_TIMEOUT_SECONDS
    dest = Path(dest_path)

    def _attempt() -> None:
        attempt_timeout = per_attempt
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise VideoKitError(
                    "The ducked-mix download did not complete within the overall time "
                    "budget for this operation (shared with polling) and was stopped "
                    "before starting a fresh attempt past it."
                )
            attempt_timeout = min(per_attempt, remaining)

        tmp_path = dest.parent / f".{dest.name}.{uuid.uuid4().hex}.part"
        with httpx.Client(follow_redirects=False, timeout=attempt_timeout) as http:
            try:
                with http.stream("GET", url) as response:
                    if response.status_code >= 400:
                        raise _HttpStatusError(
                            response.status_code, "Could not download the ducked mix"
                        )
                    total = 0
                    with open(tmp_path, "wb") as handle:
                        for chunk in response.iter_bytes():
                            total += len(chunk)
                            if total > max_bytes:
                                raise VideoKitError(
                                    "The ducked mix exceeded the maximum allowed size "
                                    f"({max_bytes} bytes) and was refused."
                                )
                            handle.write(chunk)
                    if expected_bytes is not None and total != expected_bytes:
                        raise VideoKitError(
                            f"The ducked mix download was {total} bytes but the ducking "
                            f"API declared exactly {expected_bytes} bytes; refusing this "
                            "truncated or altered download."
                        )
                    os.replace(tmp_path, dest)
            except Exception:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                raise

    _with_retry(_attempt, sleep=sleep)
