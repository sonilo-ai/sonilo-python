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
    sonilo video-to-sfx --video clip.mp4 --segments @segments.json
    sonilo video-to-sound --video clip.mp4 \
        --music-prompt "uplifting orchestral score" --sfx-prompt "match the on-screen action"
    sonilo video-to-video-music --video clip.mp4 --prompt "tense synths" --output scored.mp4
    sonilo video-to-video-sfx --video clip.mp4 --segments @segments.json --output scored.mp4
    sonilo video-to-video-sound --video clip.mp4 --music-prompt "tense synths"
    sonilo dubbing --video-url https://example.com/clip.mp4 --languages es,fr --output dubbed.mp4
    # writes dubbed.es.mp4 and dubbed.fr.mp4
    sonilo tasks get <task-id>
    sonilo tasks wait <task-id> --poll-interval 2 --timeout 600

### Notes

- `text-to-music` / `video-to-music` stream a short `.m4a` by default. `--format wav`,
  `--preserve-speech`, `--variants` above 1, and the legacy alias `--isolate-vocals` each switch
  to the async submit-and-poll path.
- `text-to-sfx` / `video-to-sfx` are always async; `--format` accepts `wav|mp3|aac|flac`.
- Output defaults to `./output.<ext>`; override with `--output`.

### Segments

`--segments` scores a timeline instead of one whole-clip prompt. It takes a JSON array, in one of
three forms — inline, from a file, or from stdin:

    sonilo text-to-music --prompt "warm lo-fi piano" --duration 30 \
        --segments '[{"start":0,"label":"intro","prompt":"airy pads"}]'
    sonilo video-to-sfx --video clip.mp4 --segments @segments.json
    jq -c '.cues' storyboard.json | sonilo video-to-sfx --video clip.mp4 --segments @-

A value starting with `@` names a source to read the JSON from, and `@-` reads standard input — the
same convention as `curl`, `gh` and `aws`. Anything else is parsed as JSON directly.

The two segment shapes are **not** interchangeable:

| Shape | Commands | Fields |
| --- | --- | --- |
| Music | `text-to-music`, `video-to-music` | `{start, prompt, label?}` |
| SFX | `video-to-sfx`, `video-to-video-sfx`, `video-to-sound`, `video-to-video-sound` | `{start, end, prompt}` |

- `start` / `end` are seconds from the start of the track or clip.
- Passing one shape to a command that takes the other is rejected before any request is made, with
  a message naming the shape that command expects.
- Only the shape is checked locally. Timing rules — the first segment starting at 0, minimum
  spacing between segments, the `label` vocabulary, how many segments are allowed — are enforced by
  the API, which answers with a `422` describing what it rejected.
- Keys the CLI does not recognise are forwarded as-is, so a newly added API field works without
  upgrading the CLI.
- `text-to-sfx` takes no segments (its output is a single effect, not a timeline).
- `video-to-video-music` takes no segments either — the API scores the whole clip in one pass.

### Variants

`--variants N` (1-10, default 1) generates that many distinct variants in one request instead of
one, on `text-to-music`, `video-to-music`, `video-to-video-music`, `video-to-sound`, and
`video-to-video-sound`. Cost scales linearly — `--variants 3` costs three times a single-variant
request — and values above 1 are never covered by the free trial.

    sonilo text-to-music --prompt "warm lo-fi piano" --duration 30 --variants 3 --output take.m4a
    # writes take.0.m4a, take.1.m4a, take.2.m4a

- `--variants` above 1 forces the async submit-and-poll path (see [Notes](#notes) above).
- With `--variants` unset (or `1`), a command writes the single `--output` file exactly as before
  this flag existed. Above 1, it instead writes one file per variant, with the variant index
  spliced before the extension: `take.m4a` becomes `take.0.m4a`, `take.1.m4a`, etc. — the same
  naming `--stem` and dubbing's per-language output already use.
- On `video-to-sound` / `video-to-video-sound`, `--stem` is applied per variant too, e.g.
  `take.0.music.m4a`.

### Scored video

`video-to-video-music` and `video-to-video-sfx` are the video-out counterparts of `video-to-music`
and `video-to-sfx`: same generation, but what comes back is the source picture with the new audio
already muxed in, so there is nothing to line up afterwards. Both are async-only and write a single
file (default `output.mp4`):

    sonilo video-to-video-music --video clip.mp4 --prompt "tense synths" --output scored.mp4
    sonilo video-to-video-sfx --video clip.mp4 \
        --segments '[{"start":0,"end":5,"prompt":"footsteps on gravel"}]' --output scored.mp4

- `--prompt` is optional on both; without it the model scores from the picture alone.
- `video-to-video-music` also takes `--preserve-speech`, which keeps source speech in the mix;
  omitting it leaves the server default untouched. `--isolate-vocals` is a legacy alias for the
  same flag — the API ORs the two together, and this endpoint returns one muxed video with no
  separate vocals stem.
- `video-to-video-sfx` takes `--segments` in the SFX shape `{start, end, prompt}` — see
  [Segments](#segments).
- Neither command exposes `--format`: the output is a video, not an audio file.
- For music *and* effects in one call, use `video-to-video-sound` below.
- `video-to-video-music` also takes `--variants` — see [Variants](#variants) above.
  `video-to-video-sfx` does not.

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
- `--segments` places individual effects on the timeline, in the SFX shape `{start, end, prompt}` —
  see [Segments](#segments).
- `--preserve-speech` keeps speech from the source video in the mix.
- **Ducking is on by default** (music dips under speech). Pass `--no-ducking` to opt out — omitting
  the flag leaves the server default untouched.
- `--stem` is repeatable (`music`, `music_processed`, `sfx`) and saves the individual layers next to
  the combined output, so you can re-balance the mix yourself. With `--output soundtrack.wav`, the
  music stem lands at `soundtrack.music.m4a`. `music_processed` exists only when `--preserve-speech`
  or ducking altered the music bed.
- Both also take `--variants` — see [Variants](#variants) above.

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
- `--timeout` defaults to 7200 seconds, matching the backend's own ceiling for a dubbing job
  (far longer than other commands' default, since dubbing can run well past the usual
  `tasks wait --timeout 600`). If the wait still times out, the task keeps running
  server-side — resume watching it with `sonilo tasks wait <task-id>`.

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

## Rate limits

Two separate limits return `HTTP 429`, and they want opposite handling. The CLI prints the API's
own sentence, so the wording says which one you hit:

    sonilo: HTTP 429: Rate limit exceeded: your account allows 60 requests per minute. Please retry after 1 minute. To raise your limit, please contact info@sonilo.com. (rate_limit_exceeded)
    sonilo: HTTP 429: Too many concurrent generations: 5 of 5 in progress. Please wait for one to finish before starting another. To raise your limit, please contact info@sonilo.com. (rate_limit_exceeded)

The first means calls are going out too fast. The counter runs on a fixed 60-second window and
rejected calls count toward it too, so wait the window out instead of retrying inside it. The
second means every generation slot is busy — waiting alone frees nothing, a running generation has
to finish first.

`sonilo account` prints the account's own `rpm_limit` and `concurrency_limit`; the numbers above
are the standard-tier defaults. Email info@sonilo.com to raise either.
