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
