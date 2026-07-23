"""Client-identity headers.

First-party wrappers (the CLI, the video kit) sit on top of this SDK, so
without an override every one of their calls reports as `sdk-python` and
becomes indistinguishable from direct SDK use in server-side analytics.
"""

import httpx
import pytest
import respx

from sonilo import AsyncSonilo, Sonilo
from sonilo._client import DEFAULT_CLIENT_NAME
from sonilo._version import __version__

BASE = "https://api.sonilo.com"
SERVICES = {"available_services": []}


def _stub():
    return respx.get(f"{BASE}/v1/account/services").mock(
        return_value=httpx.Response(200, json=SERVICES)
    )


@respx.mock
def test_defaults_to_sdk_python():
    route = _stub()
    Sonilo(api_key="sk-test").account.services()
    headers = route.calls.last.request.headers
    assert headers["x-sonilo-client"] == "sdk-python"
    assert headers["x-sonilo-client-version"] == __version__


def test_default_client_name_constant():
    assert DEFAULT_CLIENT_NAME == "sdk-python"


@respx.mock
def test_client_name_and_version_are_overridable():
    route = _stub()
    Sonilo(api_key="sk-test", client_name="cli-python", client_version="1.2.3").account.services()
    headers = route.calls.last.request.headers
    assert headers["x-sonilo-client"] == "cli-python"
    assert headers["x-sonilo-client-version"] == "1.2.3"


@respx.mock
def test_overrides_are_independent():
    """Naming a wrapper must not force it to also restate a version, and vice versa."""
    route = _stub()
    Sonilo(api_key="sk-test", client_name="kit-python-video").account.services()
    headers = route.calls.last.request.headers
    assert headers["x-sonilo-client"] == "kit-python-video"
    assert headers["x-sonilo-client-version"] == __version__

    Sonilo(api_key="sk-test", client_version="9.9.9").account.services()
    headers = route.calls.last.request.headers
    assert headers["x-sonilo-client"] == "sdk-python"
    assert headers["x-sonilo-client-version"] == "9.9.9"


@respx.mock
@pytest.mark.asyncio
async def test_async_client_honours_the_same_overrides():
    route = _stub()
    await AsyncSonilo(
        api_key="sk-test", client_name="cli-python", client_version="1.2.3"
    ).account.services()
    headers = route.calls.last.request.headers
    assert headers["x-sonilo-client"] == "cli-python"
    assert headers["x-sonilo-client-version"] == "1.2.3"


@respx.mock
@pytest.mark.asyncio
async def test_async_defaults_to_sdk_python():
    route = _stub()
    await AsyncSonilo(api_key="sk-test").account.services()
    headers = route.calls.last.request.headers
    assert headers["x-sonilo-client"] == "sdk-python"
    assert headers["x-sonilo-client-version"] == __version__
