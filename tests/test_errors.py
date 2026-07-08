import httpx
import pytest

from sonilo.errors import (
    APIError,
    AuthenticationError,
    BadRequestError,
    GenerationError,
    PaymentRequiredError,
    RateLimitError,
    SoniloError,
    error_from_response,
)


def make_response(status_code, json_body=None, text=None, headers=None):
    if json_body is not None:
        return httpx.Response(status_code, json=json_body, headers=headers)
    return httpx.Response(status_code, text=text or "", headers=headers)


def test_401_maps_to_authentication_error():
    err = error_from_response(make_response(401, {"detail": "Invalid API key"}))
    assert isinstance(err, AuthenticationError)
    assert err.status_code == 401
    assert "Invalid API key" in str(err)


def test_402_maps_to_payment_required():
    err = error_from_response(make_response(402, {"detail": "Insufficient balance"}))
    assert isinstance(err, PaymentRequiredError)


def test_429_maps_to_rate_limit_with_retry_after():
    err = error_from_response(
        make_response(429, {"detail": "Rate limit exceeded"}, headers={"retry-after": "7"})
    )
    assert isinstance(err, RateLimitError)
    assert err.retry_after == 7.0


def test_429_without_header_has_no_retry_after():
    err = error_from_response(make_response(429, {"detail": "Rate limit exceeded"}))
    assert err.retry_after is None


@pytest.mark.parametrize("status", [400, 413, 422])
def test_4xx_maps_to_bad_request_with_detail(status):
    err = error_from_response(make_response(status, {"detail": "bad input"}))
    assert isinstance(err, BadRequestError)
    assert err.detail == "bad input"


def test_other_status_maps_to_api_error_with_text_body():
    err = error_from_response(make_response(500, text="boom"))
    assert isinstance(err, APIError)
    assert not isinstance(err, BadRequestError)
    assert err.status_code == 500
    assert err.body == "boom"


def test_generation_error_carries_code():
    err = GenerationError("failed", code="PROXY_ERROR")
    assert isinstance(err, SoniloError)
    assert err.code == "PROXY_ERROR"
