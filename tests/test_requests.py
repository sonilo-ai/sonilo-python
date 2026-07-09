import io
import json

import pytest

from sonilo._requests import build_t2m_data, build_v2m_parts, normalize_video
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
