# sonilo

Official Python client for the [Sonilo](https://sonilo.com) API.
Python ≥ 3.9. Sync and async clients included.

## Installation

```bash
pip install sonilo
```

## Command-line interface

Prefer a terminal over Python? [`sonilo-cli`](./sonilo-cli/) wraps this client
in a `sonilo` command for music and SFX generation:

```bash
pip install sonilo-cli
sonilo text-to-music --prompt "warm lo-fi piano, rain" --duration 30
```

## Authentication

Create an API key in your [Sonilo dashboard](https://platform.sonilo.com/dashboard/api-keys?utm_source=sonilo_python&utm_medium=readme&utm_campaign=sdk_quickstart),
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

### Variants (async)

`variants_num` (1-10, default `1`) generates that many distinct music
variants in one request instead of one — each is its own creative direction
with its own title. It's an async-only option, same as `output_format`:
`submit()` / `generate_async()` accept it on both `text_to_music` and
`video_to_music`, auto-selecting async when it's above 1 (an explicit
non-async `mode` alongside `variants_num > 1` raises `SoniloError` locally,
same as the other async-only options above). Cost scales linearly —
`variants_num=3` costs three times a single-variant request — and values
above 1 are never covered by the free trial.

```python
result = client.text_to_music.generate_async(
    prompt="cinematic orchestral score",
    duration=30,
    variants_num=3,
)
for i in range(len(result.audio)):
    result.save(f"variant_{i}.m4a", index=i)
    title = result.audio[i].title
    print(i, title.title if title else None)
```

`result.audio` always has one entry per variant; with `variants_num=1` (the
default) that's the same single-entry list as before this option existed, and
the top-level `result.title` stays an alias for `result.audio[0].title`.

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

`video_to_video_music` also takes `variants_num` (1-10, default `1`): each
variant scores the source video with a different musical direction. This
endpoint is already async-only, so no `mode` to auto-select — `variants_num`
just travels straight through.

```python
music = client.video_to_video_music.generate(
    video="my_video.mp4", prompt="cinematic orchestral swell", variants_num=3,
)
for i in range(len(music.videos)):
    music.save(f"scored_{i}.mp4", index=i)
```

`music.videos` always has one entry per variant; `music.video` stays a
permanent alias for `music.videos[0]`, so `music.save("scored.mp4")` (no
`index`) keeps working exactly as it did before `variants_num` existed.

## Video to sound

`video_to_sound` and `video_to_video_sound` generate a music bed and sound
effects for the same clip and return them mixed into a single soundtrack — one
call, one charge, instead of chaining two requests. `video_to_sound` returns the
mixed audio; `video_to_video_sound` returns the source video with that audio
muxed in. Both are async-only, and both take the same options.

```python
from sonilo import Sonilo

client = Sonilo()

result = client.video_to_sound.generate(
    video_url="https://example.com/clip.mp4",
    music_prompt="uplifting orchestral score",
    sfx_prompt="match the on-screen action",
)
result.save("soundtrack.wav")
```

The mixed result is `output_url` (`output_type` is `"audio"` here, `"video"`
for `video_to_video_sound`). The individual stems come back alongside it, so
you can re-balance the mix yourself:

```python
result.save_stem("music.m4a", which="music")
result.save_stem("sfx.wav", which="sfx")
```

`preserve_speech=True` keeps the speech from the source video, and `ducking`
(on by default) dips the music under it — pass `ducking=False` to opt out.
`segments` takes the same `{"start", "end", "prompt"}` list as `video_to_sfx`.
Input videos may be at most 180 seconds long.

Both also take `variants_num` (1-10, default `1`): each variant pairs its own
generated music with its own generated sound effects. Like
`video_to_video_music`, these endpoints are already async-only, so
`variants_num` needs no `mode` to auto-select.

```python
result = client.video_to_sound.generate(
    video_url="https://example.com/clip.mp4",
    music_prompt="uplifting orchestral score",
    variants_num=3,
)
for i in range(len(result.outputs)):
    result.save(f"soundtrack_{i}.wav", index=i)
    result.save_stem(f"music_{i}.m4a", which="music", index=i)
```

`result.outputs` always has one entry per variant, sorted by `variant_index`;
`output_url`/`output_type`/`output_bytes`/`music`/`music_processed`/`sfx`
stay aliases for `outputs[0]`'s corresponding fields, so `result.save(...)`
and `result.save_stem(...)` (no `index`) keep working exactly as they did
before `variants_num` existed.

Use `submit()` instead of `generate()` to get a `task_id` back immediately and
poll it yourself with `client.tasks.wait(task_id, parser=parse_sound_result)`.
`AsyncSonilo` exposes the same two resources with `await`-able
`submit`/`generate` and `asave`/`asave_stem`.

## Dubbing

`client.dubbing` dubs one video into one or more target languages in a single
async call. Pass exactly one of `video` / `video_url` (`video_url` must be
**https**), plus optional `languages` — it defaults server-side to
`["zh_cn", "es", "fr"]`; supported codes are `en, zh_cn, ja, ko, pt, es, de,
fr, it, ru`. Source videos may be at most 180 seconds long, and billing is
per language: a 3-language call costs three times as much as one. Dubbing has
no free trial allowance — see [Free trial](#free-trial).

The SDK's default wait is `DEFAULT_WAIT_TIMEOUT` (600 seconds), but the
dubbing pipeline can take much longer than that — especially with several
languages in one call. Pass a longer `timeout` explicitly: 7200 seconds
matches the backend's own ceiling for a dubbing job, and is what the CLI
defaults to. Note that a client-side timeout only stops *waiting* — it does
not cancel the task or refund what's already been billed, so for long jobs
prefer `submit()` plus your own `client.tasks.wait(...)` over `generate()`.

```python
from sonilo import Sonilo

with Sonilo() as client:
    result = client.dubbing.generate(
        video_url="https://example.com/clip.mp4",
        languages=["es", "fr"],
        timeout=7200,
    )
    for language, path in result.save_all("./dubbed").items():
        print(language, path)
```

`DubbingResult.outputs` is a language → dubbed-`.mp4`-URL map — there's no
single `output_url` since one call produces multiple videos. Use
`result.save(language, path)` to fetch just one language, or `save_all(dir)`
for all of them; `AsyncSonilo` exposes the same shape with `asave`/`asave_all`.
Use `submit()` instead of `generate()` to get a `task_id` back immediately and
poll it yourself with `client.tasks.wait(task_id, parser=parse_dubbing_result)`.

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

## Free trial

Accounts created through self-serve signup start with free runs on most
endpoints — no card required:

| Free runs | Endpoints |
| --- | --- |
| 2 each | text-to-music, text-to-sfx, audio-ducking |
| 1 each | video-to-music, video-to-sfx, video-to-video-music, video-to-video-sfx, video-to-sound, video-to-video-sound |
| 0 | dubbing |

Dubbing bills `video duration × number of languages`, so a free run on it
would be worth far more than a free run on any other endpoint — it has no
free allowance and bills from the first call.

Once an endpoint's free runs are used up, calls to it bill at the normal rate.

The table above is the current default. Read the live numbers from
`account.services()` rather than hard-coding them — see [Account](#account)
below, and [Errors](#errors) for what a spent trial looks like at the call
site.

## Account

```python
client.account.services()
client.account.usage(days=7)
```

`services()["trial"]` reports the free-trial allowance per service, so an
integration can degrade gracefully *before* a call fails:

```python
quota = client.account.services().get("trial", {}).get("text_to_music")
if quota and quota["remaining"] == 0:
    # Prompt for a payment method instead of firing a call that will 402.
    print(f"Free trial spent ({quota['used']}/{quota['granted']}).")
```

`trial` is present only for self-serve accounts, so always treat it as
optional; a service missing from the map has no trial allowance rather than
an unlimited one. `AccountServices` and `TrialQuota` are exported as
`TypedDict`s for type checking — the return value is a plain `dict` at
runtime.

## Errors

All errors extend `SoniloError`: `AuthenticationError` (401),
`PaymentRequiredError` (402), `TrialExhaustedError` (402, a subclass of
`PaymentRequiredError`), `RateLimitError` (429, `.retry_after`),
`BadRequestError` (400/413/422, `.detail`), `APIError` (anything else),
`GenerationError` for failures mid-stream, `TaskFailedError` (`.code`,
`.task_id`, `.refunded`) for a failed SFX task, and `TaskTimeoutError`
(`.task_id`) when `tasks.wait()` / `generate()` hits its deadline.

Every `APIError` also carries `.status_code`, `.body` (the parsed response),
`.code` (the API's error code, e.g. `"rate_limit_exceeded"`), and `.errors`
(the validation detail list on a 422), in addition to any subclass-specific
attributes above.

### The three 402s

A `402` is not one condition. Branch on the class (or equivalently on
`.code`), never on the message text:

```python
from sonilo import PaymentRequiredError, TrialExhaustedError

try:
    client.text_to_music.generate(prompt="lofi", duration=30)
except TrialExhaustedError:
    # code: "trial_exhausted" — the free trial for this service is spent and
    # the account has never been funded. Prompt for a payment method; a retry
    # can never succeed.
    ...
except PaymentRequiredError as exc:
    # code: "insufficient_balance" — a funded wallet ran dry. Add balance and
    # retry the same request.
    # code: "payment_required" — anything else, e.g. a suspended account.
    print(exc.code)
```

`TrialExhaustedError` subclasses `PaymentRequiredError`, so an existing
`except PaymentRequiredError` keeps catching every 402 — order the handlers
most-specific-first if you want to tell them apart.
