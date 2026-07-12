# sonilo

Official Python client for the [Sonilo](https://sonilo.com) API.
Python ≥ 3.9. Sync and async clients included.

## Installation

```bash
pip install sonilo
```

## Quickstart

```python
from sonilo import Sonilo

client = Sonilo()  # reads SONILO_API_KEY

track = client.text_to_music.generate(
    prompt="cinematic orchestral score",
    duration=60,
)
track.save("output.mp3")
print(track.title)
```

## Video to music

```python
track = client.video_to_music.generate(video="my_video.mp4", prompt="upbeat")
# or bytes / an open binary file, or a hosted URL:
track = client.video_to_music.generate(video_url="https://example.com/clip.mp4")
```

## Streaming

```python
for event in client.text_to_music.stream(prompt="lofi", duration=30):
    if event["type"] == "audio_chunk":
        handle(event["data"])  # bytes, as they arrive
```

## Async

```python
from sonilo import AsyncSonilo

async with AsyncSonilo() as client:
    track = await client.text_to_music.generate(prompt="lofi", duration=30)
    async for event in client.text_to_music.stream(prompt="lofi", duration=30):
        ...
```

## Segments

Shape the composition with start-only contiguous segments (each ends where
the next begins):

```python
client.text_to_music.generate(
    prompt="epic trailer",
    duration=60,
    segments=[
        {"start": 0, "prompt": "soft intro", "label": "intro"},
        {"start": 20, "prompt": "building tension", "label": "verse"},
        {"start": 40, "prompt": "full orchestra", "label": "chorus"},
    ],
)
```

## Sound effects (async tasks)

SFX endpoints are asynchronous: submitting returns a `task_id`, and the result
is fetched by polling. `generate()` wraps submit + poll:

```python
from sonilo import Sonilo

with Sonilo() as client:
    result = client.text_to_sfx.generate(prompt="glass shattering", duration=5)
    result.save("sfx.m4a")
```

Or control polling yourself:

```python
task = client.video_to_sfx.submit(
    video="clip.mp4",
    segments=[{"start": 0, "end": 2.5, "prompt": "footsteps on gravel"}],
    audio_format="wav",
)
result = client.tasks.wait(task.task_id, poll_interval=2.0, timeout=600.0)
result.save("audio.wav")
result.save("with_audio.mp4", which="video")  # video-to-sfx also returns the muxed video
```

`tasks.get(task_id)` fetches state once and never raises on a failed task;
`tasks.wait()` / `generate()` raise `TaskFailedError` (with `.code`,
`.refunded`) on failure and `TaskTimeoutError` if the deadline passes — the
task keeps running server-side and can still be polled afterwards. Result URLs
are presigned and expire; download promptly or re-fetch via `tasks.get`.

## Account

```python
client.account.services()
client.account.usage(days=7)
```

## Errors

All errors extend `SoniloError`: `AuthenticationError` (401),
`PaymentRequiredError` (402), `RateLimitError` (429, `.retry_after`),
`BadRequestError` (400/413/422, `.detail`), `APIError` (anything else),
`GenerationError` for failures mid-stream, `TaskFailedError` (`.code`,
`.task_id`, `.refunded`) for a failed SFX task, and `TaskTimeoutError`
(`.task_id`) when `tasks.wait()` / `generate()` hits its deadline.

Every `APIError` also carries `.status_code`, `.body` (the parsed response),
`.code` (the API's error code, e.g. `"rate_limit_exceeded"`), and `.errors`
(the validation detail list on a 422), in addition to any subclass-specific
attributes above.
