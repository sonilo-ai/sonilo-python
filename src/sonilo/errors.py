from __future__ import annotations

from typing import Any, Optional

import httpx


class SoniloError(Exception):
    """Base class for every error raised by this SDK."""


class APIError(SoniloError):
    def __init__(self, message: str, status_code: int, body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class AuthenticationError(APIError):
    pass


class PaymentRequiredError(APIError):
    pass


class BadRequestError(APIError):
    @property
    def detail(self) -> Optional[str]:
        if isinstance(self.body, dict):
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


def error_from_response(response: httpx.Response) -> APIError:
    """Map a non-2xx response to a typed error.

    For streamed responses the body must already have been read
    (`response.read()` / `await response.aread()`).
    """
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    detail = body.get("detail") if isinstance(body, dict) else None
    message = f"HTTP {response.status_code}: {detail or response.reason_phrase or 'request failed'}"
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
