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
from sonilo.types import (
    DOWNLOAD_TIMEOUT,
    MusicAudioMedia,
    MusicResult,
    MusicTitle,
    SoundOutput,
    SoundResult,
    VideoResult,
)

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


# --- variants_num -----------------------------------------------------


def test_music_audio_media_carries_optional_title():
    entry = MusicAudioMedia(
        stream_index=1,
        url="https://r2/a1.m4a",
        title=MusicTitle(title="Variant 1", summary="s", display_tags=["x"]),
    )
    assert entry.title.title == "Variant 1"
    # Default stays None, matching mux/ducked entries which never carry one.
    assert MusicAudioMedia(stream_index=0, url="https://r2/a0.m4a").title is None


def test_music_result_variants_num_defaults_to_none():
    result = MusicResult(task_id="m1", status="succeeded")
    assert result.variants_num is None


@respx.mock
def test_video_result_videos_index_selects_a_variant(tmp_path):
    respx.get("https://r2.example.com/v1.mp4").mock(
        return_value=httpx.Response(200, content=b"variant1")
    )
    result = make_video_result(
        videos=[
            SfxMedia(url="https://r2.example.com/video.mp4"),
            SfxMedia(url="https://r2.example.com/v1.mp4"),
        ],
        variants_num=2,
    )
    out = result.save(tmp_path / "v1.mp4", index=1)
    assert out.read_bytes() == b"variant1"


def test_video_result_default_save_ignores_videos_list(tmp_path):
    # Omitting `index` must keep using `video`, unchanged from before
    # `videos`/`variants_num` existed, even when `videos` is populated.
    result = make_video_result(videos=[SfxMedia(url="https://r2.example.com/other.mp4")])
    assert result._media().url == "https://r2.example.com/video.mp4"


def test_video_result_videos_index_out_of_range_raises():
    result = make_video_result(videos=[SfxMedia(url="https://r2.example.com/v0.mp4")])
    with pytest.raises(SoniloError):
        result.save("unused.mp4", index=5)


def test_video_result_videos_index_without_videos_raises():
    result = VideoResult(task_id="v2", status="succeeded")
    with pytest.raises(SoniloError):
        result.save("unused.mp4", index=0)


SOUND_STEM_MEDIA = SfxMedia(url="https://r2.example.com/s0.music.m4a")


def make_sound_result(**overrides) -> SoundResult:
    kwargs = {
        "task_id": "sd1",
        "status": "succeeded",
        "output_url": "https://r2.example.com/s0.wav",
        "music": SOUND_STEM_MEDIA,
    }
    kwargs.update(overrides)
    return SoundResult(**kwargs)


@respx.mock
def test_sound_result_outputs_index_selects_a_variant(tmp_path):
    respx.get("https://r2.example.com/s1.wav").mock(
        return_value=httpx.Response(200, content=b"variant1")
    )
    result = make_sound_result(
        outputs=[
            SoundOutput(variant_index=0, output_url="https://r2.example.com/s0.wav"),
            SoundOutput(variant_index=1, output_url="https://r2.example.com/s1.wav"),
        ],
        variants_num=2,
    )
    out = result.save(tmp_path / "v1.wav", index=1)
    assert out.read_bytes() == b"variant1"


@respx.mock
def test_sound_result_save_stem_index_selects_a_variant(tmp_path):
    respx.get("https://r2.example.com/s1.music.m4a").mock(
        return_value=httpx.Response(200, content=b"music1")
    )
    result = make_sound_result(
        outputs=[
            SoundOutput(
                variant_index=0, output_url="https://r2.example.com/s0.wav",
                music=SOUND_STEM_MEDIA,
            ),
            SoundOutput(
                variant_index=1, output_url="https://r2.example.com/s1.wav",
                music=SfxMedia(url="https://r2.example.com/s1.music.m4a"),
            ),
        ],
    )
    out = result.save_stem(tmp_path / "m1.m4a", which="music", index=1)
    assert out.read_bytes() == b"music1"


def test_sound_result_default_save_ignores_outputs_list(tmp_path):
    result = make_sound_result(
        outputs=[SoundOutput(variant_index=0, output_url="https://r2.example.com/other.wav")]
    )
    assert result._output() == "https://r2.example.com/s0.wav"


def test_sound_result_outputs_index_without_outputs_raises():
    result = SoundResult(task_id="sd2", status="succeeded")
    with pytest.raises(SoniloError):
        result.save("unused.wav", index=0)


def test_task_errors_carry_fields():
    failed = TaskFailedError("boom", code="GENERATION_FAILED", task_id="t1", refunded=True)
    assert isinstance(failed, SoniloError)
    assert failed.code == "GENERATION_FAILED"
    assert failed.task_id == "t1"
    assert failed.refunded is True

    timed_out = TaskTimeoutError("slow", task_id="t1")
    assert isinstance(timed_out, SoniloError)
    assert timed_out.task_id == "t1"
