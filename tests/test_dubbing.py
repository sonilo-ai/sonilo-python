from urllib.parse import unquote_plus

import httpx
import pytest
import respx

from sonilo.errors import SoniloError
from sonilo.resources.tasks import parse_dubbing_result

SUCCESS_BODY = {
    "task_id": "db1",
    "type": "dubbing",
    "status": "succeeded",
    "outputs": {"es": "https://r2/es.mp4", "fr": "https://r2/fr.mp4"},
    "duration_seconds": 12.5,
    "cost": 0.36,
}


def test_parse_dubbing_result_reads_the_outputs_map():
    result = parse_dubbing_result(SUCCESS_BODY)
    assert result.task_id == "db1"
    assert result.status == "succeeded"
    assert result.type == "dubbing"
    assert result.outputs == {
        "es": "https://r2/es.mp4",
        "fr": "https://r2/fr.mp4",
    }
    assert result.duration_seconds == 12.5
    assert result.cost == 0.36


def test_parse_dubbing_result_defaults_outputs_to_empty():
    result = parse_dubbing_result({"task_id": "db1", "status": "processing"})
    assert result.outputs == {}


def test_parse_dubbing_result_rejects_a_body_without_a_task_id():
    with pytest.raises(SoniloError):
        parse_dubbing_result({"status": "succeeded"})


@respx.mock
def test_save_downloads_one_language(tmp_path):
    respx.get("https://r2/es.mp4").mock(
        return_value=httpx.Response(200, content=b"es-bytes")
    )
    result = parse_dubbing_result(SUCCESS_BODY)
    path = result.save("es", tmp_path / "clip.es.mp4")
    assert path.read_bytes() == b"es-bytes"


def test_save_rejects_a_language_the_task_did_not_produce(tmp_path):
    result = parse_dubbing_result(SUCCESS_BODY)
    with pytest.raises(SoniloError):
        result.save("de", tmp_path / "clip.de.mp4")


@respx.mock
def test_save_all_writes_one_file_per_language(tmp_path):
    respx.get("https://r2/es.mp4").mock(
        return_value=httpx.Response(200, content=b"es-bytes")
    )
    respx.get("https://r2/fr.mp4").mock(
        return_value=httpx.Response(200, content=b"fr-bytes")
    )
    result = parse_dubbing_result(SUCCESS_BODY)
    paths = result.save_all(tmp_path / "out")
    assert set(paths) == {"es", "fr"}
    assert (tmp_path / "out" / "dubbed.es.mp4").read_bytes() == b"es-bytes"
    assert (tmp_path / "out" / "dubbed.fr.mp4").read_bytes() == b"fr-bytes"


@respx.mock
async def test_asave_downloads_one_language(tmp_path):
    respx.get("https://r2/fr.mp4").mock(
        return_value=httpx.Response(200, content=b"fr-bytes")
    )
    result = parse_dubbing_result(SUCCESS_BODY)
    path = await result.asave("fr", tmp_path / "clip.fr.mp4")
    assert path.read_bytes() == b"fr-bytes"


from sonilo import AsyncSonilo, Sonilo

ACK = {"task_id": "db1", "status": "processing"}


@respx.mock
def test_submit_posts_to_v1_dubbing():
    route = respx.post("https://api.sonilo.com/v1/dubbing").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    with Sonilo(api_key="sk-test") as client:
        task = client.dubbing.submit(
            video_url="https://x/v.mp4", languages=["es", "fr"]
        )
    assert task.task_id == "db1"
    # video_url-only submissions have no file part, so httpx sends this as
    # application/x-www-form-urlencoded (not multipart) and percent-escapes
    # the JSON array; unquote before checking for the raw JSON substring.
    sent = unquote_plus(route.calls.last.request.content.decode())
    assert "video_url" in sent
    assert '["es", "fr"]' in sent


@respx.mock
def test_generate_polls_to_a_dubbing_result():
    respx.post("https://api.sonilo.com/v1/dubbing").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    respx.get("https://api.sonilo.com/v1/tasks/db1").mock(
        return_value=httpx.Response(200, json=SUCCESS_BODY)
    )
    with Sonilo(api_key="sk-test") as client:
        result = client.dubbing.generate(
            video_url="https://x/v.mp4", languages=["es", "fr"], poll_interval=0
        )
    assert result.outputs["es"] == "https://r2/es.mp4"
    assert result.outputs["fr"] == "https://r2/fr.mp4"


@respx.mock
def test_submit_rejects_a_non_https_url_before_sending():
    route = respx.post("https://api.sonilo.com/v1/dubbing")
    with Sonilo(api_key="sk-test") as client:
        with pytest.raises(SoniloError):
            client.dubbing.submit(video_url="http://x/v.mp4")
    assert not route.called


@respx.mock
async def test_async_generate_polls_to_a_dubbing_result():
    respx.post("https://api.sonilo.com/v1/dubbing").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    respx.get("https://api.sonilo.com/v1/tasks/db1").mock(
        return_value=httpx.Response(200, json=SUCCESS_BODY)
    )
    async with AsyncSonilo(api_key="sk-test") as client:
        result = await client.dubbing.generate(
            video_url="https://x/v.mp4", poll_interval=0
        )
    assert result.outputs["fr"] == "https://r2/fr.mp4"
