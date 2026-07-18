from sonilo_video_kit import generate_music_for_video


class _FakeV2M:
    def __init__(self):
        self.calls = []

    def generate(self, *, video=None, prompt=None, segments=None):
        self.calls.append({"video": video, "prompt": prompt, "segments": segments})
        return "TRACK"


class _FakeClient:
    def __init__(self):
        self.video_to_music = _FakeV2M()


def test_passthrough_with_prompt():
    c = _FakeClient()
    out = generate_music_for_video("clip.mp4", prompt="epic", client=c)
    assert out == "TRACK"
    assert c.video_to_music.calls == [
        {"video": "clip.mp4", "prompt": "epic", "segments": None}
    ]


def test_passthrough_with_segments():
    c = _FakeClient()
    generate_music_for_video("clip.mp4", segments=[{"prompt": "x", "duration": 5}], client=c)
    assert c.video_to_music.calls[0]["segments"] == [{"prompt": "x", "duration": 5}]
