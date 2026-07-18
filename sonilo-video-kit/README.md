# sonilo-video-kit

Video helpers for the [Sonilo](https://sonilo.com) API: generate a soundtrack
for a video and mix it in locally with ffmpeg. Python ≥ 3.9.

Requires `ffmpeg` + `ffprobe` on your PATH (macOS: `brew install ffmpeg`,
Debian/Ubuntu: `apt-get install ffmpeg`) — or pass `ffmpeg_path`/`ffprobe_path`
to any function.

## Installation

```bash
pip install sonilo sonilo-video-kit
```

`sonilo` (the core client) is a required dependency — it is installed
automatically alongside the kit, but is shown here for clarity.

## Quickstart

```python
from sonilo_video_kit import generate_music_for_video, mix_with_video

track = generate_music_for_video("./clip.mp4", prompt="upbeat, energetic")  # uses SONILO_API_KEY

mix_with_video(
    video="./clip.mp4",
    audio=track.audio,
    output="./clip.scored.mp4",
)
```

## Loudness-matched mixing

By default the kit measures the loudness (LUFS) of your video's own audio and
of the generated music, then sits the music 4 LU below the original — so
dialogue stays intelligible without hand-tuning. The final file is normalized
to −14 LUFS (streaming-platform delivery level) with a −1 dBFS peak limiter.
The delivery-normalize boost is capped at +12 dB; attenuation (bringing an
overly loud render down to target) is uncapped.

- `music_volume` (0–1, default 0.5): 0.5 is the matched level; each step of
  0.25 shifts ±6 dB (full range ±12 dB). 0 mutes the music.
- `original_volume` (0–1, default 1): absolute — 1 keeps the original exactly
  as recorded, 0 removes it entirely.
- `loudness_match=False` switches both knobs to plain absolute gains.
- `normalize=False` skips the delivery-loudness pass.

If loudness measurement fails (exotic codecs, unreadable audio), the kit
silently falls back to absolute-gain behavior rather than failing your render.

## Ducking

`mix_with_video` sits the music at a fixed level under the original audio.
`duck_music_under_speech` goes further: it rides the music down whenever
someone speaks and back up in the gaps.

```python
from sonilo_video_kit import duck_music_under_speech

duck_music_under_speech(
    video="./interview.mp4",
    audio=track.audio,
    output="./interview.ducked.mp4",
)
```

Unlike `mix_with_video`, which is entirely local and free, this calls the
Sonilo ducking API and is **billed on your video's duration**. The kit
uploads only the video's extracted audio track — your picture never leaves
the machine and is copied into the result untouched. The API sets the
ducking curve itself (speech gate, duck depth, −14 LUFS delivery, −1 dBTP
ceiling), so there are no volume knobs to pass.

Requirements are enforced locally, before anything is uploaded or charged:
the video must have an audio track and a real picture, it must run no longer
than **360 s**, `output` must carry a file extension and live in a directory
that already exists and is writable, and your picture must be
stream-copyable into `output`'s container. Any failure raises before the API
is called; the kit never quietly falls back to an un-ducked mix. Use
`mix_with_video` for silent or longer videos.

If a failure happens *after* the ducking job is submitted (you have already
been billed), the kit never throws away the mix you paid for: it retries
transient errors, and on a non-recoverable failure it saves the ducked audio
to `<output>.ducked.wav` and raises a `VideoKitError` naming the task id and
that path, so you can finish locally instead of calling
`duck_music_under_speech` again and being billed a second time.

## Errors

`VideoKitError` (invalid arguments, unreadable video), `FfmpegNotFoundError`
(ffmpeg/ffprobe missing — message includes install hints), `FfmpegError`
(ffmpeg failed — carries `exit_code` and `stderr_tail`), `DuckingFailedError`
(the ducking API accepted the job but could not finish it — carries `code`
and `refunded`). Errors from the Sonilo API pass through as the `sonilo`
package's typed errors.

## License

MIT
