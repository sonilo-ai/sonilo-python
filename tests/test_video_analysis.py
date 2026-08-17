from urllib.parse import unquote_plus

import httpx
import pytest
import respx

from sonilo import AsyncSonilo, Sonilo
from sonilo.errors import SoniloError
from sonilo.resources.tasks import parse_video_analysis_result

SUCCESS_BODY = {
    "task_id": "va1",
    "type": "video_analysis",
    "status": "succeeded",
    "variants_num": 2,
    "segments": [
        {"start": 0, "end": 12, "label": "intro", "prompt": "sparse piano, rising"},
        {"start": 12, "end": 30, "label": "none", "prompt": "full strings, driving"},
    ],
    "variations": [
        {"prompt": "cinematic strings, 90bpm"},
        {"prompt": "lo-fi hip hop, warm keys"},
    ],
    "duration_seconds": 30.0,
    "cost": 0.24,
}


def test_parse_reads_segments_and_variations():
    result = parse_video_analysis_result(SUCCESS_BODY)
    assert result.task_id == "va1"
    assert result.status == "succeeded"
    assert result.type == "video_analysis"
    assert result.variants_num == 2
    assert result.duration_seconds == 30.0
    assert result.cost == 0.24
    assert [(s.start, s.end, s.label, s.prompt) for s in result.segments] == [
        (0, 12, "intro", "sparse piano, rising"),
        (12, 30, "none", "full strings, driving"),
    ]
    assert [v.prompt for v in result.variations] == [
        "cinematic strings, 90bpm",
        "lo-fi hip hop, warm keys",
    ]


def test_parse_defaults_segments_and_variations_to_empty():
    """A processing task carries neither list; they must read as empty rather
    than None so callers can iterate without a guard."""
    result = parse_video_analysis_result({"task_id": "va1", "status": "processing"})
    assert result.segments == []
    assert result.variations == []


def test_parse_skips_malformed_entries():
    """A backend change that adds a differently-shaped entry must not turn
    into an AttributeError deep in the caller's loop."""
    result = parse_video_analysis_result(
        {
            "task_id": "va1",
            "status": "succeeded",
            "segments": ["nope", {"start": 0, "end": 3, "prompt": "kept"}],
            "variations": [{"no_prompt": 1}, {"prompt": "kept too"}],
        }
    )
    assert [s.prompt for s in result.segments] == ["kept"]
    assert result.segments[0].label == "none"
    assert [v.prompt for v in result.variations] == ["kept too"]


def test_parse_rejects_a_body_without_a_task_id():
    with pytest.raises(SoniloError):
        parse_video_analysis_result({"status": "succeeded"})


ACK = {"task_id": "va1", "status": "processing"}


@respx.mock
def test_submit_posts_to_v1_video_analysis():
    route = respx.post("https://api.sonilo.com/v1/video-analysis").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    with Sonilo(api_key="sk-test") as client:
        task = client.video_analysis.submit(
            video_url="https://x/v.mp4", prompt="focus on the chase", variants_num=2
        )
    assert task.task_id == "va1"
    sent = unquote_plus(route.calls.last.request.content.decode())
    assert "video_url=https://x/v.mp4" in sent
    assert "prompt=focus on the chase" in sent
    assert "variants_num=2" in sent


@respx.mock
def test_submit_omits_unset_optionals():
    route = respx.post("https://api.sonilo.com/v1/video-analysis").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    with Sonilo(api_key="sk-test") as client:
        client.video_analysis.submit(video_url="https://x/v.mp4")
    sent = unquote_plus(route.calls.last.request.content.decode())
    assert "prompt" not in sent
    assert "variants_num" not in sent


@respx.mock
def test_submit_requires_exactly_one_input():
    route = respx.post("https://api.sonilo.com/v1/video-analysis")
    with Sonilo(api_key="sk-test") as client:
        with pytest.raises(SoniloError):
            client.video_analysis.submit()
        with pytest.raises(SoniloError):
            client.video_analysis.submit(video="v.mp4", video_url="https://x/v.mp4")
    assert not route.called


@respx.mock
def test_submit_uploads_a_local_file(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake-mp4")
    route = respx.post("https://api.sonilo.com/v1/video-analysis").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    with Sonilo(api_key="sk-test") as client:
        client.video_analysis.submit(video=str(clip))
    body = route.calls.last.request.content
    assert b"fake-mp4" in body
    assert b'filename="clip.mp4"' in body


@respx.mock
def test_analyze_polls_to_a_video_analysis_result():
    respx.post("https://api.sonilo.com/v1/video-analysis").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    respx.get("https://api.sonilo.com/v1/tasks/va1").mock(
        return_value=httpx.Response(200, json=SUCCESS_BODY)
    )
    with Sonilo(api_key="sk-test") as client:
        result = client.video_analysis.analyze(
            video_url="https://x/v.mp4", variants_num=2, poll_interval=0
        )
    assert [v.prompt for v in result.variations] == [
        "cinematic strings, 90bpm",
        "lo-fi hip hop, warm keys",
    ]


@respx.mock
async def test_async_analyze_polls_to_a_video_analysis_result():
    respx.post("https://api.sonilo.com/v1/video-analysis").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    respx.get("https://api.sonilo.com/v1/tasks/va1").mock(
        return_value=httpx.Response(200, json=SUCCESS_BODY)
    )
    async with AsyncSonilo(api_key="sk-test") as client:
        result = await client.video_analysis.analyze(
            video_url="https://x/v.mp4", poll_interval=0
        )
    assert result.segments[0].label == "intro"
