from pathlib import Path
from urllib.parse import unquote_plus

import httpx
import pytest
import respx

from sonilo import AsyncSonilo, ProofreadIssue, ProofreadResult, Sonilo
from sonilo._requests import build_proofread_parts
from sonilo.errors import SoniloError
from sonilo.types import SfxTask
from sonilo.resources.tasks import parse_proofread_result

# The real prod body (task 4288764d..., 2026-09-18), URLs shortened. Keeping
# the actual shape means the parser is checked against what the API sends —
# including `warnings` carrying a code with its own measurement field.
SUCCESS_BODY = {
    "task_id": "4288764d-0057-4a77-885e-03c0391c7c1d",
    "type": "proofread",
    "status": "succeeded",
    "duration_seconds": 206.32,
    "source_language": "en",
    "subtitles": {
        "en": "https://r2/en.srt",
        "ko": "https://r2/ko.srt",
        "fr": "https://r2/fr.srt",
        "de": "https://r2/de.srt",
        "ar": "https://r2/ar.srt",
        "th": "https://r2/th.srt",
        "ru": "https://r2/ru.srt",
    },
    "cue_count": 65,
    "warnings": {
        "fr": [
            {
                "cue": 33,
                "code": "high_text_speed",
                "severity": "warning",
                "characters_per_second": 26.92,
            }
        ]
    },
}

ACK = {"task_id": "pr1", "status": "processing"}


# --- result parsing --------------------------------------------------------


def test_parse_proofread_result_reads_the_subtitles_map():
    result = parse_proofread_result(SUCCESS_BODY)
    assert result.task_id == "4288764d-0057-4a77-885e-03c0391c7c1d"
    assert result.status == "succeeded"
    assert result.type == "proofread"
    assert result.source_language == "en"
    assert result.cue_count == 65
    assert result.duration_seconds == 206.32
    # The detected source language is always in the map, alongside the
    # requested targets.
    assert "en" in result.subtitles
    assert result.subtitles["fr"] == "https://r2/fr.srt"
    assert len(result.subtitles) == 7


def test_parse_proofread_result_reads_the_warnings():
    result = parse_proofread_result(SUCCESS_BODY)
    assert set(result.warnings) == {"fr"}
    issue = result.warnings["fr"][0]
    assert isinstance(issue, ProofreadIssue)
    assert issue.cue == 33
    assert issue.code == "high_text_speed"
    assert issue.severity == "warning"
    # Everything past the three named fields is kept verbatim, because each
    # server-owned code brings its own measurement.
    assert issue.extras == {"characters_per_second": 26.92}
    assert issue.get("characters_per_second") == 26.92
    assert issue.get("nothing_like_this") is None


def test_parse_proofread_result_defaults_warnings_to_empty():
    result = parse_proofread_result(
        {"task_id": "pr1", "status": "succeeded", "subtitles": {"en": "https://r2/en.srt"}}
    )
    assert result.warnings == {}
    assert result.source_language is None
    assert result.cue_count is None


def test_parse_proofread_result_defaults_subtitles_to_empty():
    result = parse_proofread_result({"task_id": "pr1", "status": "processing"})
    assert result.subtitles == {}


def test_parse_proofread_result_tolerates_stringy_numbers():
    """A store that keeps numbers as strings is what made dubbing's reports
    arrive as strings; read either shape here rather than crash."""
    result = parse_proofread_result(
        {
            "task_id": "pr1",
            "status": "succeeded",
            "cue_count": "65",
            "warnings": {"fr": [{"cue": "7", "code": "high_text_speed"}]},
        }
    )
    assert result.cue_count == 65
    assert result.warnings["fr"][0].cue == 7
    # severity is defaulted rather than dropped, so callers can print it.
    assert result.warnings["fr"][0].severity == "warning"


def test_parse_proofread_result_drops_malformed_warning_entries():
    result = parse_proofread_result(
        {
            "task_id": "pr1",
            "status": "succeeded",
            "subtitles": "nope",
            "warnings": {"fr": "not-a-list", "de": ["not-an-issue", {"code": "x"}]},
        }
    )
    assert result.subtitles == {}
    assert "fr" not in result.warnings
    assert [issue.code for issue in result.warnings["de"]] == ["x"]


def test_parse_proofread_result_rejects_a_body_without_a_task_id():
    with pytest.raises(SoniloError):
        parse_proofread_result({"status": "succeeded"})


# --- saving ----------------------------------------------------------------


@respx.mock
def test_save_downloads_one_language(tmp_path):
    respx.get("https://r2/fr.srt").mock(
        return_value=httpx.Response(200, content=b"1\nbonjour\n")
    )
    result = parse_proofread_result(SUCCESS_BODY)
    path = result.save("fr", tmp_path / "clip.fr.srt")
    assert path.read_bytes() == b"1\nbonjour\n"


def test_save_rejects_a_language_the_task_did_not_produce(tmp_path):
    result = parse_proofread_result(SUCCESS_BODY)
    with pytest.raises(SoniloError):
        result.save("es", tmp_path / "clip.es.srt")


@respx.mock
def test_save_all_writes_one_srt_per_language(tmp_path):
    for language in SUCCESS_BODY["subtitles"]:
        respx.get(f"https://r2/{language}.srt").mock(
            return_value=httpx.Response(200, content=f"{language}-bytes".encode())
        )
    result = parse_proofread_result(SUCCESS_BODY)
    paths = result.save_all(tmp_path / "out")
    assert set(paths) == set(SUCCESS_BODY["subtitles"])
    assert (tmp_path / "out" / "proofread.en.srt").read_bytes() == b"en-bytes"
    assert (tmp_path / "out" / "proofread.ko.srt").read_bytes() == b"ko-bytes"


@respx.mock
async def test_asave_downloads_one_language(tmp_path):
    respx.get("https://r2/de.srt").mock(
        return_value=httpx.Response(200, content=b"1\nhallo\n")
    )
    result = parse_proofread_result(SUCCESS_BODY)
    path = await result.asave("de", tmp_path / "clip.de.srt")
    assert path.read_bytes() == b"1\nhallo\n"


# --- request shape ---------------------------------------------------------


@respx.mock
def test_submit_posts_to_v1_proofread():
    route = respx.post("https://api.sonilo.com/v1/proofread").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    with Sonilo(api_key="sk-test") as client:
        task = client.proofread.submit(
            video_url="https://x/v.mp4", languages=["ja", "zh_cn"]
        )
    assert isinstance(task, SfxTask)
    assert task.task_id == "pr1" and task.status == "processing"
    # video_url-only submissions have no file part, so httpx sends this as
    # application/x-www-form-urlencoded (not multipart) and percent-escapes
    # the JSON array; unquote before checking for the raw JSON substring.
    sent = unquote_plus(route.calls.last.request.content.decode())
    assert "video_url=https://x/v.mp4" in sent
    assert '["ja", "zh_cn"]' in sent


@respx.mock
def test_submit_omits_languages_when_unset():
    """Omitting the field is what asks for the transcript alone; sending
    `languages=None` as a string would be a 422."""
    route = respx.post("https://api.sonilo.com/v1/proofread").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    with Sonilo(api_key="sk-test") as client:
        client.proofread.submit(video_url="https://x/v.mp4")
    assert b"languages" not in route.calls.last.request.content


@respx.mock
def test_submit_sends_an_explicit_empty_language_list():
    """Unlike dubbing, `[]` is meaningful here — it is the explicit spelling
    of "transcript only" — so it goes on the wire rather than being dropped."""
    route = respx.post("https://api.sonilo.com/v1/proofread").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    with Sonilo(api_key="sk-test") as client:
        client.proofread.submit(video_url="https://x/v.mp4", languages=[])
    sent = unquote_plus(route.calls.last.request.content.decode())
    assert "languages=[]" in sent


@respx.mock
def test_submit_sends_source_language_only_when_given():
    route = respx.post("https://api.sonilo.com/v1/proofread").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    with Sonilo(api_key="sk-test") as client:
        client.proofread.submit(video_url="https://x/v.mp4", source_language="en")
        client.proofread.submit(video_url="https://x/v.mp4")
    bodies = [unquote_plus(c.request.content.decode()) for c in route.calls]
    assert "source_language=en" in bodies[0]
    # Unset → omitted entirely so the server detects the language itself.
    assert "source_language" not in bodies[1]


@respx.mock
def test_submit_uploads_a_local_video_as_a_file_part(tmp_path):
    route = respx.post("https://api.sonilo.com/v1/proofread").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    clip = tmp_path / "interview.mp4"
    clip.write_bytes(b"fake-mp4")
    with Sonilo(api_key="sk-test") as client:
        client.proofread.submit(video=str(clip), languages=["ja"])
    body = route.calls.last.request.content.decode(errors="replace")
    assert 'name="video"' in body
    assert 'filename="interview.mp4"' in body
    # multipart, so the JSON array travels as a plain field value.
    assert '["ja"]' in body


@respx.mock
def test_submit_rejects_a_non_https_url_before_sending():
    route = respx.post("https://api.sonilo.com/v1/proofread")
    with Sonilo(api_key="sk-test") as client:
        with pytest.raises(SoniloError):
            client.proofread.submit(video_url="http://x/v.mp4")
    assert not route.called


@respx.mock
def test_submit_requires_exactly_one_video_input():
    route = respx.post("https://api.sonilo.com/v1/proofread")
    with Sonilo(api_key="sk-test") as client:
        with pytest.raises(SoniloError):
            client.proofread.submit()
        with pytest.raises(SoniloError):
            client.proofread.submit(video=b"bytes", video_url="https://x/v.mp4")
    assert not route.called


@respx.mock
def test_submit_closes_a_local_video_even_when_the_api_rejects_it(tmp_path, monkeypatch):
    respx.post("https://api.sonilo.com/v1/proofread").mock(
        return_value=httpx.Response(422, json={"error": {"code": "unprocessable_entity"}})
    )
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake-mp4")
    opened = []
    real_open = Path.open

    def spy(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(Path, "open", spy)
    with Sonilo(api_key="sk-test") as client:
        with pytest.raises(SoniloError):
            client.proofread.submit(video=str(clip))
    assert opened and all(handle.closed for handle in opened)


def test_build_proofread_parts_passes_unknown_codes_through():
    """Language codes are server-owned, exactly as on dubbing: a code this
    SDK has never heard of must reach the API and earn its own 422."""
    data, _, _ = build_proofread_parts(None, "https://x/v.mp4", ["klingon"], "klingon")
    assert data["languages"] == '["klingon"]'
    assert data["source_language"] == "klingon"


# --- polling ---------------------------------------------------------------


@respx.mock
def test_generate_polls_to_a_proofread_result():
    respx.post("https://api.sonilo.com/v1/proofread").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    respx.get("https://api.sonilo.com/v1/tasks/pr1").mock(
        return_value=httpx.Response(200, json=dict(SUCCESS_BODY, task_id="pr1"))
    )
    with Sonilo(api_key="sk-test") as client:
        result = client.proofread.generate(
            video_url="https://x/v.mp4", languages=["fr", "de"], poll_interval=0
        )
    assert isinstance(result, ProofreadResult)
    assert result.source_language == "en"
    assert result.subtitles["fr"] == "https://r2/fr.srt"
    assert result.warnings["fr"][0].code == "high_text_speed"


@respx.mock
def test_tasks_get_parses_a_proofread_task():
    respx.get("https://api.sonilo.com/v1/tasks/pr1").mock(
        return_value=httpx.Response(200, json=dict(SUCCESS_BODY, task_id="pr1"))
    )
    with Sonilo(api_key="sk-test") as client:
        result = client.tasks.get("pr1", parser=parse_proofread_result)
    assert result.type == "proofread"
    assert result.cue_count == 65


@respx.mock
async def test_async_generate_polls_to_a_proofread_result():
    respx.post("https://api.sonilo.com/v1/proofread").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    respx.get("https://api.sonilo.com/v1/tasks/pr1").mock(
        return_value=httpx.Response(200, json=dict(SUCCESS_BODY, task_id="pr1"))
    )
    async with AsyncSonilo(api_key="sk-test") as client:
        result = await client.proofread.generate(
            video_url="https://x/v.mp4", source_language="en", poll_interval=0
        )
    assert result.subtitles["en"] == "https://r2/en.srt"


@respx.mock
async def test_async_submit_sends_the_same_fields():
    route = respx.post("https://api.sonilo.com/v1/proofread").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    async with AsyncSonilo(api_key="sk-test") as client:
        await client.proofread.submit(
            video_url="https://x/v.mp4", languages=["ja"], source_language="en"
        )
    sent = unquote_plus(route.calls.last.request.content.decode())
    assert '["ja"]' in sent
    assert "source_language=en" in sent
