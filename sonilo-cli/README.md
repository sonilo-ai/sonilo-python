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
    sonilo tasks get <task-id>
    sonilo tasks wait <task-id> --poll-interval 2 --timeout 600

### Notes

- `text-to-music` / `video-to-music` stream a short `.m4a` by default. `--format wav`,
  `--isolate-vocals`, and `--preserve-speech` each switch to the async submit-and-poll path.
- `text-to-sfx` / `video-to-sfx` are always async; `--format` accepts `wav|mp3|aac|flac`.
- Output defaults to `./output.<ext>`; override with `--output`.
