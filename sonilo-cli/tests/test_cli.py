import io
import json
from urllib.parse import unquote_plus

import httpx
import pytest
import respx

from sonilo_cli.__main__ import main

BASE = "https://api.sonilo.com"


def run(argv, api_key="sk-test"):
    full = (["--api-key", api_key] if api_key is not None else []) + argv
    main(full)


@respx.mock
def test_account_prints_json(capsys):
    respx.get(f"{BASE}/v1/account/services").mock(
        return_value=httpx.Response(200, json={"plan": "pro"})
    )
    run(["account"])
    out = json.loads(capsys.readouterr().out)
    assert out == {"plan": "pro"}


@respx.mock
def test_account_prints_trial_summary_on_stderr(capsys):
    services = {
        "available_services": ["text_to_music", "video_to_music"],
        "rpm_limit": 60,
        "concurrency_limit": 5,
        "discount_factor": 1.0,
        "max_upload_size_mb": 300,
        "trial": {
            "text_to_music": {"granted": 2, "used": 1, "remaining": 1},
            "video_to_music": {"granted": 1, "used": 1, "remaining": 0},
        },
    }
    respx.get(f"{BASE}/v1/account/services").mock(
        return_value=httpx.Response(200, json=services)
    )
    run(["account"])
    captured = capsys.readouterr()
    # stdout stays parseable JSON; the summary is on stderr.
    assert json.loads(captured.out) == services
    assert captured.err.strip() == (
        "Free trial: text-to-music 1/2 left, video-to-music 0/1 left"
    )


@respx.mock
def test_account_prints_no_summary_without_trial(capsys):
    respx.get(f"{BASE}/v1/account/services").mock(
        return_value=httpx.Response(200, json={"available_services": []})
    )
    run(["account"])
    assert capsys.readouterr().err == ""


@respx.mock
def test_trial_exhausted_error_shows_the_code(capsys):
    respx.get(f"{BASE}/v1/account/services").mock(
        return_value=httpx.Response(
            402,
            json={
                "code": "trial_exhausted",
                "message": "You've used your 2 free trial calls for text-to-music.",
            },
        )
    )
    with pytest.raises(SystemExit) as exc:
        run(["account"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "free trial calls for text-to-music" in err
    assert "(trial_exhausted)" in err


@respx.mock
def test_usage_passes_days(capsys):
    route = respx.get(f"{BASE}/v1/account/usage").mock(
        return_value=httpx.Response(200, json={"days": 7})
    )
    run(["usage", "--days", "7"])
    assert route.calls.last.request.url.params["days"] == "7"


def test_missing_api_key_exits_1(capsys, monkeypatch):
    monkeypatch.delenv("SONILO_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        main(["account"])  # no --api-key, no env
    assert exc.value.code == 1
    assert "no API key" in capsys.readouterr().err


def test_unknown_command_exits_1(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--api-key", "sk-test", "frobnicate"])
    assert exc.value.code == 1
    assert "sonilo:" in capsys.readouterr().err


@respx.mock
def test_api_error_has_no_traceback(capsys):
    respx.get(f"{BASE}/v1/account/services").mock(
        return_value=httpx.Response(401, json={"error": {"message": "bad key"}})
    )
    with pytest.raises(SystemExit) as exc:
        run(["account"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("sonilo:")
    assert "Traceback" not in err


def _music_stream_body():
    # Minimal NDJSON stream matching sonilo._streaming.collect_track: an
    # audio_chunk event (base64 "data", decoded by iter_events) followed by
    # the terminal "complete" event. Confirmed against tests/test_streaming.py.
    import base64

    chunk = {"type": "audio_chunk", "data": base64.b64encode(b"ID3xx").decode()}
    done = {"type": "complete"}
    return "\n".join(json.dumps(e) for e in (chunk, done)) + "\n"


@respx.mock
def test_text_to_music_streaming_saves_m4a(tmp_path, capsys):
    respx.post(f"{BASE}/v1/text-to-music").mock(
        return_value=httpx.Response(200, text=_music_stream_body())
    )
    out = tmp_path / "song.m4a"
    run(["text-to-music", "--prompt", "lofi", "--duration", "10", "--output", str(out)])
    assert out.read_bytes() == b"ID3xx"
    assert "Wrote" in capsys.readouterr().out


@respx.mock
def test_text_to_music_wav_forces_async(tmp_path):
    submit = respx.post(f"{BASE}/v1/text-to-music").mock(
        return_value=httpx.Response(200, json={"task_id": "t1", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/t1").mock(
        return_value=httpx.Response(200, json={
            "task_id": "t1", "type": "text_to_music", "status": "succeeded",
            "audio": [{"stream_index": 0, "url": "https://r2.example.com/a.wav",
                       "content_type": "audio/wav", "file_size": 3}],
        })
    )
    respx.get("https://r2.example.com/a.wav").mock(
        return_value=httpx.Response(200, content=b"RIF")
    )
    out = tmp_path / "song.wav"
    run(["text-to-music", "--prompt", "lofi", "--duration", "10",
         "--format", "wav", "--output", str(out)])
    # Async path used: a submit POST happened AND polling GET happened.
    assert submit.called
    assert out.read_bytes() == b"RIF"


@respx.mock
def test_text_to_music_variants_forces_async_and_writes_indexed_files(tmp_path):
    submit = respx.post(f"{BASE}/v1/text-to-music").mock(
        return_value=httpx.Response(200, json={"task_id": "tv1", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/tv1").mock(
        return_value=httpx.Response(200, json={
            "task_id": "tv1", "type": "text_to_music", "status": "succeeded",
            "variants_num": 2,
            "audio": [
                {"stream_index": 0, "url": "https://r2.example.com/tv1.0.m4a"},
                {"stream_index": 1, "url": "https://r2.example.com/tv1.1.m4a"},
            ],
        })
    )
    respx.get("https://r2.example.com/tv1.0.m4a").mock(
        return_value=httpx.Response(200, content=b"A0")
    )
    respx.get("https://r2.example.com/tv1.1.m4a").mock(
        return_value=httpx.Response(200, content=b"A1")
    )
    out = tmp_path / "take.m4a"
    run(["text-to-music", "--prompt", "lofi", "--duration", "10",
         "--variants", "2", "--output", str(out)])
    # --variants > 1 must force the async submit-and-poll path, same as --format wav.
    assert submit.called
    body = submit.calls.last.request.content.decode()
    assert "variants_num=2" in body
    assert (tmp_path / "take.0.m4a").read_bytes() == b"A0"
    assert (tmp_path / "take.1.m4a").read_bytes() == b"A1"
    assert not out.exists()


def test_video_to_music_requires_a_video_source():
    with pytest.raises(SystemExit) as exc:
        run(["video-to-music", "--prompt", "x"])  # neither --video nor --video-url
    assert exc.value.code == 1


def test_video_to_music_rejects_both_sources():
    with pytest.raises(SystemExit) as exc:
        run(["video-to-music", "--video", "a.mp4", "--video-url", "http://x/y.mp4"])
    assert exc.value.code == 1


@respx.mock
def test_text_to_sfx_saves_wav(tmp_path):
    respx.post(f"{BASE}/v1/text-to-sfx").mock(
        return_value=httpx.Response(200, json={"task_id": "s1", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/s1").mock(
        return_value=httpx.Response(200, json={
            "task_id": "s1", "type": "text_to_sfx", "status": "succeeded",
            "audio": {"url": "https://r2.example.com/s.wav",
                      "content_type": "audio/wav", "file_size": 3},
        })
    )
    respx.get("https://r2.example.com/s.wav").mock(
        return_value=httpx.Response(200, content=b"RIF")
    )
    out = tmp_path / "fx.wav"
    run(["text-to-sfx", "--prompt", "glass break", "--duration", "3", "--output", str(out)])
    assert out.read_bytes() == b"RIF"


@respx.mock
def test_text_to_sfx_format_maps_to_audio_format(tmp_path):
    route = respx.post(f"{BASE}/v1/text-to-sfx").mock(
        return_value=httpx.Response(200, json={"task_id": "s2", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/s2").mock(
        return_value=httpx.Response(200, json={
            "task_id": "s2", "type": "text_to_sfx", "status": "succeeded",
            "audio": {"url": "https://r2.example.com/s.mp3",
                      "content_type": "audio/mpeg", "file_size": 3},
        })
    )
    respx.get("https://r2.example.com/s.mp3").mock(
        return_value=httpx.Response(200, content=b"ID3")
    )
    run(["text-to-sfx", "--prompt", "x", "--duration", "2",
         "--format", "mp3", "--output", str(tmp_path / "fx.mp3")])
    # The request body is form-encoded (per build_sfx_t2s_data/_post_json, and
    # confirmed against tests/test_sfx.py::test_text_to_sfx_submit_posts_form),
    # not JSON. It carries the chosen format under audio_format.
    body = route.calls.last.request.content.decode()
    assert "audio_format=mp3" in body


def test_video_to_sfx_requires_a_video_source():
    with pytest.raises(SystemExit) as exc:
        run(["video-to-sfx", "--prompt", "x"])
    assert exc.value.code == 1


@respx.mock
def test_tasks_get_prints_raw_json(capsys):
    respx.get(f"{BASE}/v1/tasks/abc").mock(
        return_value=httpx.Response(200, json={"task_id": "abc", "status": "processing"})
    )
    run(["tasks", "get", "abc"])
    assert json.loads(capsys.readouterr().out) == {"task_id": "abc", "status": "processing"}


@respx.mock
def test_tasks_wait_polls_until_succeeded(capsys):
    respx.get(f"{BASE}/v1/tasks/abc").mock(
        side_effect=[
            httpx.Response(200, json={"task_id": "abc", "status": "processing"}),
            httpx.Response(200, json={"task_id": "abc", "status": "succeeded"}),
        ]
    )
    run(["tasks", "wait", "abc", "--poll-interval", "0"])
    assert json.loads(capsys.readouterr().out)["status"] == "succeeded"


@respx.mock
def test_tasks_wait_failed_exits_1(capsys):
    respx.get(f"{BASE}/v1/tasks/abc").mock(
        return_value=httpx.Response(200, json={"task_id": "abc", "status": "failed"})
    )
    with pytest.raises(SystemExit) as exc:
        run(["tasks", "wait", "abc", "--poll-interval", "0"])
    assert exc.value.code == 1


def test_tasks_unknown_subcommand_exits_1(capsys):
    with pytest.raises(SystemExit) as exc:
        run(["tasks", "frob", "abc"])
    assert exc.value.code == 1


# --- video-to-sound / video-to-video-sound -------------------------------
#
# Fixture shape confirmed against tests/test_video_to_sound.py::SUCCESS_BODY
# in the SDK repo.

SOUND_SUCCESS_BODY = {
    "task_id": "sd1",
    "type": "video_to_sound",
    "status": "succeeded",
    "output_url": "https://r2.example.com/sound.wav",
    "output_type": "audio",
    "output_bytes": 5,
    "music": {"url": "https://r2.example.com/sound.music.m4a",
              "content_type": "audio/mp4", "file_size": 5},
    "sfx": {"url": "https://r2.example.com/sound.sfx.wav",
            "content_type": "audio/wav", "file_size": 3},
}


def _sound_body(task_id, **overrides):
    return {**SOUND_SUCCESS_BODY, "task_id": task_id, **overrides}


@respx.mock
def test_video_to_sound_saves_combined_output(tmp_path):
    respx.post(f"{BASE}/v1/video-to-sound").mock(
        return_value=httpx.Response(200, json={"task_id": "sd1", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/sd1").mock(
        return_value=httpx.Response(200, json=_sound_body("sd1"))
    )
    respx.get("https://r2.example.com/sound.wav").mock(
        return_value=httpx.Response(200, content=b"MIXED")
    )
    out = tmp_path / "s.wav"
    run(["video-to-sound", "--video-url", "http://x/y.mp4", "--output", str(out)])
    assert out.read_bytes() == b"MIXED"


@respx.mock
def test_video_to_sound_stem_flag_saves_stems_alongside(tmp_path):
    respx.post(f"{BASE}/v1/video-to-sound").mock(
        return_value=httpx.Response(200, json={"task_id": "sd2", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/sd2").mock(
        return_value=httpx.Response(200, json=_sound_body("sd2"))
    )
    respx.get("https://r2.example.com/sound.wav").mock(
        return_value=httpx.Response(200, content=b"MIXED")
    )
    respx.get("https://r2.example.com/sound.music.m4a").mock(
        return_value=httpx.Response(200, content=b"MUSIC")
    )
    respx.get("https://r2.example.com/sound.sfx.wav").mock(
        return_value=httpx.Response(200, content=b"SFX")
    )
    out = tmp_path / "s.wav"
    run(["video-to-sound", "--video-url", "http://x/y.mp4", "--output", str(out),
         "--stem", "music", "--stem", "sfx"])
    assert (tmp_path / "s.music.m4a").read_bytes() == b"MUSIC"
    assert (tmp_path / "s.sfx.wav").read_bytes() == b"SFX"


@respx.mock
def test_video_to_sound_ducking_absent_omits_field(tmp_path):
    route = respx.post(f"{BASE}/v1/video-to-sound").mock(
        return_value=httpx.Response(200, json={"task_id": "sd3", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/sd3").mock(
        return_value=httpx.Response(200, json=_sound_body("sd3"))
    )
    respx.get("https://r2.example.com/sound.wav").mock(
        return_value=httpx.Response(200, content=b"MIXED")
    )
    run(["video-to-sound", "--video-url", "http://x/y.mp4",
         "--output", str(tmp_path / "s.wav")])
    # ducking is default-OFF server-side, and neither flag was passed, so the
    # CLI must forward `None`, not `False` — the field has to be absent from
    # the form-encoded body (per build_v2s_parts) and let the server decide.
    body = route.calls.last.request.content.decode()
    assert "ducking=" not in body


@respx.mock
@pytest.mark.parametrize(
    "flag, wire",
    [
        # --ducking is the direction that does something now that the server
        # default is off; --no-ducking predates the flip, still parses so
        # existing scripts do not break, and states the default explicitly.
        ("--ducking", "ducking=true"),
        ("--no-ducking", "ducking=false"),
    ],
)
def test_video_to_sound_ducking_flags(tmp_path, flag, wire):
    route = respx.post(f"{BASE}/v1/video-to-sound").mock(
        return_value=httpx.Response(200, json={"task_id": "sd4", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/sd4").mock(
        return_value=httpx.Response(200, json=_sound_body("sd4"))
    )
    respx.get("https://r2.example.com/sound.wav").mock(
        return_value=httpx.Response(200, content=b"MIXED")
    )
    run(["video-to-sound", "--video-url", "http://x/y.mp4",
         "--output", str(tmp_path / "s.wav"), flag])
    body = route.calls.last.request.content.decode()
    assert wire in body


def test_video_to_sound_rejects_both_ducking_flags(tmp_path):
    with pytest.raises(SystemExit):
        run(["video-to-sound", "--video-url", "http://x/y.mp4",
             "--output", str(tmp_path / "s.wav"), "--ducking", "--no-ducking"])


@respx.mock
def test_video_to_sound_preserve_speech_absent_omits_field(tmp_path):
    route = respx.post(f"{BASE}/v1/video-to-sound").mock(
        return_value=httpx.Response(200, json={"task_id": "sd5", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/sd5").mock(
        return_value=httpx.Response(200, json=_sound_body("sd5"))
    )
    respx.get("https://r2.example.com/sound.wav").mock(
        return_value=httpx.Response(200, content=b"MIXED")
    )
    run(["video-to-sound", "--video-url", "http://x/y.mp4",
         "--output", str(tmp_path / "s.wav")])
    body = route.calls.last.request.content.decode()
    assert "preserve_speech=" not in body


@respx.mock
def test_video_to_sound_preserve_speech_flag_sets_true(tmp_path):
    route = respx.post(f"{BASE}/v1/video-to-sound").mock(
        return_value=httpx.Response(200, json={"task_id": "sd6", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/sd6").mock(
        return_value=httpx.Response(200, json=_sound_body("sd6"))
    )
    respx.get("https://r2.example.com/sound.wav").mock(
        return_value=httpx.Response(200, content=b"MIXED")
    )
    run(["video-to-sound", "--video-url", "http://x/y.mp4",
         "--output", str(tmp_path / "s.wav"), "--preserve-speech"])
    body = route.calls.last.request.content.decode()
    assert "preserve_speech=true" in body


@respx.mock
def test_video_to_sound_variants_writes_indexed_files_and_stems(tmp_path):
    respx.post(f"{BASE}/v1/video-to-sound").mock(
        return_value=httpx.Response(200, json={"task_id": "sv1", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/sv1").mock(
        return_value=httpx.Response(200, json={
            "task_id": "sv1", "type": "video_to_sound", "status": "succeeded",
            "variants_num": 2,
            "output_url": "https://r2.example.com/sv1.0.wav",
            "output_type": "audio", "output_bytes": 5,
            "music": {"url": "https://r2.example.com/sv1.0.music.m4a"},
            "sfx": {"url": "https://r2.example.com/sv1.0.sfx.wav"},
            "outputs": [
                {
                    "variant_index": 0,
                    "output_url": "https://r2.example.com/sv1.0.wav",
                    "output_type": "audio", "output_bytes": 5,
                    "music": {"url": "https://r2.example.com/sv1.0.music.m4a"},
                    "sfx": {"url": "https://r2.example.com/sv1.0.sfx.wav"},
                },
                {
                    "variant_index": 1,
                    "output_url": "https://r2.example.com/sv1.1.wav",
                    "output_type": "audio", "output_bytes": 6,
                    "music": {"url": "https://r2.example.com/sv1.1.music.m4a"},
                    "sfx": {"url": "https://r2.example.com/sv1.1.sfx.wav"},
                },
            ],
        })
    )
    for url, content in [
        ("https://r2.example.com/sv1.0.wav", b"O0"),
        ("https://r2.example.com/sv1.1.wav", b"O1"),
        ("https://r2.example.com/sv1.0.music.m4a", b"M0"),
        ("https://r2.example.com/sv1.1.music.m4a", b"M1"),
    ]:
        respx.get(url).mock(return_value=httpx.Response(200, content=content))
    out = tmp_path / "s.wav"
    run(["video-to-sound", "--video-url", "http://x/y.mp4", "--variants", "2",
         "--output", str(out), "--stem", "music"])
    assert (tmp_path / "s.0.wav").read_bytes() == b"O0"
    assert (tmp_path / "s.1.wav").read_bytes() == b"O1"
    assert (tmp_path / "s.0.music.m4a").read_bytes() == b"M0"
    assert (tmp_path / "s.1.music.m4a").read_bytes() == b"M1"
    assert not out.exists()


@respx.mock
def test_video_to_video_sound_defaults_to_mp4(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    route = respx.post(f"{BASE}/v1/video-to-video-sound").mock(
        return_value=httpx.Response(200, json={"task_id": "sd7", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/sd7").mock(
        return_value=httpx.Response(200, json=_sound_body(
            "sd7", type="video_to_video_sound", output_type="video",
            output_url="https://r2.example.com/sound.mp4",
        ))
    )
    respx.get("https://r2.example.com/sound.mp4").mock(
        return_value=httpx.Response(200, content=b"MP4DATA")
    )
    run(["video-to-video-sound", "--video-url", "http://x/y.mp4"])
    assert route.called
    assert (tmp_path / "output.mp4").read_bytes() == b"MP4DATA"


def test_video_to_sound_requires_a_video_source():
    with pytest.raises(SystemExit) as exc:
        run(["video-to-sound"])
    assert exc.value.code == 1


def test_video_to_video_sound_requires_a_video_source():
    with pytest.raises(SystemExit) as exc:
        run(["video-to-video-sound"])
    assert exc.value.code == 1


def test_cli_identifies_itself_not_the_sdk():
    """CLI traffic must be separable from direct SDK use in analytics."""
    import sonilo_cli
    from sonilo_cli.__main__ import build_client

    client = build_client("sk-test")
    try:
        assert client._http.headers["x-sonilo-client"] == "cli-python"
        assert client._http.headers["x-sonilo-client-version"] == sonilo_cli.__version__
    finally:
        client.close()


DUBBING_BODY = {
    "task_id": "db1",
    "type": "dubbing",
    "status": "succeeded",
    "outputs": {"es": "https://r2/es.mp4", "fr": "https://r2/fr.mp4"},
}


@respx.mock
def test_dubbing_writes_one_file_per_language(tmp_path):
    respx.post(f"{BASE}/v1/dubbing").mock(
        return_value=httpx.Response(202, json={"task_id": "db1", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/db1").mock(
        return_value=httpx.Response(200, json=DUBBING_BODY)
    )
    respx.get("https://r2/es.mp4").mock(
        return_value=httpx.Response(200, content=b"es-bytes")
    )
    respx.get("https://r2/fr.mp4").mock(
        return_value=httpx.Response(200, content=b"fr-bytes")
    )
    out = tmp_path / "clip.mp4"
    run([
        "dubbing",
        "--video-url", "https://x/v.mp4",
        "--languages", "es,fr",
        "--output", str(out),
    ])
    assert (tmp_path / "clip.es.mp4").read_bytes() == b"es-bytes"
    assert (tmp_path / "clip.fr.mp4").read_bytes() == b"fr-bytes"


@respx.mock
def test_dubbing_sends_languages_as_a_json_array(tmp_path):
    route = respx.post(f"{BASE}/v1/dubbing").mock(
        return_value=httpx.Response(202, json={"task_id": "db1", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/db1").mock(
        return_value=httpx.Response(200, json={
            "task_id": "db1", "status": "succeeded",
            "outputs": {"es": "https://r2/es.mp4"},
        })
    )
    respx.get("https://r2/es.mp4").mock(
        return_value=httpx.Response(200, content=b"es-bytes")
    )
    run([
        "dubbing",
        "--video-url", "https://x/v.mp4",
        "--languages", " es , fr ",
        "--output", str(tmp_path / "clip.mp4"),
    ])
    # With no file part the request body is form-urlencoded, so the JSON
    # array arrives percent-encoded (spaces as `+`, quotes as `%22`, etc.).
    # Decode before checking for the literal JSON array string.
    body = unquote_plus(route.calls.last.request.content.decode())
    assert '["es", "fr"]' in body


def test_dubbing_requires_a_video_source():
    with pytest.raises(SystemExit) as exc:
        main(["--api-key", "sk-test", "dubbing"])
    assert exc.value.code == 1


@respx.mock
def test_dubbing_non_https_url_exits_1(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--api-key", "sk-test", "dubbing", "--video-url", "http://x/v.mp4"])
    assert exc.value.code == 1
    assert "https" in capsys.readouterr().err


@respx.mock
def test_dubbing_without_languages_omits_the_field(tmp_path):
    route = respx.post(f"{BASE}/v1/dubbing").mock(
        return_value=httpx.Response(202, json={"task_id": "db1", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/db1").mock(
        return_value=httpx.Response(200, json={
            "task_id": "db1", "status": "succeeded",
            "outputs": {"es": "https://r2/es.mp4"},
        })
    )
    respx.get("https://r2/es.mp4").mock(
        return_value=httpx.Response(200, content=b"es-bytes")
    )
    run([
        "dubbing",
        "--video-url", "https://x/v.mp4",
        "--output", str(tmp_path / "clip.mp4"),
    ])
    # Omitting --languages must not send a `languages` field at all — the
    # server default (["zh_cn", "es", "fr"]) only applies when the field is
    # absent. Sending `languages=[]` or the string "None" would silently
    # override that default with something else.
    assert b"languages" not in route.calls.last.request.content


# --- --segments -----------------------------------------------------------
#
# The two shapes are not interchangeable: music segments are
# {start, prompt, label?} and SFX segments are {start, end, prompt}. Both are
# sent as a JSON string inside the form-encoded body (see
# sonilo._requests.build_v2m_parts), so assertions decode the body first.

MUSIC_SEGMENTS = [{"start": 0, "label": "intro", "prompt": "airy pads"}]
SFX_SEGMENTS = [{"start": 0, "end": 5, "prompt": "footsteps on gravel"}]


def _sent_segments(route):
    """The `segments` value as it left the CLI, decoded back to Python."""
    body = unquote_plus(route.calls.last.request.content.decode())
    for field in body.split("&"):
        name, _, value = field.partition("=")
        if name == "segments":
            return json.loads(value)
    return None


@respx.mock
def test_segments_inline_json_reaches_the_request_body(tmp_path):
    route = respx.post(f"{BASE}/v1/text-to-music").mock(
        return_value=httpx.Response(200, text=_music_stream_body())
    )
    run(["text-to-music", "--prompt", "lofi", "--duration", "30",
         "--segments", json.dumps(MUSIC_SEGMENTS),
         "--output", str(tmp_path / "song.m4a")])
    assert _sent_segments(route) == MUSIC_SEGMENTS


@respx.mock
def test_segments_from_a_file(tmp_path):
    route = respx.post(f"{BASE}/v1/text-to-music").mock(
        return_value=httpx.Response(200, text=_music_stream_body())
    )
    src = tmp_path / "segments.json"
    src.write_text(json.dumps(MUSIC_SEGMENTS))
    run(["text-to-music", "--prompt", "lofi", "--duration", "30",
         "--segments", f"@{src}", "--output", str(tmp_path / "song.m4a")])
    assert _sent_segments(route) == MUSIC_SEGMENTS


@respx.mock
def test_segments_from_stdin(tmp_path, monkeypatch):
    route = respx.post(f"{BASE}/v1/text-to-music").mock(
        return_value=httpx.Response(200, text=_music_stream_body())
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(MUSIC_SEGMENTS)))
    run(["text-to-music", "--prompt", "lofi", "--duration", "30",
         "--segments", "@-", "--output", str(tmp_path / "song.m4a")])
    assert _sent_segments(route) == MUSIC_SEGMENTS


@respx.mock
def test_sfx_segments_reach_the_request_body(tmp_path):
    route = respx.post(f"{BASE}/v1/video-to-sound").mock(
        return_value=httpx.Response(200, json={"task_id": "sg1", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/sg1").mock(
        return_value=httpx.Response(200, json=_sound_body("sg1"))
    )
    respx.get("https://r2.example.com/sound.wav").mock(
        return_value=httpx.Response(200, content=b"MIXED")
    )
    run(["video-to-sound", "--video-url", "http://x/y.mp4",
         "--segments", json.dumps(SFX_SEGMENTS),
         "--output", str(tmp_path / "s.wav")])
    assert _sent_segments(route) == SFX_SEGMENTS


@respx.mock
def test_omitting_segments_sends_no_segments_field(tmp_path):
    route = respx.post(f"{BASE}/v1/text-to-music").mock(
        return_value=httpx.Response(200, text=_music_stream_body())
    )
    run(["text-to-music", "--prompt", "lofi", "--duration", "30",
         "--output", str(tmp_path / "song.m4a")])
    # Not `segments=[]` and not the string "None" — the field must be absent,
    # exactly as --languages is for dubbing.
    assert b"segments" not in route.calls.last.request.content


def test_segments_unknown_keys_pass_through(tmp_path):
    """A field the API adds later must not need a CLI release to be usable."""
    from sonilo_cli.__main__ import MUSIC_SHAPE, parse_segments

    value = [{"start": 0, "prompt": "pads", "intensity": 0.4}]
    assert parse_segments(json.dumps(value), MUSIC_SHAPE, "text-to-music") == value


def test_segments_malformed_json_names_the_source(capsys):
    with pytest.raises(SystemExit) as exc:
        run(["video-to-music", "--video-url", "http://x/y.mp4",
             "--segments", "[{start: 0}]"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("sonilo:")
    assert "--segments" in err  # the offending source
    assert "Expecting" in err  # the parser's own complaint
    assert "Traceback" not in err


def test_segments_malformed_json_from_a_file_names_the_file(tmp_path, capsys):
    src = tmp_path / "segments.json"
    src.write_text("{oops")
    with pytest.raises(SystemExit) as exc:
        run(["video-to-music", "--video-url", "http://x/y.mp4", "--segments", f"@{src}"])
    assert exc.value.code == 1
    assert str(src) in capsys.readouterr().err


def test_segments_malformed_json_from_stdin_names_stdin(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("{oops"))
    with pytest.raises(SystemExit) as exc:
        run(["video-to-music", "--video-url", "http://x/y.mp4", "--segments", "@-"])
    assert exc.value.code == 1
    # "stdin", not "standard input" — the Node CLI says stdin.
    assert "could not parse segments from stdin:" in capsys.readouterr().err


def test_segments_unreadable_file_exits_1(tmp_path, capsys):
    missing = tmp_path / "nope.json"
    with pytest.raises(SystemExit) as exc:
        run(["video-to-music", "--video-url", "http://x/y.mp4", "--segments", f"@{missing}"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert str(missing) in err
    assert "Traceback" not in err


def test_segments_must_be_a_list(capsys):
    with pytest.raises(SystemExit) as exc:
        run(["video-to-music", "--video-url", "http://x/y.mp4",
             "--segments", '{"start": 0, "prompt": "pads"}'])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "JSON array" in err
    assert "{start, prompt, label?}" in err


def test_segments_must_not_be_empty(capsys):
    with pytest.raises(SystemExit) as exc:
        run(["video-to-music", "--video-url", "http://x/y.mp4", "--segments", "[]"])
    assert exc.value.code == 1
    assert "empty array" in capsys.readouterr().err


def test_segments_elements_must_be_objects(capsys):
    with pytest.raises(SystemExit) as exc:
        run(["video-to-music", "--video-url", "http://x/y.mp4", "--segments", '["intro"]'])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "video-to-music segments take {start, prompt, label?}" in err
    assert "element 0 is not an object" in err


def test_segments_element_errors_name_the_offending_index(capsys):
    """Indices are 0-based, and point at the bad element rather than always
    reporting the first — matching the Node CLI, so the two agree."""
    with pytest.raises(SystemExit) as exc:
        run(["video-to-music", "--video-url", "http://x/y.mp4",
             "--segments", '[{"start": 0, "prompt": "a"}, {"start": 5, "prompt": "b"}, "oops"]'])
    assert exc.value.code == 1
    assert "element 2 is not an object" in capsys.readouterr().err


def test_music_command_rejects_sfx_shaped_segments(capsys):
    """The predictable mistake, in the direction that is hardest to spot: the
    music shape's required fields are all present, so only the foreign `end`
    key gives it away."""
    with pytest.raises(SystemExit) as exc:
        run(["video-to-music", "--video-url", "http://x/y.mp4",
             "--segments", json.dumps(SFX_SEGMENTS)])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    # Naming both the expected shape and the keys actually given is what makes
    # this self-correcting without a docs lookup.
    assert "video-to-music segments take {start, prompt, label?}" in err
    assert "got an object with keys start, end, prompt" in err


def test_sfx_command_rejects_music_shaped_segments(capsys):
    with pytest.raises(SystemExit) as exc:
        run(["video-to-sfx", "--video-url", "http://x/y.mp4",
             "--segments", json.dumps(MUSIC_SEGMENTS)])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "video-to-sfx segments take {start, end, prompt}" in err
    assert "got an object with keys start, label, prompt" in err


def test_segments_field_types_are_checked(capsys):
    with pytest.raises(SystemExit) as exc:
        run(["video-to-sfx", "--video-url", "http://x/y.mp4",
             "--segments", '[{"start": 0, "end": "5", "prompt": "thud"}]'])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "video-to-sfx segments take {start, end, prompt}" in err
    assert '"end" must be a number (element 0)' in err


def test_segments_field_type_errors_name_the_offending_index(capsys):
    with pytest.raises(SystemExit) as exc:
        run(["video-to-sfx", "--video-url", "http://x/y.mp4",
             "--segments", '[{"start": 0, "end": 5, "prompt": "a"},'
                           ' {"start": 5, "end": 9, "prompt": 7}]'])
    assert exc.value.code == 1
    assert '"prompt" must be a string (element 1)' in capsys.readouterr().err


def test_segments_semantic_rules_are_left_to_the_server():
    """Spacing, the label enum, the first segment's start and item caps are
    server-side rules; duplicating them here would drift. Shape-valid input
    must pass client-side however implausible it looks."""
    from sonilo_cli.__main__ import MUSIC_SHAPE, parse_segments

    value = [{"start": 900, "prompt": "x", "label": "not-in-the-enum"},
             {"start": 901, "prompt": "y"}]
    assert parse_segments(json.dumps(value), MUSIC_SHAPE, "text-to-music") == value


@pytest.mark.parametrize(
    "command",
    ["text-to-music", "video-to-music", "video-to-sfx", "video-to-video-sfx",
     "video-to-sound", "video-to-video-sound"],
)
def test_segments_help_shows_all_three_value_forms(command, capsys):
    with pytest.raises(SystemExit):
        main([command, "--help"])
    help_text = capsys.readouterr().out
    assert "--segments" in help_text
    assert "@FILE" in help_text
    assert "@-" in help_text


@pytest.mark.parametrize("command", ["text-to-sfx"])
def test_commands_without_segments_reject_the_flag(command, capsys):
    """text-to-sfx takes no segments in the SDK, so the CLI must not offer it.
    The other segment-less endpoint, video-to-video-music, is covered by
    test_video_to_video_music_rejects_segments (it takes no --duration)."""
    with pytest.raises(SystemExit) as exc:
        run([command, "--prompt", "x", "--duration", "3", "--segments", "[]"])
    assert exc.value.code == 1
    assert "unrecognized arguments" in capsys.readouterr().err


# --- video-to-video-music / video-to-video-sfx ---------------------------
#
# Both return the source picture with the generated audio muxed in, so the
# task body carries a single `video` object rather than `audio`/`output_url`
# (shape confirmed against tests/test_video_to_video.py in the SDK repo).


def _video_body(task_id, task_type):
    return {
        "task_id": task_id,
        "type": task_type,
        "status": "succeeded",
        "video": {"url": f"https://r2.example.com/{task_id}.mp4",
                  "content_type": "video/mp4", "file_size": 7},
        "duration_seconds": 4.0,
    }


def _mock_video_task(endpoint, task_id, task_type, content=b"MP4DATA"):
    """Wire up submit + poll + download for one video-returning endpoint."""
    route = respx.post(f"{BASE}/v1/{endpoint}").mock(
        return_value=httpx.Response(202, json={"task_id": task_id, "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/{task_id}").mock(
        return_value=httpx.Response(200, json=_video_body(task_id, task_type))
    )
    respx.get(f"https://r2.example.com/{task_id}.mp4").mock(
        return_value=httpx.Response(200, content=content)
    )
    return route


@respx.mock
def test_video_to_video_music_saves_the_scored_video(tmp_path):
    route = _mock_video_task("video-to-video-music", "vm1", "video_to_video_music")
    out = tmp_path / "scored.mp4"
    run(["video-to-video-music", "--video-url", "http://x/y.mp4",
         "--prompt", "tense synths", "--output", str(out)])
    assert route.called
    assert out.read_bytes() == b"MP4DATA"
    body = unquote_plus(route.calls.last.request.content.decode())
    assert "video_url=http://x/y.mp4" in body
    assert "prompt=tense synths" in body


@respx.mock
def test_video_to_video_music_defaults_to_mp4(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _mock_video_task("video-to-video-music", "vm2", "video_to_video_music")
    run(["video-to-video-music", "--video-url", "http://x/y.mp4"])
    assert (tmp_path / "output.mp4").read_bytes() == b"MP4DATA"


@respx.mock
def test_video_to_video_music_flags_reach_the_request_body(tmp_path):
    route = _mock_video_task("video-to-video-music", "vm3", "video_to_video_music")
    run(["video-to-video-music", "--video-url", "http://x/y.mp4",
         "--preserve-speech", "--isolate-vocals", "--output", str(tmp_path / "s.mp4")])
    body = route.calls.last.request.content.decode()
    assert "preserve_speech=true" in body
    assert "isolate_vocals=true" in body


@respx.mock
def test_video_to_video_music_unset_flags_are_omitted(tmp_path):
    route = _mock_video_task("video-to-video-music", "vm4", "video_to_video_music")
    run(["video-to-video-music", "--video-url", "http://x/y.mp4",
         "--output", str(tmp_path / "s.mp4")])
    # Unset switches must forward None, not False, so the server default
    # stands — same rule as --no-ducking on the sound commands.
    body = route.calls.last.request.content.decode()
    assert "preserve_speech=" not in body
    assert "isolate_vocals=" not in body
    assert "prompt=" not in body


def test_video_to_video_music_requires_a_video_source():
    with pytest.raises(SystemExit) as exc:
        run(["video-to-video-music", "--prompt", "x"])
    assert exc.value.code == 1


def test_video_to_video_music_rejects_both_sources():
    with pytest.raises(SystemExit) as exc:
        run(["video-to-video-music", "--video", "a.mp4", "--video-url", "http://x/y.mp4"])
    assert exc.value.code == 1


@respx.mock
def test_video_to_video_music_variants_writes_indexed_files(tmp_path):
    route = respx.post(f"{BASE}/v1/video-to-video-music").mock(
        return_value=httpx.Response(202, json={"task_id": "vm5", "status": "processing"})
    )
    respx.get(f"{BASE}/v1/tasks/vm5").mock(
        return_value=httpx.Response(200, json={
            "task_id": "vm5", "type": "video_to_video_music", "status": "succeeded",
            "variants_num": 2,
            "videos": [
                {"url": "https://r2.example.com/vm5.0.mp4"},
                {"url": "https://r2.example.com/vm5.1.mp4"},
            ],
            "video": {"url": "https://r2.example.com/vm5.0.mp4"},
        })
    )
    respx.get("https://r2.example.com/vm5.0.mp4").mock(
        return_value=httpx.Response(200, content=b"V0")
    )
    respx.get("https://r2.example.com/vm5.1.mp4").mock(
        return_value=httpx.Response(200, content=b"V1")
    )
    out = tmp_path / "scored.mp4"
    run(["video-to-video-music", "--video-url", "http://x/y.mp4",
         "--variants", "2", "--output", str(out)])
    assert (tmp_path / "scored.0.mp4").read_bytes() == b"V0"
    assert (tmp_path / "scored.1.mp4").read_bytes() == b"V1"
    assert not out.exists()
    body = route.calls.last.request.content.decode()
    assert "variants_num=2" in body


def test_video_to_video_music_rejects_segments(capsys):
    """The endpoint scores the whole clip in one pass — the SDK resource takes
    no `segments`, so the CLI must not offer the flag."""
    with pytest.raises(SystemExit) as exc:
        run(["video-to-video-music", "--video-url", "http://x/y.mp4", "--segments", "[]"])
    assert exc.value.code == 1
    assert "unrecognized arguments" in capsys.readouterr().err


@respx.mock
def test_video_to_video_sfx_saves_the_scored_video(tmp_path):
    route = _mock_video_task("video-to-video-sfx", "vf1", "video_to_video_sfx")
    out = tmp_path / "scored.mp4"
    run(["video-to-video-sfx", "--video-url", "http://x/y.mp4",
         "--prompt", "footsteps", "--output", str(out)])
    assert route.called
    assert out.read_bytes() == b"MP4DATA"
    body = unquote_plus(route.calls.last.request.content.decode())
    assert "video_url=http://x/y.mp4" in body
    assert "prompt=footsteps" in body


@respx.mock
def test_video_to_video_sfx_defaults_to_mp4(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _mock_video_task("video-to-video-sfx", "vf2", "video_to_video_sfx")
    run(["video-to-video-sfx", "--video-url", "http://x/y.mp4"])
    assert (tmp_path / "output.mp4").read_bytes() == b"MP4DATA"


@respx.mock
def test_video_to_video_sfx_segments_reach_the_request_body(tmp_path):
    route = _mock_video_task("video-to-video-sfx", "vf3", "video_to_video_sfx")
    run(["video-to-video-sfx", "--video-url", "http://x/y.mp4",
         "--segments", json.dumps(SFX_SEGMENTS), "--output", str(tmp_path / "s.mp4")])
    assert _sent_segments(route) == SFX_SEGMENTS


@respx.mock
def test_video_to_video_sfx_omitting_segments_sends_no_field(tmp_path):
    route = _mock_video_task("video-to-video-sfx", "vf4", "video_to_video_sfx")
    run(["video-to-video-sfx", "--video-url", "http://x/y.mp4",
         "--output", str(tmp_path / "s.mp4")])
    assert b"segments" not in route.calls.last.request.content


def test_video_to_video_sfx_rejects_music_shaped_segments(capsys):
    with pytest.raises(SystemExit) as exc:
        run(["video-to-video-sfx", "--video-url", "http://x/y.mp4",
             "--segments", json.dumps(MUSIC_SEGMENTS)])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "video-to-video-sfx segments take {start, end, prompt}" in err
    assert "got an object with keys start, label, prompt" in err


def test_video_to_video_sfx_requires_a_video_source():
    with pytest.raises(SystemExit) as exc:
        run(["video-to-video-sfx", "--prompt", "x"])
    assert exc.value.code == 1


def test_video_to_video_sfx_rejects_both_sources():
    with pytest.raises(SystemExit) as exc:
        run(["video-to-video-sfx", "--video", "a.mp4", "--video-url", "http://x/y.mp4"])
    assert exc.value.code == 1


@pytest.mark.parametrize("command", ["video-to-music", "video-to-video-music"])
def test_isolate_vocals_is_documented_as_an_alias(command, capsys):
    """Both endpoints OR the two fields into one behaviour server-side
    (video_to_music.py: `isolate_vocals = bool(preserve_speech) or
    bool(isolate_vocals)`; video_to_video.py: `keep_speech = bool(...) or
    bool(...)`), so the help must not present --isolate-vocals as a separate
    feature. On video-to-video-music there is no stem at all — the result is
    a single muxed video."""
    with pytest.raises(SystemExit):
        main([command, "--help"])
    help_text = capsys.readouterr().out
    assert "Legacy alias for --preserve-speech" in help_text
    assert "vocals-only stem" not in help_text


@pytest.mark.parametrize(
    "command", ["video-to-video-music", "video-to-video-sfx"]
)
def test_video_to_video_commands_are_listed_in_top_level_help(command, capsys):
    """Both are documented publicly as `sonilo <command>`, so they have to be
    discoverable from `sonilo --help`, not just by knowing the name."""
    with pytest.raises(SystemExit):
        main(["--help"])
    assert command in capsys.readouterr().out
