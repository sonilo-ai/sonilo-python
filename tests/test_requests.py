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
    data, files, opened = build_dubbing_parts(
        None, "https://x/v.mp4", ["es", "fr"]
    )
    assert files is None and opened is False
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
    data, files, opened = build_dubbing_parts(b"bytes", None, ["ja"])
    assert "video_url" not in data
    assert json.loads(data["languages"]) == ["ja"]
    assert files is not None and files["video"][1] == b"bytes"
    assert opened is False


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
