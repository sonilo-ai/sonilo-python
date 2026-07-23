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

## Free trial

Accounts created through self-serve signup start with free runs on every endpoint — no card
required:

| Free runs | Endpoints |
| --- | --- |
| 2 each | text-to-music, text-to-sfx, audio-ducking |
| 1 each | video-to-music, video-to-sfx, video-to-video-music, video-to-video-sfx, video-to-sound, video-to-video-sound |

Once an endpoint's free runs are used up, calls to it bill at the normal rate. `sonilo account`
shows the services available to your key.
