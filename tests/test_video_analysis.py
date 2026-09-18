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


BOTH_BODY = {
    **SUCCESS_BODY,
    "mode": "both",
    "sfx_segments": [
        {"start": 0, "end": 4, "label": "none", "prompt": "wind, distant traffic"},
        {"start": 4, "end": 9, "label": "none", "prompt": "footsteps on gravel"},
    ],
    "sfx_prompt": "  naturalistic exterior ambience with sharp foley hits  ",
}


def test_parse_reads_mode_sfx_segments_and_sfx_prompt():
    """mode "both" adds a sound-design brief next to the music one: shot-sized
    `sfx_segments` and a single `sfx_prompt`, which is stripped."""
    result = parse_video_analysis_result(BOTH_BODY)
    assert result.mode == "both"
    assert [(s.start, s.end, s.label, s.prompt) for s in result.sfx_segments] == [
        (0, 4, "none", "wind, distant traffic"),
        (4, 9, "none", "footsteps on gravel"),
    ]
    assert result.sfx_prompt == "naturalistic exterior ambience with sharp foley hits"
    # The music half is untouched by the extra keys.
    assert [s.label for s in result.segments] == ["intro", "none"]
    assert len(result.variations) == 2


def test_parse_skips_malformed_sfx_segments():
    result = parse_video_analysis_result(
        {
            **BOTH_BODY,
            "sfx_segments": [
                "nope",
                {"start": "x", "end": 3, "prompt": "bad start"},
                {"start": 0, "end": 3, "prompt": "kept"},
            ],
        }
    )
    assert [s.prompt for s in result.sfx_segments] == ["kept"]
    assert result.sfx_segments[0].label == "none"


def test_parse_defaults_mode_and_sfx_fields_when_absent():
    """A pre-`mode` body (and a music/sfx-mode body) carries none of the
    three: mode None, an empty list and None, so callers need no guard."""
    result = parse_video_analysis_result(SUCCESS_BODY)
    assert result.mode is None
    assert result.sfx_segments == []
    assert result.sfx_prompt is None


@pytest.mark.parametrize("raw", ["", "   ", None, 7, ["not", "a", "string"]])
def test_parse_blank_or_non_string_sfx_prompt_reads_as_none(raw):
    result = parse_video_analysis_result({**BOTH_BODY, "sfx_prompt": raw})
    assert result.sfx_prompt is None


def test_parse_music_mode_echo_without_sfx_keys():
    result = parse_video_analysis_result({**SUCCESS_BODY, "mode": "music"})
    assert result.mode == "music"
    assert result.sfx_segments == []
    assert result.sfx_prompt is None


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
    assert "mode" not in sent


@respx.mock
def test_submit_sends_mode_only_when_set():
    """`mode` is a plain pass-through: sent verbatim when given, omitted when
    not so the server default ("both") applies. Values are not checked
    client-side, so an unknown one reaches the API rather than an SDK error."""
    route = respx.post("https://api.sonilo.com/v1/video-analysis").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    with Sonilo(api_key="sk-test") as client:
        client.video_analysis.submit(video_url="https://x/v.mp4", mode="sfx")
        sent = unquote_plus(route.calls.last.request.content.decode())
        assert "mode=sfx" in sent
        client.video_analysis.submit(video_url="https://x/v.mp4", mode="whatever")
        sent = unquote_plus(route.calls.last.request.content.decode())
        assert "mode=whatever" in sent


@respx.mock
def test_analyze_passes_mode_through_to_submit():
    route = respx.post("https://api.sonilo.com/v1/video-analysis").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    respx.get("https://api.sonilo.com/v1/tasks/va1").mock(
        return_value=httpx.Response(200, json=BOTH_BODY)
    )
    with Sonilo(api_key="sk-test") as client:
        result = client.video_analysis.analyze(
            video_url="https://x/v.mp4", mode="both", poll_interval=0
        )
    assert "mode=both" in unquote_plus(route.calls.last.request.content.decode())
    assert result.sfx_prompt == "naturalistic exterior ambience with sharp foley hits"


@respx.mock
async def test_async_analyze_passes_mode_through_to_submit():
    route = respx.post("https://api.sonilo.com/v1/video-analysis").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    respx.get("https://api.sonilo.com/v1/tasks/va1").mock(
        return_value=httpx.Response(200, json=BOTH_BODY)
    )
    async with AsyncSonilo(api_key="sk-test") as client:
        result = await client.video_analysis.analyze(
            video_url="https://x/v.mp4", mode="music", poll_interval=0
        )
    assert "mode=music" in unquote_plus(route.calls.last.request.content.decode())
    assert result.mode == "both"  # whatever the mocked task body says


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
