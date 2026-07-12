from __future__ import annotations

from typing import Any, List, Optional

import httpx


class SoniloError(Exception):
    """Base class for every error raised by this SDK."""


class APIError(SoniloError):
    def __init__(self, message: str, status_code: int, body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.code: Optional[str] = None
        self.errors: Optional[List[Any]] = None
        if isinstance(body, dict):
            code = body.get("code")
            if isinstance(code, str):
                self.code = code
            errors = body.get("errors")
            if isinstance(errors, list):
                self.errors = errors


class AuthenticationError(APIError):
    pass


class PaymentRequiredError(APIError):
    pass


class BadRequestError(APIError):
    @property
    def detail(self) -> Optional[str]:
        if isinstance(self.body, dict):
            message = self.body.get("message")
            if isinstance(message, str) and message:
                return message
            detail = self.body.get("detail")
            if isinstance(detail, str):
                return detail
        return None


class RateLimitError(APIError):
    def __init__(
        self,
        message: str,
        status_code: int,
        body: Any = None,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message, status_code, body)
        self.retry_after = retry_after


class GenerationError(SoniloError):
    """Raised by generate() when an `error` event arrives mid-stream."""

    def __init__(self, message: str, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


class TaskFailedError(SoniloError):
    """Raised by tasks.wait()/generate() when an SFX task reaches `failed`."""

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        task_id: Optional[str] = None,
        refunded: Optional[bool] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.task_id = task_id
        self.refunded = refunded


class TaskTimeoutError(SoniloError):
    """Poll deadline passed. The task may still finish server-side — resume
    with tasks.wait(task_id) or tasks.get(task_id)."""

    def __init__(self, message: str, *, task_id: Optional[str] = None) -> None:
        super().__init__(message)
        self.task_id = task_id


def error_from_response(response: httpx.Response) -> APIError:
    """Map a non-2xx response to a typed error.

    For streamed responses the body must already have been read
    (`response.read()` / `await response.aread()`).
    """
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    reason = None
    if isinstance(body, dict):
        api_message = body.get("message")
        if isinstance(api_message, str) and api_message:
            reason = api_message
        else:
            detail = body.get("detail")
            if detail:
                reason = detail if isinstance(detail, str) else str(detail)
    message = f"HTTP {response.status_code}: {reason or response.reason_phrase or 'request failed'}"
    status = response.status_code

    if status == 401:
        return AuthenticationError(message, status, body)
    if status == 402:
        return PaymentRequiredError(message, status, body)
    if status == 429:
        raw = response.headers.get("retry-after")
        retry_after: Optional[float]
        try:
            retry_after = float(raw) if raw is not None else None
        except ValueError:
            retry_after = None
        return RateLimitError(message, status, body, retry_after=retry_after)
    if status in (400, 413, 422):
        return BadRequestError(message, status, body)
    return APIError(message, status, body)
