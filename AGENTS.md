# AGENTS.md

Notes for coding agents working in this repo, and for agents writing code
against the Sonilo Python packages.

## What this repo is

Three PyPI packages in one repo:

| Package | Path | What it is |
|---|---|---|
| `sonilo` | `.` (`src/sonilo`) | Python client for the Sonilo API. Sync (`Sonilo`) and async (`AsyncSonilo`) clients, Python 3.9+, only depends on `httpx` |
| `sonilo-cli` | `sonilo-cli/` | `sonilo` command line tool, built on `sonilo` |
| `sonilo-video-kit` | `sonilo-video-kit/` | Helpers that generate a soundtrack, duck it under speech and mix it into a video with local ffmpeg |

The TypeScript counterparts live in
[sonilo-js](https://github.com/sonilo-ai/sonilo-js).

## Layout

```
src/sonilo/_client.py            Sonilo: auth, base URL, timeout, transport
src/sonilo/_async_client.py      AsyncSonilo, same surface with async methods
src/sonilo/resources/*.py        one module per endpoint (text_to_music, video_to_sfx, dubbing, ...)
src/sonilo/resources/tasks.py    tasks.get / tasks.wait and the parse_*_result parsers
src/sonilo/errors.py             error classes, mapped from HTTP status and the API `code`
src/sonilo/types.py              result dataclasses and TypedDicts
src/sonilo/_version.py           __version__, sent in X-Sonilo-Client-Version
sonilo-cli/src/sonilo_cli/       __main__.py (every command), login.py, credentials.py
sonilo-video-kit/src/sonilo_video_kit/  generate, duck, mix, loudness, ffmpeg wrappers
context7.json                    rules Context7 serves to coding assistants (checked by sonilo-cli/tests/test_context7.py)
examples/                        runnable scripts
```

## Commands

CI (`.github/workflows/ci.yml`) runs on Python 3.9 and 3.12 with ffmpeg
installed:

```bash
pip install -e ".[dev]" -e "./sonilo-video-kit[dev]" -e "./sonilo-cli[dev]"
pytest                    # sonilo
pytest sonilo-video-kit   # needs ffmpeg and ffprobe on PATH
pytest sonilo-cli
```

Tests mock HTTP with `respx`; none of them call the real API.

## Making changes

- Keep `sonilo` on Python 3.9 syntax (`Optional[...]`, `from __future__ import annotations`)
  and on `httpx` as its only dependency.
- Every resource has a sync class and an async class in the same module. Change
  both, and cover both in tests.
- New endpoint: add a module under `src/sonilo/resources/`, attach it in both
  `_client.py` and `_async_client.py`, export new result types from
  `src/sonilo/__init__.py`, add tests, document it in `README.md`, then add the
  CLI command in `sonilo-cli/src/sonilo_cli/__main__.py` if a user would run it
  from a terminal.
- Use the API's field names (`video_url`, `variants_num`, `output_format`) as
  the Python keyword arguments.
- Tri-state options (`ducking`, `preserve_speech`) are sent only when not
  `None`, so the server default applies when they are left unset.
- Branch on the API's error `code`, never on message text.
- Wrappers pass `client_name` / `client_version` (`cli-python`,
  `videokit-python`) so their traffic is reported in the `X-Sonilo-Client`
  header; direct SDK use leaves them unset.
- `context7.json` rules are limited to 255 characters each and 50 in total;
  `sonilo-cli/tests/test_context7.py` enforces it.

## Releases

Each package publishes to PyPI through OIDC Trusted Publishing when its tag is
pushed. The workflow fails if the tag does not match the version in the
package's `pyproject.toml`.

| Package | Bump | Tag | Workflow |
|---|---|---|---|
| `sonilo` | `pyproject.toml` and `src/sonilo/_version.py` | `vX.Y.Z` | `publish.yml` |
| `sonilo-cli` | `sonilo-cli/pyproject.toml` and `sonilo_cli/__init__.py` | `sonilo-cli-vX.Y.Z` | `publish-cli.yml` |
| `sonilo-video-kit` | `sonilo-video-kit/pyproject.toml` and `sonilo_video_kit/_version.py` | `sonilo-video-kit-vX.Y.Z` | `publish-video-kit.yml` |

`sonilo-cli` pins `sonilo>=X.Y,<X.(Y+1)`; raise that pin when the CLI needs a
new SDK release.

## Using the SDK

Get an `sk-` key at https://platform.sonilo.com/dashboard/api-keys and set
`SONILO_API_KEY`, or pass `api_key=`. The CLI also accepts the credential that
`sonilo login` stores in `~/.config/sonilo/credentials.json`.

```python
from sonilo import Sonilo

client = Sonilo()  # reads SONILO_API_KEY; base_url defaults to https://api.sonilo.com

# Music streams back as m4a bytes; for wav or mp3 use generate_async(output_format=...)
track = client.video_to_music.generate(video="clip.mp4", prompt="warm, hopeful")
track.save("music.m4a")

# Task-based endpoints: generate() submits and waits; submit() returns a task_id
sfx = client.text_to_sfx.generate(prompt="glass shattering on stone", duration=5)
sfx.save("sfx.m4a")

from sonilo.resources.tasks import parse_sound_result
task = client.video_to_sound.submit(video_url="https://example.com/clip.mp4")
result = client.tasks.wait(task.task_id, parser=parse_sound_result)
```

`tasks.wait()` and `tasks.get()` default to the SFX parser; pass the matching
`parse_*_result` for music, sound, dubbing, proofread and analysis tasks.

Resources on the client: `text_to_music`, `video_to_music`, `text_to_sfx`,
`video_to_sfx`, `video_to_video_music`, `video_to_video_sfx`, `video_to_sound`,
`video_to_video_sound`, `video_analysis` (`analyze()`, returns a brief, not
media), `audio_ducking`, `dubbing`, `proofread`, `tasks`, `account`.

CLI commands: `sonilo text-to-music`, `video-to-music`, `text-to-sfx`,
`video-to-sfx`, `video-to-sound`, `video-to-video-music`, `video-to-video-sfx`,
`video-to-video-sound`, `audio-ducking`, `video-analysis`, `dubbing`,
`proofread`, `tasks get|wait`, `account`, `usage`, `login`, `whoami`, `logout`.

Video length caps (422 before any charge): music 360 s; SFX, sound and video
analysis 480 s; audio ducking 360 s per input; dubbing and proofread 300 s.

## Errors

| Class | Status / code | What to do |
|---|---|---|
| `AuthenticationError` | 401 | Key invalid, revoked or expired; replace it or `sonilo login` again |
| `TrialExhaustedError` | 402 `trial_exhausted` | Free runs for that service are spent; add a payment method at https://platform.sonilo.com/dashboard/billing. Retrying cannot help |
| `PaymentRequiredError` | 402 `insufficient_balance`, `payment_required` | Top up, then retry |
| `BadRequestError` | 400 / 413 / 422 | Bad parameters, file too large, over a length cap; `.detail` and `.errors` say which |
| `RateLimitError` | 429 `rate_limit_exceeded` | Requests per minute: wait a full minute. Concurrency: wait for one of your running tasks to finish |
| `GenerationError` | | A streamed `generate()` sent an `error` event mid-stream |
| `TaskFailedError` | task `failed` | `.code`, `.task_id`, `.refunded`; failed generations are refunded |
| `TaskTimeoutError` | | Still running and already charged; call `tasks.wait(err.task_id)` again instead of resubmitting |

All of them extend `SoniloError`. `TrialExhaustedError` extends
`PaymentRequiredError`, so catch it first. `client.account.services()` reports
the remaining free runs (`trial`) and the account's `rpm_limit` and
`concurrency_limit`.
