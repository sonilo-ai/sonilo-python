# sonilo-cli

Command-line interface for the [Sonilo API](https://github.com/sonilo-ai/sonilo-python) — generate music and sound effects from text or video.

## Install

    pip install sonilo-cli

## Auth

Set your API key once:

    export SONILO_API_KEY=sk-...

or pass `--api-key sk-...` on any command.

## Commands

    sonilo account                     # plan limits and available services
    sonilo usage --days 7              # usage summary
    sonilo text-to-music --prompt "warm lo-fi piano, rain" --duration 30
    sonilo video-to-music --video clip.mp4 --prompt "tense synths" --format wav
    sonilo text-to-sfx --prompt "glass shattering on concrete" --duration 3
    sonilo video-to-sfx --video clip.mp4 --output whoosh.wav
    sonilo video-to-sound --video clip.mp4 \
        --music-prompt "uplifting orchestral score" --sfx-prompt "match the on-screen action"
    sonilo video-to-video-sound --video clip.mp4 --music-prompt "tense synths"
    sonilo dubbing --video-url https://example.com/clip.mp4 --languages es,fr --output dubbed.mp4
    # writes dubbed.es.mp4 and dubbed.fr.mp4
    sonilo tasks get <task-id>
    sonilo tasks wait <task-id> --poll-interval 2 --timeout 600

### Notes

- `text-to-music` / `video-to-music` stream a short `.m4a` by default. `--format wav`,
  `--isolate-vocals`, and `--preserve-speech` each switch to the async submit-and-poll path.
- `text-to-sfx` / `video-to-sfx` are always async; `--format` accepts `wav|mp3|aac|flac`.
- Output defaults to `./output.<ext>`; override with `--output`.

### Combined soundtracks

`video-to-sound` and `video-to-video-sound` score a clip with a music bed *and* sound effects in one
call (one charge, instead of chaining two requests). Both are async-only and take the same options —
they differ only in what comes back: `video-to-sound` writes the mixed **audio** (default
`output.wav`), `video-to-video-sound` writes the **source video with that audio muxed in** (default
`output.mp4`).

    sonilo video-to-sound --video clip.mp4 \
        --music-prompt "uplifting orchestral score" \
        --sfx-prompt "match the on-screen action" \
        --output soundtrack.wav --stem music --stem sfx

- `--music-prompt` / `--sfx-prompt` steer the two layers separately; both are optional.
- `--preserve-speech` keeps speech from the source video in the mix.
- **Ducking is on by default** (music dips under speech). Pass `--no-ducking` to opt out — omitting
  the flag leaves the server default untouched.
- `--stem` is repeatable (`music`, `music_processed`, `sfx`) and saves the individual layers next to
  the combined output, so you can re-balance the mix yourself. With `--output soundtrack.wav`, the
  music stem lands at `soundtrack.music.m4a`. `music_processed` exists only when `--preserve-speech`
  or ducking altered the music bed.

### Dubbing

`dubbing` dubs a video into one or more target languages in a single async call:

    sonilo dubbing --video-url https://example.com/clip.mp4 --languages es,fr --output dubbed.mp4
    # writes dubbed.es.mp4 and dubbed.fr.mp4

- `--languages` is comma-separated; omit it to use the server default `zh_cn,es,fr`. Supported
  codes: `en, zh_cn, ja, ko, pt, es, de, fr, it, ru`.
- Source videos may be at most 180 seconds long.
- `--output` is a filename template, not a single destination: a dubbing task returns one video
  per language, so `--output clip.mp4` writes `clip.es.mp4`, `clip.fr.mp4`, etc.
- Billing is per language, and dubbing has **no free trial runs** — see [Free trial](#free-trial)
  below.
- `--timeout` defaults to 3600 seconds (longer than other commands' default, since dubbing can run
  well past the usual `tasks wait --timeout 600`). If the wait still times out, the task keeps
  running server-side — resume watching it with `sonilo tasks wait <task-id>`.

## Free trial

Accounts created through self-serve signup start with free runs on most endpoints — no card
required:

| Free runs | Endpoints |
| --- | --- |
| 2 each | text-to-music, text-to-sfx, audio-ducking |
| 1 each | video-to-music, video-to-sfx, video-to-video-music, video-to-video-sfx, video-to-sound, video-to-video-sound |
| 0 | dubbing |

Dubbing bills `video duration × number of languages`, so a free run on it would be worth far more
than a free run on any other endpoint — it has no free allowance and bills from the first call.

The table above is the current default. `sonilo account` prints the live numbers: the account JSON
goes to stdout, and when the account has a free-trial allowance one summary line goes to stderr:

    Free trial: text-to-music 1/2 left, video-to-music 0/1 left

Because the summary is on stderr, `sonilo account | jq .trial` still sees clean JSON.

Once an endpoint's free runs are used up, calls to it bill at the normal rate — or, if the account
has never been funded, fail with `HTTP 402: ... (trial_exhausted)` until a payment method is added.
That is the one 402 a retry can never fix.
