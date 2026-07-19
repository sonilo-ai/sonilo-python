# sonilo

Official Python client for the [Sonilo](https://sonilo.com) API.
Python ≥ 3.9. Sync and async clients included.

## Installation

```bash
pip install sonilo
```

## Authentication

Create an API key in your [Sonilo dashboard](https://platform.sonilo.com/dashboard/api-keys),
then give it to the client either as an environment variable (recommended) or
inline:

```bash
export SONILO_API_KEY=sk_...
```

```python
client = Sonilo()                  # reads SONILO_API_KEY
client = Sonilo(api_key="sk_...")  # or pass it directly
```

Keep your key secret — use it only server-side, never commit it, and prefer the
environment variable over hardcoding it.

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

### Preserve speech (async)

Pass `preserve_speech=True` to keep the source speech/vocals in the result.
You also get a separate speech stem (`vocals`) and a mux (the generated music
mixed with the preserved speech) alongside the scored audio. This requires async
processing — submit returns a `task_id` immediately, and `generate_async()`
wraps submit + poll:

```python
result = client.video_to_music.generate_async(
    video="my_video.mp4",
    prompt="upbeat",
    preserve_speech=True,  # implies mode="async"; omit mode to let it auto-select
)
result.save("mix.m4a")           # result.audio[0] — the full mix
result.save("vocals.m4a", which="vocals")
result.save("video.mp4", which="mux")  # generated music muxed with the preserved speech
print(result.title.title if result.title else None)
```

Or control submission and polling yourself:

```python
from sonilo.resources.tasks import parse_music_result

task = client.video_to_music.submit(video_url="https://example.com/clip.mp4", preserve_speech=True)
result = client.tasks.wait(
    task.task_id,
    parser=parse_music_result,  # required: tasks.wait()/get() default to the SFX parser
)
```

`preserve_speech=True` with an explicit non-async `mode` raises `SoniloError`
locally before any request is sent.

### Ducking, speech & output format (async video-to-music)

`submit()` / `generate_async()` also accept:

- `preserve_speech` — keep the source speech/vocals in the result (see
  [Preserve speech](#preserve-speech-async) above).
- `ducking` — duck the generated music under the source voice. It is **on by
  default** in async mode; pass `ducking=False` to opt out. When it runs, the
  result gains a `ducked` list alongside `audio`.
- `output_format` — `"m4a"` (default) or `"wav"` (requires async mode).

```python
result = client.video_to_music.generate_async(
    video="my_video.mp4",
    preserve_speech=True,
    output_format="wav",
    # ducking defaults on in async — pass ducking=False to disable
)
result.save("track.wav")
if result.ducked:
    result.save("ducked.wav", which="ducked")
```

## Video to video

Generate music or sound effects and get back a **re-hosted video** with the
audio muxed in — not just an audio file. Both endpoints are async; `generate()`
submits and polls to a `VideoResult`:

```python
music = client.video_to_video_music.generate(
    video="my_video.mp4",  # path, bytes, open file, or use video_url=
    prompt="cinematic orchestral swell",
    preserve_speech=True,
)
music.save("scored.mp4")

sfx = client.video_to_video_sfx.generate(
    video="my_video.mp4",
    segments=[{"start": 0, "end": 2, "prompt": "footsteps on gravel"}],
)
sfx.save("with_sfx.mp4")
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
result.save("audio.wav")  # video-to-sfx returns the generated audio only
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
