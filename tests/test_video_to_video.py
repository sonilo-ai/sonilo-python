import httpx
import pytest
import respx

from sonilo import Sonilo


@respx.mock
def test_v2v_music_submit_and_poll():
    respx.post("https://api.sonilo.com/v1/video-to-video-music").mock(
        return_value=httpx.Response(202, json={"task_id": "v1", "status": "processing"})
    )
    respx.get("https://api.sonilo.com/v1/tasks/v1").mock(
        return_value=httpx.Response(
            200,
            json={
                "task_id": "v1",
                "type": "video_to_video_music",
                "status": "succeeded",
                "video": {"url": "https://r2/o.mp4", "content_type": "video/mp4", "file_size": 9},
                "duration_seconds": 4.0,
            },
        )
    )
    client = Sonilo(api_key="k")
    result = client.video_to_video_music.generate(
        video_url="https://x/v.mp4", preserve_speech=True, poll_interval=0
    )
    assert result.video.url == "https://r2/o.mp4"
    assert result.duration_seconds == 4.0
    request = respx.calls[0].request
    assert b"preserve_speech" in request.content


@respx.mock
def test_v2v_sfx_submit_serializes_segments():
    respx.post("https://api.sonilo.com/v1/video-to-video-sfx").mock(
        return_value=httpx.Response(202, json={"task_id": "s1", "status": "processing"})
    )
    client = Sonilo(api_key="k")
    task = client.video_to_video_sfx.submit(
        video_url="https://x/v.mp4", segments=[{"start": 0, "end": 2, "prompt": "boom"}]
    )
    assert task.task_id == "s1"
    assert b"segments" in respx.calls[0].request.content
