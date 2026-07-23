import json

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
    # ducking is default-ON server-side: an unset --no-ducking must forward
    # `None`, not `False`, so the field must be entirely absent from the
    # form-encoded body (per build_v2s_parts).
    body = route.calls.last.request.content.decode()
    assert "ducking=" not in body


@respx.mock
def test_video_to_sound_no_ducking_sets_false(tmp_path):
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
         "--output", str(tmp_path / "s.wav"), "--no-ducking"])
    body = route.calls.last.request.content.decode()
    assert "ducking=false" in body


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
