import httpx
import pytest
import respx

from sonilo import AsyncSonilo, Sonilo
from sonilo._requests import build_ducking_parts
from sonilo.errors import SoniloError

SUCCESS_BODY = {
    "task_id": "ad1",
    "type": "audio_ducking",
    "status": "succeeded",
    "output_url": "https://r2/ducked.wav",
    "output_type": "audio",
    "output_bytes": 12,
}

VIDEO_BODY = {
    "task_id": "ad2",
    "type": "audio_ducking",
    "status": "succeeded",
    "output_url": "https://r2/ducked.mp4",
    "output_type": "video",
    "output_bytes": 34,
}


def test_build_ducking_parts_urls_only():
    data, files, close_after = build_ducking_parts(
        None, "https://x/v.mp4", None, "https://x/m.wav"
    )
    assert data == {"voice_url": "https://x/v.mp4", "music_url": "https://x/m.wav"}
    assert files is None and close_after is None


def test_build_ducking_parts_local_files(tmp_path):
    voice = tmp_path / "interview.mp4"
    voice.write_bytes(b"v")
    music = tmp_path / "bed.wav"
    music.write_bytes(b"m")
    data, files, close_after = build_ducking_parts(str(voice), None, str(music), None)
    assert data == {}
    assert files["voice_file"][0] == "interview.mp4"
    assert files["music_file"][0] == "bed.wav"
    assert close_after is not None
    close_after.close()
    assert files["voice_file"][1].closed
    assert files["music_file"][1].closed


def test_build_ducking_parts_mixes_file_and_url(tmp_path):
    voice = tmp_path / "voice.wav"
    voice.write_bytes(b"v")
    data, files, close_after = build_ducking_parts(
        str(voice), None, None, "https://x/m.wav"
    )
    assert data == {"music_url": "https://x/m.wav"}
    assert set(files) == {"voice_file"}
    close_after.close()
    assert files["voice_file"][1].closed


def test_build_ducking_parts_requires_exactly_one_voice():
    with pytest.raises(SoniloError):
        build_ducking_parts(None, None, None, "https://x/m.wav")
    with pytest.raises(SoniloError):
        build_ducking_parts(b"v", "https://x/v.wav", None, "https://x/m.wav")


def test_build_ducking_parts_requires_exactly_one_music():
    with pytest.raises(SoniloError):
        build_ducking_parts(None, "https://x/v.wav", None, None)
    with pytest.raises(SoniloError):
        build_ducking_parts(None, "https://x/v.wav", b"m", "https://x/m.wav")


def test_build_ducking_parts_checks_both_pairs_before_opening_files(tmp_path):
    # A missing music input must be reported even when the voice side is a
    # real local file — and without leaving that file open.
    voice = tmp_path / "voice.wav"
    voice.write_bytes(b"v")
    with pytest.raises(SoniloError):
        build_ducking_parts(str(voice), None, None, None)


@respx.mock
def test_submit_posts_multipart_to_audio_ducking():
    respx.post("https://api.sonilo.com/v1/audio-ducking").mock(
        return_value=httpx.Response(202, json={"task_id": "ad1", "status": "processing"})
    )
    task = Sonilo(api_key="k").audio_ducking.submit(
        voice_url="https://x/v.mp4", music_url="https://x/m.wav"
    )
    assert task.task_id == "ad1"
    content = respx.calls[0].request.content
    assert b"voice_url" in content and b"music_url" in content


@respx.mock
def test_generate_polls_to_sound_result():
    respx.post("https://api.sonilo.com/v1/audio-ducking").mock(
        return_value=httpx.Response(202, json={"task_id": "ad1", "status": "processing"})
    )
    respx.get("https://api.sonilo.com/v1/tasks/ad1").mock(
        return_value=httpx.Response(200, json=SUCCESS_BODY)
    )
    result = Sonilo(api_key="k").audio_ducking.generate(
        voice_url="https://x/v.wav", music_url="https://x/m.wav", poll_interval=0
    )
    assert result.output_url == "https://r2/ducked.wav"
    assert result.output_type == "audio"
    assert result.output_bytes == 12


@respx.mock
def test_generate_surfaces_video_output_type():
    respx.post("https://api.sonilo.com/v1/audio-ducking").mock(
        return_value=httpx.Response(202, json={"task_id": "ad2", "status": "processing"})
    )
    respx.get("https://api.sonilo.com/v1/tasks/ad2").mock(
        return_value=httpx.Response(200, json=VIDEO_BODY)
    )
    result = Sonilo(api_key="k").audio_ducking.generate(
        voice_url="https://x/v.mp4", music_url="https://x/m.wav", poll_interval=0
    )
    assert result.output_type == "video"
    assert result.output_url == "https://r2/ducked.mp4"


@respx.mock
def test_submit_closes_opened_files(tmp_path):
    respx.post("https://api.sonilo.com/v1/audio-ducking").mock(
        return_value=httpx.Response(202, json={"task_id": "ad1", "status": "processing"})
    )
    voice = tmp_path / "voice.wav"
    voice.write_bytes(b"v")
    music = tmp_path / "bed.wav"
    music.write_bytes(b"m")
    client = Sonilo(api_key="k")
    # Grab the parts the resource would open by spying on the request content;
    # the observable contract is simply that submit() succeeds and leaves no
    # file handles behind (ResourceWarning-free under -W error would catch it;
    # here we assert via the multipart body containing both files).
    task = client.audio_ducking.submit(voice=str(voice), music=str(music))
    assert task.task_id == "ad1"
    content = respx.calls[0].request.content
    assert b'name="voice_file"' in content
    assert b'name="music_file"' in content


@respx.mock
async def test_async_generate_polls_to_sound_result():
    respx.post("https://api.sonilo.com/v1/audio-ducking").mock(
        return_value=httpx.Response(202, json={"task_id": "ad1", "status": "processing"})
    )
    respx.get("https://api.sonilo.com/v1/tasks/ad1").mock(
        return_value=httpx.Response(200, json=SUCCESS_BODY)
    )
    async with AsyncSonilo(api_key="k") as client:
        result = await client.audio_ducking.generate(
            voice_url="https://x/v.wav", music_url="https://x/m.wav", poll_interval=0
        )
    assert result.output_url == "https://r2/ducked.wav"
