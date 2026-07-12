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


def test_400_maps_to_bad_request_with_code_and_message_envelope():
    err = error_from_response(
        make_response(
            400,
            {"code": "invalid_request", "message": "audio_format must be one of wav, mp3, aac, flac"},
        )
    )
    assert isinstance(err, BadRequestError)
    assert "audio_format must be one of" in str(err)
    assert err.code == "invalid_request"
    assert err.detail == "audio_format must be one of wav, mp3, aac, flac"


def test_401_maps_to_authentication_error():
    err = error_from_response(
        make_response(401, {"code": "unauthorized", "message": "Invalid API key"})
    )
    assert isinstance(err, AuthenticationError)
    assert err.status_code == 401
    assert "Invalid API key" in str(err)
    assert err.code == "unauthorized"


def test_402_maps_to_payment_required():
    err = error_from_response(
        make_response(402, {"code": "payment_required", "message": "Insufficient balance"})
    )
    assert isinstance(err, PaymentRequiredError)
    assert "Insufficient balance" in str(err)


def test_404_maps_to_api_error_with_code():
    err = error_from_response(
        make_response(404, {"code": "not_found", "message": "Task not found"})
    )
    assert isinstance(err, APIError)
    assert err.status_code == 404
    assert err.code == "not_found"


def test_422_maps_to_bad_request_with_errors_array():
    body = {
        "code": "unprocessable_entity",
        "message": "Input should be less than or equal to 180",
        "errors": [
            {
                "loc": ["body", "duration"],
                "msg": "Input should be less than or equal to 180",
                "type": "less_than_equal",
            }
        ],
    }
    err = error_from_response(make_response(422, body))
    assert isinstance(err, BadRequestError)
    assert "Input should be less than or equal to 180" in str(err)
    assert err.errors is not None
    assert len(err.errors) == 1
    assert err.errors[0]["msg"] == "Input should be less than or equal to 180"


def test_429_maps_to_rate_limit_with_retry_after_and_code():
    err = error_from_response(
        make_response(
            429,
            {"code": "rate_limit_exceeded", "message": "Rate limit exceeded"},
            headers={"retry-after": "30"},
        )
    )
    assert isinstance(err, RateLimitError)
    assert err.retry_after == 30.0
    assert err.code == "rate_limit_exceeded"


def test_429_without_header_has_no_retry_after():
    err = error_from_response(make_response(429, {"code": "rate_limit_exceeded", "message": "Rate limit exceeded"}))
    assert err.retry_after is None


@pytest.mark.parametrize("status", [400, 413, 422])
def test_4xx_maps_to_bad_request_with_legacy_detail(status):
    err = error_from_response(make_response(status, {"detail": "bad input"}))
    assert isinstance(err, BadRequestError)
    assert err.detail == "bad input"
    assert "bad input" in str(err)


def test_body_without_message_or_detail_falls_back_to_reason_phrase():
    err = error_from_response(make_response(422, {}))
    assert "Unprocessable Entity" in str(err)


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
