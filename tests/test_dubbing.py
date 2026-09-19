from pathlib import Path
from urllib.parse import unquote_plus

import httpx
import pytest
import respx

from sonilo import AsyncSonilo, DubbingTask, Sonilo
from sonilo.errors import SoniloError
from sonilo.types import SfxTask
from sonilo.resources.tasks import parse_dubbing_result, parse_dubbing_task

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
def test_submit_sends_ducking_only_when_set():
    route = respx.post("https://api.sonilo.com/v1/dubbing").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    with Sonilo(api_key="sk-test") as client:
        client.dubbing.submit(video_url="https://x/v.mp4", ducking=True)
        client.dubbing.submit(video_url="https://x/v.mp4", ducking=False)
        client.dubbing.submit(video_url="https://x/v.mp4")
    bodies = [unquote_plus(c.request.content.decode()) for c in route.calls]
    assert "ducking=true" in bodies[0]
    assert "ducking=false" in bodies[1]
    # Unset → omitted entirely so the server default (off) applies.
    assert "ducking" not in bodies[2]


@respx.mock
def test_submit_sends_lipsync_only_when_set():
    """The mirror of ducking, with the default the other way up: absent must
    mean lip sync ON, which is what every dubbing call did before the
    parameter existed."""
    route = respx.post("https://api.sonilo.com/v1/dubbing").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    with Sonilo(api_key="sk-test") as client:
        client.dubbing.submit(video_url="https://x/v.mp4", lipsync=False)
        client.dubbing.submit(video_url="https://x/v.mp4", lipsync=True)
        client.dubbing.submit(video_url="https://x/v.mp4")
    bodies = [unquote_plus(c.request.content.decode()) for c in route.calls]
    assert "lipsync=false" in bodies[0]
    assert "lipsync=true" in bodies[1]
    assert "lipsync" not in bodies[2]


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


# --- subtitles and export_srt ----------------------------------------------

SUBTITLED_BODY = {
    "task_id": "db1",
    "type": "dubbing",
    "status": "succeeded",
    "outputs": {"es": "https://r2/es.mp4", "fr": "https://r2/fr.mp4"},
    # fr's export was blocked: it still has a video, just no subtitle.
    "subtitles": {"es": "https://r2/es.srt"},
    # The pipeline's store returns numbers as strings, so a client that
    # surfaces these has to tolerate both shapes — hence "5" next to 4.
    "subtitle_preflight": {
        "es": {"status": "ok", "cue_count": "5", "issues": [], "changes_count": 0},
        "fr": {"status": "ok", "cue_count": 4, "issues": [], "changes_count": 0},
    },
    "subtitle_export": {
        "es": {"status": "exported", "alignment_loss": "0.6305176995017312"},
        "fr": {"status": "blocked", "error": "alignment failed"},
    },
}


def test_parse_dubbing_result_reads_the_subtitle_maps():
    result = parse_dubbing_result(SUBTITLED_BODY)
    assert result.subtitles == {"es": "https://r2/es.srt"}
    assert result.subtitle_preflight["es"]["cue_count"] == "5"
    assert result.subtitle_preflight["fr"]["cue_count"] == 4
    assert result.subtitle_export["fr"]["status"] == "blocked"


def test_parse_dubbing_result_defaults_the_subtitle_maps_to_empty():
    result = parse_dubbing_result(SUCCESS_BODY)
    assert result.subtitles == {}
    assert result.subtitle_preflight == {}
    assert result.subtitle_export == {}


def test_parse_dubbing_result_carries_the_free_preview():
    preview = {
        "preview_seconds": 15, "source_duration_seconds": 60.0, "trimmed": True,
        "languages": 1, "full_video_cost_usd": 3.49, "message": "Free preview: …",
    }
    result = parse_dubbing_result({**SUCCESS_BODY, "trial_preview": preview})
    assert result.trial_preview == preview


def test_parse_dubbing_result_has_no_preview_on_a_paid_run():
    assert parse_dubbing_result(SUCCESS_BODY).trial_preview is None
    assert parse_dubbing_result({**SUCCESS_BODY, "trial_preview": "nope"}).trial_preview is None


def test_parse_dubbing_result_drops_malformed_report_entries():
    result = parse_dubbing_result({
        "task_id": "db1", "status": "succeeded",
        "subtitles": "nope",
        "subtitle_export": {"es": "not-a-report", "fr": {"status": "exported"}},
    })
    assert result.subtitles == {}
    assert result.subtitle_export == {"fr": {"status": "exported"}}


@respx.mock
def test_save_subtitle_downloads_one_language(tmp_path):
    respx.get("https://r2/es.srt").mock(
        return_value=httpx.Response(200, content=b"1\nhola\n")
    )
    result = parse_dubbing_result(SUBTITLED_BODY)
    path = result.save_subtitle("es", tmp_path / "clip.es.srt")
    assert path.read_bytes() == b"1\nhola\n"


def test_save_subtitle_rejects_a_language_whose_export_was_blocked(tmp_path):
    result = parse_dubbing_result(SUBTITLED_BODY)
    with pytest.raises(SoniloError):
        result.save_subtitle("fr", tmp_path / "clip.fr.srt")


@respx.mock
def test_save_all_subtitles_skips_languages_without_one(tmp_path):
    respx.get("https://r2/es.srt").mock(
        return_value=httpx.Response(200, content=b"1\nhola\n")
    )
    result = parse_dubbing_result(SUBTITLED_BODY)
    paths = result.save_all_subtitles(tmp_path / "out")
    assert set(paths) == {"es"}
    assert (tmp_path / "out" / "dubbed.es.srt").read_bytes() == b"1\nhola\n"


@respx.mock
async def test_asave_subtitle_downloads_one_language(tmp_path):
    respx.get("https://r2/es.srt").mock(
        return_value=httpx.Response(200, content=b"1\nhola\n")
    )
    result = parse_dubbing_result(SUBTITLED_BODY)
    path = await result.asave_subtitle("es", tmp_path / "clip.es.srt")
    assert path.read_bytes() == b"1\nhola\n"


@respx.mock
def test_submit_sends_subtitle_urls_as_bracket_keyed_fields():
    route = respx.post("https://api.sonilo.com/v1/dubbing").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    with Sonilo(api_key="sk-test") as client:
        client.dubbing.submit(
            video_url="https://x/v.mp4",
            languages=["es", "fr"],
            subtitles={"es": "https://x/es.srt", "fr": "https://x/fr.vtt"},
            export_srt=True,
        )
    sent = unquote_plus(route.calls.last.request.content.decode())
    assert "subtitles[es]=https://x/es.srt" in sent
    assert "subtitles[fr]=https://x/fr.vtt" in sent
    assert "export_srt=true" in sent


@respx.mock
def test_submit_uploads_local_scripts_as_file_parts(tmp_path):
    route = respx.post("https://api.sonilo.com/v1/dubbing").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    script = tmp_path / "spanish.srt"
    script.write_text("1\n00:00:00,000 --> 00:00:01,000\nhola\n")
    with Sonilo(api_key="sk-test") as client:
        client.dubbing.submit(
            video_url="https://x/v.mp4", languages=["es"],
            subtitles={"es": str(script)}, export_srt=True,
        )
    body = route.calls.last.request.content.decode(errors="replace")
    assert 'name="subtitles[es]"' in body
    assert 'filename="spanish.srt"' in body


@respx.mock
def test_submit_closes_the_scripts_even_when_the_api_rejects_them(tmp_path, monkeypatch):
    """The 422 path is the one that leaks: preflight rejects a script set
    routinely, and those handles have to be closed all the same."""
    respx.post("https://api.sonilo.com/v1/dubbing").mock(
        return_value=httpx.Response(422, json={"error": {"code": "SUBTITLE_PREFLIGHT_BLOCKED"}})
    )
    script = tmp_path / "spanish.srt"
    script.write_text("1\n")
    opened = []
    real_open = Path.open

    def spy(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(Path, "open", spy)
    with Sonilo(api_key="sk-test") as client:
        with pytest.raises(SoniloError):
            client.dubbing.submit(
                video_url="https://x/v.mp4", languages=["es"],
                subtitles={"es": str(script)},
            )
    assert opened and all(handle.closed for handle in opened)


@respx.mock
def test_submit_rejects_export_srt_without_subtitles_before_sending():
    route = respx.post("https://api.sonilo.com/v1/dubbing")
    with Sonilo(api_key="sk-test") as client:
        with pytest.raises(SoniloError):
            client.dubbing.submit(video_url="https://x/v.mp4", export_srt=True)
    assert not route.called


@respx.mock
async def test_async_submit_sends_the_subtitle_fields():
    route = respx.post("https://api.sonilo.com/v1/dubbing").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    async with AsyncSonilo(api_key="sk-test") as client:
        await client.dubbing.submit(
            video_url="https://x/v.mp4", languages=["es"],
            subtitles={"es": "https://x/es.srt"}, export_srt=True,
        )
    sent = unquote_plus(route.calls.last.request.content.decode())
    assert "subtitles[es]=https://x/es.srt" in sent
    assert "export_srt=true" in sent


# --- the 202's preflight ---------------------------------------------------

PREFLIGHT_ACK = {
    "task_id": "db1",
    "status": "processing",
    "subtitle_preflight": {
        # The pipeline stores numbers as strings, so cue_count arrives as one.
        "es": {"status": "ok", "cue_count": "5", "issues": [], "changes_count": 0},
        "fr": {"status": "review_required", "cue_count": 4, "issues": ["line_shortened"],
               "changes_count": 2},
    },
}


@respx.mock
def test_submit_returns_the_preflight_from_the_ack():
    """The preflight is free and pre-charge: a review_required language is only
    actionable here, before the dub is billed."""
    respx.post("https://api.sonilo.com/v1/dubbing").mock(
        return_value=httpx.Response(202, json=PREFLIGHT_ACK)
    )
    with Sonilo(api_key="sk-test") as client:
        task = client.dubbing.submit(
            video_url="https://x/v.mp4", languages=["es", "fr"],
            subtitles={"es": "https://x/es.srt", "fr": "https://x/fr.srt"},
        )
    assert isinstance(task, DubbingTask)
    assert task.task_id == "db1" and task.status == "processing"
    assert task.subtitle_preflight["fr"]["status"] == "review_required"
    assert task.subtitle_preflight["es"]["cue_count"] == "5"


@respx.mock
def test_submit_without_scripts_has_an_empty_preflight():
    respx.post("https://api.sonilo.com/v1/dubbing").mock(
        return_value=httpx.Response(202, json=ACK)
    )
    with Sonilo(api_key="sk-test") as client:
        task = client.dubbing.submit(video_url="https://x/v.mp4")
    assert task.subtitle_preflight == {}


def test_parse_dubbing_task_drops_malformed_preflight_entries():
    task = parse_dubbing_task({
        "task_id": "db1",
        "subtitle_preflight": {"es": "not-a-report", "fr": {"status": "ok"}},
    })
    # Missing status defaults the same way the shared ack parser does.
    assert task.status == "processing"
    assert task.subtitle_preflight == {"fr": {"status": "ok"}}


def test_parse_dubbing_task_rejects_a_body_without_a_task_id():
    with pytest.raises(SoniloError):
        parse_dubbing_task({"status": "processing"})


def test_dubbing_task_extends_sfx_task_without_changing_it():
    """SfxTask acks every other async endpoint, so the preflight had to arrive
    as a new type rather than two more fields on the shared one."""
    assert issubclass(DubbingTask, SfxTask)
    assert not hasattr(SfxTask("t", "processing"), "subtitle_preflight")


@respx.mock
async def test_async_submit_returns_the_preflight_too():
    respx.post("https://api.sonilo.com/v1/dubbing").mock(
        return_value=httpx.Response(202, json=PREFLIGHT_ACK)
    )
    async with AsyncSonilo(api_key="sk-test") as client:
        task = await client.dubbing.submit(
            video_url="https://x/v.mp4",
            subtitles={"es": "https://x/es.srt", "fr": "https://x/fr.srt"},
        )
    assert task.subtitle_preflight["fr"]["changes_count"] == 2
