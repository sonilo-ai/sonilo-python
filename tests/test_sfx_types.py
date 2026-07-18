import httpx
import pytest
import respx

from sonilo import (
    SfxMedia,
    SfxResult,
    SfxTask,
    SoniloError,
    TaskFailedError,
    TaskTimeoutError,
)
from sonilo.types import DOWNLOAD_TIMEOUT, MusicAudioMedia, MusicResult, VideoResult

AUDIO = SfxMedia(url="https://r2.example.com/audio.m4a", content_type="audio/mp4", file_size=10)


def make_result(**overrides) -> SfxResult:
    kwargs = {"task_id": "t1", "status": "succeeded", "audio": AUDIO}
    kwargs.update(overrides)
    return SfxResult(**kwargs)


def test_sfx_task_fields():
    task = SfxTask(task_id="t1", status="processing")
    assert task.task_id == "t1"
    assert task.status == "processing"


@respx.mock
def test_save_downloads_audio(tmp_path):
    respx.get("https://r2.example.com/audio.m4a").mock(
        return_value=httpx.Response(200, content=b"audiobytes")
    )
    out = make_result().save(tmp_path / "out.m4a")
    assert out.read_bytes() == b"audiobytes"
    assert "authorization" not in respx.calls.last.request.headers


@respx.mock
def test_save_which_video(tmp_path):
    respx.get("https://r2.example.com/video.mp4").mock(
        return_value=httpx.Response(200, content=b"videobytes")
    )
    result = make_result(video=SfxMedia(url="https://r2.example.com/video.mp4"))
    out = result.save(tmp_path / "out.mp4", which="video")
    assert out.read_bytes() == b"videobytes"


def test_save_missing_media_raises(tmp_path):
    result = SfxResult(task_id="t1", status="processing")
    with pytest.raises(SoniloError):
        result.save(tmp_path / "out.m4a")


def test_save_rejects_unknown_which(tmp_path):
    with pytest.raises(SoniloError):
        make_result().save(tmp_path / "x", which="cover_art")


@respx.mock
def test_save_uses_download_timeout_by_default(tmp_path, monkeypatch):
    respx.get("https://r2.example.com/audio.m4a").mock(
        return_value=httpx.Response(200, content=b"audiobytes")
    )
    captured = {}
    real_get = httpx.get

    def spy_get(url, **kwargs):
        captured.update(kwargs)
        return real_get(url, **kwargs)

    monkeypatch.setattr(httpx, "get", spy_get)
    make_result().save(tmp_path / "out.m4a")
    assert captured["timeout"] == DOWNLOAD_TIMEOUT


@respx.mock
def test_save_passes_through_custom_timeout(tmp_path, monkeypatch):
    respx.get("https://r2.example.com/audio.m4a").mock(
        return_value=httpx.Response(200, content=b"audiobytes")
    )
    captured = {}
    real_get = httpx.get

    def spy_get(url, **kwargs):
        captured.update(kwargs)
        return real_get(url, **kwargs)

    monkeypatch.setattr(httpx, "get", spy_get)
    make_result().save(tmp_path / "out.m4a", timeout=1.0)
    assert captured["timeout"] == 1.0


@respx.mock
def test_save_download_http_error_raises(tmp_path):
    respx.get("https://r2.example.com/audio.m4a").mock(
        return_value=httpx.Response(403, content=b"expired")
    )
    with pytest.raises(SoniloError):
        make_result().save(tmp_path / "out.m4a")


@respx.mock
async def test_asave_downloads_audio(tmp_path):
    respx.get("https://r2.example.com/audio.m4a").mock(
        return_value=httpx.Response(200, content=b"audiobytes")
    )
    out = await make_result().asave(tmp_path / "out.m4a")
    assert out.read_bytes() == b"audiobytes"


@respx.mock
async def test_asave_uses_download_timeout_by_default(tmp_path, monkeypatch):
    respx.get("https://r2.example.com/audio.m4a").mock(
        return_value=httpx.Response(200, content=b"audiobytes")
    )
    captured = {}
    real_init = httpx.AsyncClient.__init__

    def spy_init(self, *args, **kwargs):
        captured.update(kwargs)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", spy_init)
    await make_result().asave(tmp_path / "out.m4a")
    assert captured["timeout"] == DOWNLOAD_TIMEOUT


def make_video_result(**overrides) -> VideoResult:
    kwargs = {
        "task_id": "v1",
        "status": "succeeded",
        "video": SfxMedia(
            url="https://r2.example.com/video.mp4", content_type="video/mp4", file_size=99
        ),
    }
    kwargs.update(overrides)
    return VideoResult(**kwargs)


def test_video_result_fields():
    result = make_video_result(type="video_to_video_music", duration_seconds=5.0)
    assert result.task_id == "v1"
    assert result.status == "succeeded"
    assert result.type == "video_to_video_music"
    assert result.duration_seconds == 5.0


@respx.mock
def test_video_result_save_downloads_video(tmp_path):
    respx.get("https://r2.example.com/video.mp4").mock(
        return_value=httpx.Response(200, content=b"videobytes")
    )
    out = make_video_result().save(tmp_path / "out.mp4")
    assert out.read_bytes() == b"videobytes"
    assert "authorization" not in respx.calls.last.request.headers


@respx.mock
async def test_video_result_asave_downloads_video(tmp_path):
    respx.get("https://r2.example.com/video.mp4").mock(
        return_value=httpx.Response(200, content=b"videobytes")
    )
    out = await make_video_result().asave(tmp_path / "out.mp4")
    assert out.read_bytes() == b"videobytes"


def test_video_result_save_missing_media_raises(tmp_path):
    result = VideoResult(task_id="v1", status="processing")
    with pytest.raises(SoniloError):
        result.save(tmp_path / "out.mp4")


@respx.mock
def test_music_result_save_which_ducked(tmp_path):
    respx.get("https://r2.example.com/ducked0.m4a").mock(
        return_value=httpx.Response(200, content=b"duckedbytes")
    )
    result = MusicResult(
        task_id="m1",
        status="succeeded",
        ducked=[MusicAudioMedia(stream_index=0, url="https://r2.example.com/ducked0.m4a")],
    )
    out = result.save(tmp_path / "d.m4a", which="ducked")
    assert out.read_bytes() == b"duckedbytes"


def test_task_errors_carry_fields():
    failed = TaskFailedError("boom", code="GENERATION_FAILED", task_id="t1", refunded=True)
    assert isinstance(failed, SoniloError)
    assert failed.code == "GENERATION_FAILED"
    assert failed.task_id == "t1"
    assert failed.refunded is True

    timed_out = TaskTimeoutError("slow", task_id="t1")
    assert isinstance(timed_out, SoniloError)
    assert timed_out.task_id == "t1"
