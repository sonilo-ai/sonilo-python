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

## Account

```python
client.account.services()
client.account.usage(days=7)
```

## Errors

All errors extend `SoniloError`: `AuthenticationError` (401),
`PaymentRequiredError` (402), `RateLimitError` (429, `.retry_after`),
`BadRequestError` (400/413/422, `.detail`), `APIError` (anything else),
and `GenerationError` for failures mid-stream.

## License

MIT
