import io
import json

import pytest

from sonilo._requests import (
    build_dubbing_parts,
    build_t2m_async_data,
    build_t2m_data,
    build_v2m_async_parts,
    build_v2m_parts,
    build_v2s_parts,
    build_v2v_music_parts,
    build_v2v_sfx_parts,
    normalize_video,
)
from sonilo.errors import SoniloError


def test_build_t2m_data_basic():
    data = build_t2m_data("lofi beat", 30, None)
    assert data == {"prompt": "lofi beat", "duration": "30"}


def test_build_t2m_data_with_segments():
    segments = [{"start": 0, "prompt": "intro", "label": "intro"}]
    data = build_t2m_data("p", 60, segments)
    assert json.loads(data["segments"]) == segments


def test_normalize_video_path(tmp_path):
    path = tmp_path / "movie.mp4"
    path.write_bytes(b"vid")
    filename, fileobj, opened = normalize_video(str(path))
    try:
        assert filename == "movie.mp4"
        assert opened is True
        assert fileobj.read() == b"vid"
    finally:
        fileobj.close()


def test_normalize_video_bytes():
    filename, fileobj, opened = normalize_video(b"vid")
    assert filename == "video.mp4"
    assert fileobj == b"vid"
    assert opened is False


def test_normalize_video_file_like():
    src = io.BytesIO(b"vid")
    src.name = "clip.mp4"
    filename, fileobj, opened = normalize_video(src)
    assert filename == "clip.mp4"
    assert fileobj is src
    assert opened is False


def test_normalize_video_rejects_unsupported():
    with pytest.raises(SoniloError):
        normalize_video(42)


def test_build_v2m_parts_with_url():
    data, files, opened = build_v2m_parts(None, "https://example.com/v.mp4", "upbeat", None)
    assert data == {"video_url": "https://example.com/v.mp4", "prompt": "upbeat"}
    assert files is None
    assert opened is False


def test_build_v2m_parts_with_bytes():
    data, files, opened = build_v2m_parts(b"vid", None, None, None)
    assert data == {}
    assert files["video"][0] == "video.mp4"
    assert files["video"][1] == b"vid"


def test_build_v2m_parts_rejects_both_and_neither():
    with pytest.raises(SoniloError):
        build_v2m_parts(b"vid", "https://example.com/v.mp4", None, None)
    with pytest.raises(SoniloError):
        build_v2m_parts(None, None, None, None)


def test_build_v2m_parts_with_path_propagates_opened(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"vid")
    data, files, opened = build_v2m_parts(str(path), None, None, None)
    try:
        assert opened is True
        assert files["video"][0] == "clip.mp4"
        assert files["video"][1].read() == b"vid"
        assert data == {}
    finally:
        files["video"][1].close()


def test_v2m_async_parts_new_fields_and_default_mode():
    data, _, _ = build_v2m_async_parts(
        None, "https://x/v.mp4", None, None, None, None,
        preserve_speech=True, output_format="wav", ducking=False,
    )
    assert data["mode"] == "async"
    assert data["preserve_speech"] == "true"
    assert data["output_format"] == "wav"
    assert data["ducking"] == "false"


def test_v2m_async_parts_omits_ducking_when_none():
    data, _, _ = build_v2m_async_parts(
        None, "https://x/v.mp4", None, None, None, None,
    )
    assert "ducking" not in data


def test_v2v_music_parts_forwards_alias():
    data, _, _ = build_v2v_music_parts(None, "https://x/v.mp4", "p", True, None)
    assert data == {"video_url": "https://x/v.mp4", "prompt": "p", "preserve_speech": "true"}


def test_v2v_sfx_parts_serializes_segments():
    data, _, _ = build_v2v_sfx_parts(
        None, "https://x/v.mp4", None, [{"start": 0, "end": 2, "prompt": "boom"}]
    )
    assert json.loads(data["segments"]) == [{"start": 0, "end": 2, "prompt": "boom"}]


def test_build_dubbing_parts_encodes_languages_as_a_json_array():
    data, files, close_after = build_dubbing_parts(
        None, "https://x/v.mp4", ["es", "fr"]
    )
    # Third element is a ready-made close_after (or None), not an `opened`
    # bool: subtitles can open one file per language on top of the video.
    assert files is None and close_after is None
    assert data["video_url"] == "https://x/v.mp4"
    assert json.loads(data["languages"]) == ["es", "fr"]


def test_build_dubbing_parts_omits_languages_when_unset():
    data, _, _ = build_dubbing_parts(None, "https://x/v.mp4", None)
    assert data == {"video_url": "https://x/v.mp4"}


def test_build_dubbing_parts_requires_exactly_one_input():
    with pytest.raises(SoniloError):
        build_dubbing_parts(None, None, None)
    with pytest.raises(SoniloError):
        build_dubbing_parts(b"bytes", "https://x/v.mp4", None)


def test_build_dubbing_parts_rejects_a_non_https_url():
    with pytest.raises(SoniloError):
        build_dubbing_parts(None, "http://x/v.mp4", None)


def test_build_dubbing_parts_uploads_bytes_as_the_video_part():
    data, files, close_after = build_dubbing_parts(b"bytes", None, ["ja"])
    assert "video_url" not in data
    assert json.loads(data["languages"]) == ["ja"]
    assert files is not None and files["video"][1] == b"bytes"
    # Nothing was opened here — the caller handed us the bytes.
    assert close_after is None


def test_build_dubbing_parts_passes_unknown_codes_through():
    # The backend owns the supported-language list; a client-side allowlist
    # would make this SDK reject codes added server-side later.
    data, _, _ = build_dubbing_parts(None, "https://x/v.mp4", ["xx"])
    assert json.loads(data["languages"]) == ["xx"]


# --- variants_num ----------------------------------------------------------


def test_build_t2m_async_data_forwards_variants_num():
    data = build_t2m_async_data("lofi", 30, None, None, None, variants_num=3)
    assert data["variants_num"] == "3"
    assert data["mode"] == "async"


def test_build_t2m_async_data_omits_variants_num_when_unset():
    data = build_t2m_async_data("lofi", 30, None, None, None)
    assert "variants_num" not in data


def test_v2m_async_parts_forwards_variants_num():
    data, _, _ = build_v2m_async_parts(
        None, "https://x/v.mp4", None, None, None, None, variants_num=3
    )
    assert data["variants_num"] == "3"
    assert data["mode"] == "async"


def test_v2m_async_parts_variants_num_1_does_not_force_async():
    # variants_num=1 is the no-op case: unlike variants_num > 1, it must not
    # by itself reject an explicit non-async mode.
    data, _, _ = build_v2m_async_parts(
        None, "https://x/v.mp4", None, None, "sync", None, variants_num=1
    )
    assert data["mode"] == "sync"


def test_v2m_async_parts_variants_num_above_1_requires_async():
    with pytest.raises(SoniloError):
        build_v2m_async_parts(
            None, "https://x/v.mp4", None, None, "sync", None, variants_num=2
        )


def test_v2v_music_parts_forwards_variants_num():
    data, _, _ = build_v2v_music_parts(
        None, "https://x/v.mp4", "p", None, None, variants_num=5
    )
    assert data["variants_num"] == "5"


def test_v2v_music_parts_omits_variants_num_when_unset():
    data, _, _ = build_v2v_music_parts(None, "https://x/v.mp4", "p", None, None)
    assert "variants_num" not in data


def test_build_v2s_parts_forwards_variants_num():
    data, _, _ = build_v2s_parts(
        None, "https://x/v.mp4", None, None, None, None, None, variants_num=4
    )
    assert data["variants_num"] == "4"


def test_build_v2s_parts_omits_variants_num_when_unset():
    data, _, _ = build_v2s_parts(None, "https://x/v.mp4", None, None, None, None, None)
    assert "variants_num" not in data


# --- dubbing subtitles -----------------------------------------------------
#
# The builder returns a ready-made `close_after` here (see build_ducking_parts
# for the same shape): one request can open the video plus one script per
# target language, and a bool cannot say how many handles that is.


def test_build_dubbing_parts_sends_an_https_subtitle_as_a_text_field():
    data, files, close_after = build_dubbing_parts(
        None, "https://x/v.mp4", ["es"], subtitles={"es": "https://x/es.srt"}
    )
    assert data["subtitles[es]"] == "https://x/es.srt"
    assert files is None and close_after is None


def test_build_dubbing_parts_uploads_a_local_subtitle_with_its_basename(tmp_path):
    script = tmp_path / "spanish.srt"
    script.write_text("1\n00:00:00,000 --> 00:00:01,000\nhola\n")
    data, files, close_after = build_dubbing_parts(
        None, "https://x/v.mp4", ["es"], subtitles={"es": str(script)}
    )
    assert "subtitles[es]" not in data
    assert files is not None
    filename, fileobj, _ = files["subtitles[es]"]
    assert filename == "spanish.srt"
    assert not fileobj.closed
    close_after.close()
    assert fileobj.closed


def test_build_dubbing_parts_closes_the_video_and_every_script(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"mp4")
    es = tmp_path / "es.vtt"
    es.write_text("WEBVTT\n")
    fr = tmp_path / "fr.srt"
    fr.write_text("1\n")
    _, files, close_after = build_dubbing_parts(
        str(video), None, ["es", "fr"], subtitles={"es": es, "fr": str(fr)}
    )
    handles = [files[key][1] for key in ("video", "subtitles[es]", "subtitles[fr]")]
    assert all(not handle.closed for handle in handles)
    close_after.close()
    assert all(handle.closed for handle in handles)


def test_build_dubbing_parts_closes_handles_when_a_later_open_fails(tmp_path, monkeypatch):
    """A leaked handle is invisible until the process runs out of descriptors,
    so the error path is tested the only way it can be: by watching every open."""
    from pathlib import Path

    good = tmp_path / "es.srt"
    good.write_text("1\n")
    opened = []
    real_open = Path.open

    def spy(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(Path, "open", spy)
    with pytest.raises(OSError):
        build_dubbing_parts(
            None,
            "https://x/v.mp4",
            ["es", "fr"],
            subtitles={"es": str(good), "fr": str(tmp_path / "missing.srt")},
        )
    assert opened and all(handle.closed for handle in opened)


def test_build_dubbing_parts_rejects_a_subtitle_that_is_not_srt_or_vtt(tmp_path):
    script = tmp_path / "es.txt"
    script.write_text("hola")
    with pytest.raises(SoniloError) as exc:
        build_dubbing_parts(None, "https://x/v.mp4", ["es"], subtitles={"es": str(script)})
    assert "es.txt" in str(exc.value)


def test_build_dubbing_parts_rejects_export_srt_without_subtitles():
    with pytest.raises(SoniloError):
        build_dubbing_parts(None, "https://x/v.mp4", ["es"], export_srt=True)


def test_build_dubbing_parts_sends_export_srt_with_subtitles():
    data, _, _ = build_dubbing_parts(
        None, "https://x/v.mp4", ["es"],
        subtitles={"es": "https://x/es.srt"}, export_srt=True,
    )
    assert data["export_srt"] == "true"


def test_build_dubbing_parts_omits_lipsync_when_unset():
    # Absent must keep meaning true — that is what every dubbing task did
    # before the field existed.
    data, _, _ = build_dubbing_parts(None, "https://x/v.mp4", None)
    assert "lipsync" not in data


def test_build_dubbing_parts_sends_lipsync_when_set():
    data, _, _ = build_dubbing_parts(None, "https://x/v.mp4", None, lipsync=False)
    assert data["lipsync"] == "false"
