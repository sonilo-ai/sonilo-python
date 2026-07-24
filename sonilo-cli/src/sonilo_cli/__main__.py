from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, NoReturn, Optional
from urllib.parse import urlparse

from sonilo import Sonilo
from sonilo.errors import APIError, SoniloError

from sonilo_cli import __version__


class _Parser(argparse.ArgumentParser):
    """ArgumentParser that fails with `sonilo: <msg>` and exit code 1."""

    def error(self, message: str) -> NoReturn:  # noqa: D401
        sys.stderr.write(f"sonilo: {message}\n")
        raise SystemExit(1)


def _fail(message: str) -> NoReturn:
    sys.stderr.write(f"sonilo: {message}\n")
    raise SystemExit(1)


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2))


def _wrote(path: Any, size: int) -> None:
    print(f"Wrote {path} ({size:,} bytes)")


def build_client(api_key: Optional[str]) -> Sonilo:
    key = api_key or os.environ.get("SONILO_API_KEY")
    if not key:
        _fail(
            "no API key — pass --api-key <key> or set the "
            "SONILO_API_KEY environment variable"
        )
    # Identify as the CLI rather than inheriting the SDK's own name, so CLI
    # traffic stays separable from direct SDK use in server-side analytics.
    return Sonilo(api_key=key, client_name="cli-python", client_version=__version__)


def format_trial_summary(trial: Optional[Dict[str, Any]]) -> Optional[str]:
    """One-line human summary of the free-trial allowance, e.g.
    "Free trial: text-to-music 1/2 left, video-to-music 0/1 left".

    Returns None when there is nothing to report — the `trial` field is
    present only for self-serve accounts, and printing an empty "Free trial:"
    label would read as a bug.
    """
    if not trial:
        return None
    parts = [
        # Service keys are task_types (text_to_music); show them the way the
        # endpoints and the error messages spell them (text-to-music).
        f"{service.replace('_', '-')} {quota['remaining']}/{quota['granted']} left"
        for service, quota in trial.items()
    ]
    return f"Free trial: {', '.join(parts)}"


def cmd_account(client: Sonilo, args: argparse.Namespace) -> None:
    services = client.account.services()
    _print_json(services)
    # stdout stays pure JSON so `sonilo account | jq` keeps working; the
    # human-readable summary goes to stderr.
    summary = format_trial_summary(services.get("trial"))
    if summary is not None:
        sys.stderr.write(f"{summary}\n")


def cmd_usage(client: Sonilo, args: argparse.Namespace) -> None:
    _print_json(client.account.usage(days=args.days))


def _music_output(args: argparse.Namespace, fmt: str) -> str:
    return args.output if args.output is not None else f"output.{fmt}"


def cmd_text_to_music(client: Sonilo, args: argparse.Namespace) -> None:
    fmt = args.format
    use_async = args.use_async or fmt == "wav"
    out = _music_output(args, fmt)
    if use_async:
        result = client.text_to_music.generate_async(
            prompt=args.prompt,
            duration=args.duration,
            output_format="wav" if fmt == "wav" else None,
        )
        path = result.save(out)
        _wrote(path, path.stat().st_size)
    else:
        track = client.text_to_music.generate(prompt=args.prompt, duration=args.duration)
        path = track.save(out)
        _wrote(path, len(track.audio))


def cmd_video_to_music(client: Sonilo, args: argparse.Namespace) -> None:
    fmt = args.format
    use_async = args.use_async or fmt == "wav" or args.isolate_vocals or args.preserve_speech
    out = _music_output(args, fmt)
    if use_async:
        result = client.video_to_music.generate_async(
            video=args.video,
            video_url=args.video_url,
            prompt=args.prompt,
            isolate_vocals=args.isolate_vocals or None,
            preserve_speech=args.preserve_speech or None,
            output_format="wav" if fmt == "wav" else None,
        )
        path = result.save(out)
        _wrote(path, path.stat().st_size)
    else:
        track = client.video_to_music.generate(
            video=args.video, video_url=args.video_url, prompt=args.prompt
        )
        path = track.save(out)
        _wrote(path, len(track.audio))


_SFX_FORMATS = ["wav", "mp3", "aac", "flac"]


def cmd_text_to_sfx(client: Sonilo, args: argparse.Namespace) -> None:
    out = args.output if args.output is not None else f"output.{args.format}"
    result = client.text_to_sfx.generate(
        prompt=args.prompt, duration=args.duration, audio_format=args.format
    )
    path = result.save(out)
    _wrote(path, path.stat().st_size)


def cmd_video_to_sfx(client: Sonilo, args: argparse.Namespace) -> None:
    out = args.output if args.output is not None else f"output.{args.format}"
    result = client.video_to_sfx.generate(
        video=args.video, video_url=args.video_url,
        prompt=args.prompt, audio_format=args.format,
    )
    path = result.save(out)
    _wrote(path, path.stat().st_size)


_SOUND_STEMS = ["music", "music_processed", "sfx"]


def _stem_path(out: str, stem: str, media: Any) -> str:
    base = Path(out)
    ext = ""
    if media is not None and getattr(media, "url", None):
        ext = Path(urlparse(media.url).path).suffix
    return str(base.with_name(f"{base.stem}.{stem}{ext or base.suffix}"))


def _run_sound(client: Sonilo, args: argparse.Namespace, resource: Any, default_ext: str) -> None:
    out = args.output if args.output is not None else f"output.{default_ext}"
    result = resource.generate(
        video=args.video,
        video_url=args.video_url,
        music_prompt=args.music_prompt,
        sfx_prompt=args.sfx_prompt,
        preserve_speech=True if args.preserve_speech else None,
        ducking=False if args.no_ducking else None,
    )
    path = result.save(out)
    _wrote(path, path.stat().st_size)
    for stem in args.stems or []:
        stem_path = _stem_path(out, stem, getattr(result, stem, None))
        saved = result.save_stem(stem_path, which=stem)
        _wrote(saved, saved.stat().st_size)


def cmd_video_to_sound(client: Sonilo, args: argparse.Namespace) -> None:
    _run_sound(client, args, client.video_to_sound, "wav")


def cmd_video_to_video_sound(client: Sonilo, args: argparse.Namespace) -> None:
    _run_sound(client, args, client.video_to_video_sound, "mp4")


# The dubbing backend polls its pipeline for up to 7200s (2 hours), so the
# SDK's DEFAULT_WAIT_TIMEOUT of 600s would routinely abandon a job the user
# has already been charged for. Wait an hour by default; --timeout overrides.
DUBBING_WAIT_TIMEOUT = 3600.0


def _language_path(out: str, language: str) -> str:
    """Turn one --output value into a per-language path: `clip.mp4` + `es`
    becomes `clip.es.mp4`. A dubbing task returns one video per language, so a
    single literal destination cannot express the result. This is the same
    transform _stem_path applies for --stem, so both flags read the same way."""
    base = Path(out)
    return str(base.with_name(f"{base.stem}.{language}{base.suffix or '.mp4'}"))


def cmd_dubbing(client: Sonilo, args: argparse.Namespace) -> None:
    out = args.output if args.output is not None else "output.mp4"
    languages = None
    if args.languages is not None:
        languages = [code.strip() for code in args.languages.split(",") if code.strip()]
        if not languages:
            _fail("--languages needs at least one language code, e.g. --languages es,fr")
    result = client.dubbing.generate(
        video=args.video,
        video_url=args.video_url,
        languages=languages,
        timeout=args.timeout,
    )
    if not result.outputs:
        _fail("task succeeded but returned no dubbed videos")
    for language in sorted(result.outputs):
        path = result.save(language, _language_path(out, language))
        _wrote(path, path.stat().st_size)


def _identity(body: Any) -> Any:
    return body


def cmd_tasks_get(client: Sonilo, args: argparse.Namespace) -> None:
    _print_json(client.tasks.get(args.task_id, parser=_identity))


def cmd_tasks_wait(client: Sonilo, args: argparse.Namespace) -> None:
    deadline = time.monotonic() + args.timeout
    while True:
        body = client.tasks.get(args.task_id, parser=_identity)
        status = body.get("status") if isinstance(body, dict) else None
        if status == "succeeded":
            _print_json(body)
            return
        if status == "failed":
            _print_json(body)
            raise SystemExit(1)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _fail(f"timed out after {args.timeout}s waiting for task {args.task_id}")
        time.sleep(min(args.poll_interval, max(0.0, remaining)))


def _add_global(parser: argparse.ArgumentParser) -> None:
    # default=SUPPRESS (not None) is required here: argparse subparsers parse
    # into a *fresh* namespace and then copy every key back onto the parent
    # namespace (see cpython's _SubParsersAction.__call__), so a subparser
    # default of None would clobber an --api-key already set on the parent
    # parser (e.g. `sonilo --api-key X account`). With SUPPRESS, the key is
    # only ever set when the flag is actually given, so it never overwrites
    # a value set elsewhere with a default.
    parser.add_argument(
        "--api-key",
        dest="api_key",
        default=argparse.SUPPRESS,
        help="Overrides the SONILO_API_KEY environment variable.",
    )


def _add_video_source(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--video", default=None, help="Local video file to score.")
    group.add_argument("--video-url", dest="video_url", default=None,
                       help="Remote video URL to score.")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="sonilo", description="Command-line interface for the Sonilo API")
    parser.add_argument("--version", action="version", version=__version__)
    _add_global(parser)
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_account = sub.add_parser("account", help="Show plan limits and available services")
    _add_global(p_account)
    p_account.set_defaults(func=cmd_account)

    p_usage = sub.add_parser("usage", help="Show usage summary")
    _add_global(p_usage)
    p_usage.add_argument("--days", type=int, default=None, help="Look-back window in days.")
    p_usage.set_defaults(func=cmd_usage)

    p_t2m = sub.add_parser("text-to-music", help="Generate music from a text prompt")
    _add_global(p_t2m)
    p_t2m.add_argument("--prompt", required=True, help="What the music should sound like.")
    p_t2m.add_argument("--duration", type=int, required=True, help="Track length in seconds.")
    p_t2m.add_argument("--output", default=None, help="Where to save the audio.")
    p_t2m.add_argument("--format", choices=["m4a", "wav"], default="m4a",
                       help="Output container. wav forces async. Default: m4a")
    p_t2m.add_argument("--async", dest="use_async", action="store_true",
                       help="Submit and poll instead of streaming.")
    p_t2m.set_defaults(func=cmd_text_to_music)

    p_v2m = sub.add_parser("video-to-music", help="Generate music matched to a video")
    _add_global(p_v2m)
    _add_video_source(p_v2m)
    p_v2m.add_argument("--prompt", default=None, help="Optional creative direction.")
    p_v2m.add_argument("--output", default=None, help="Where to save the audio.")
    p_v2m.add_argument("--format", choices=["m4a", "wav"], default="m4a",
                       help="Output container. wav forces async.")
    p_v2m.add_argument("--isolate-vocals", dest="isolate_vocals", action="store_true",
                       help="Split out a vocals-only stem. Forces async.")
    p_v2m.add_argument("--preserve-speech", dest="preserve_speech", action="store_true",
                       help="Keep source speech in the mix. Forces async.")
    p_v2m.add_argument("--async", dest="use_async", action="store_true",
                       help="Submit and poll instead of streaming.")
    p_v2m.set_defaults(func=cmd_video_to_music)

    p_t2s = sub.add_parser("text-to-sfx", help="Generate a sound effect from a text prompt")
    _add_global(p_t2s)
    p_t2s.add_argument("--prompt", required=True, help="What the sound effect should be.")
    p_t2s.add_argument("--duration", type=int, required=True, help="Effect length in seconds.")
    p_t2s.add_argument("--output", default=None, help="Where to save the audio.")
    p_t2s.add_argument("--format", choices=_SFX_FORMATS, default="wav",
                       help="Output format. Default: wav")
    p_t2s.set_defaults(func=cmd_text_to_sfx)

    p_v2s = sub.add_parser("video-to-sfx", help="Generate a sound effect matched to a video")
    _add_global(p_v2s)
    _add_video_source(p_v2s)
    p_v2s.add_argument("--prompt", default=None, help="Optional creative direction.")
    p_v2s.add_argument("--output", default=None, help="Where to save the audio.")
    p_v2s.add_argument("--format", choices=_SFX_FORMATS, default="wav",
                       help="Output format. Default: wav")
    p_v2s.set_defaults(func=cmd_video_to_sfx)

    p_v2sd = sub.add_parser(
        "video-to-sound", help="Generate matched music+sfx audio for a video"
    )
    _add_global(p_v2sd)
    _add_video_source(p_v2sd)
    p_v2sd.add_argument("--music-prompt", dest="music_prompt", default=None,
                        help="Optional creative direction for the music bed.")
    p_v2sd.add_argument("--sfx-prompt", dest="sfx_prompt", default=None,
                        help="Optional creative direction for the sound effects.")
    p_v2sd.add_argument("--preserve-speech", dest="preserve_speech", action="store_true",
                        help="Keep source speech in the mix.")
    p_v2sd.add_argument("--no-ducking", dest="no_ducking", action="store_true",
                        help="Disable automatic ducking (on by default server-side).")
    p_v2sd.add_argument("--stem", dest="stems", action="append", choices=_SOUND_STEMS,
                        default=None, help="Also save an individual stem. Repeatable.")
    p_v2sd.add_argument("--output", default=None, help="Where to save the combined audio.")
    p_v2sd.set_defaults(func=cmd_video_to_sound)

    p_v2vsd = sub.add_parser(
        "video-to-video-sound", help="Generate matched music+sfx muxed into the source video"
    )
    _add_global(p_v2vsd)
    _add_video_source(p_v2vsd)
    p_v2vsd.add_argument("--music-prompt", dest="music_prompt", default=None,
                         help="Optional creative direction for the music bed.")
    p_v2vsd.add_argument("--sfx-prompt", dest="sfx_prompt", default=None,
                         help="Optional creative direction for the sound effects.")
    p_v2vsd.add_argument("--preserve-speech", dest="preserve_speech", action="store_true",
                         help="Keep source speech in the mix.")
    p_v2vsd.add_argument("--no-ducking", dest="no_ducking", action="store_true",
                         help="Disable automatic ducking (on by default server-side).")
    p_v2vsd.add_argument("--stem", dest="stems", action="append", choices=_SOUND_STEMS,
                         default=None, help="Also save an individual stem. Repeatable.")
    p_v2vsd.add_argument("--output", default=None, help="Where to save the combined video.")
    p_v2vsd.set_defaults(func=cmd_video_to_video_sound)

    p_dub = sub.add_parser("dubbing", help="Dub a video into other languages")
    _add_global(p_dub)
    _add_video_source(p_dub)
    p_dub.add_argument(
        "--languages", default=None,
        help="Comma-separated target languages. Default: zh_cn,es,fr. "
             "Supported: en, zh_cn, ja, ko, pt, es, de, fr, it, ru",
    )
    p_dub.add_argument(
        "--output", default=None,
        help="Filename template; one file is written per language with the code "
             "inserted before the extension (clip.mp4 -> clip.es.mp4). "
             "Default: output.mp4",
    )
    p_dub.add_argument(
        "--timeout", type=float, default=DUBBING_WAIT_TIMEOUT,
        help="Give up waiting after this many seconds. Default: 3600. A timed-out "
             "task is still running — resume it with `sonilo tasks wait <task-id>`.",
    )
    p_dub.set_defaults(func=cmd_dubbing)

    p_tasks = sub.add_parser("tasks", help="Inspect async tasks")
    _add_global(p_tasks)
    tsub = p_tasks.add_subparsers(dest="tasks_command", metavar="<get|wait>")

    p_get = tsub.add_parser("get", help="Fetch the current state of an async task")
    _add_global(p_get)
    p_get.add_argument("task_id", help="The task id to fetch.")
    p_get.set_defaults(func=cmd_tasks_get)

    p_wait = tsub.add_parser("wait", help="Poll an async task until it finishes")
    _add_global(p_wait)
    p_wait.add_argument("task_id", help="The task id to poll.")
    p_wait.add_argument("--poll-interval", dest="poll_interval", type=float, default=2.0,
                        help="Seconds between polls. Default: 2")
    p_wait.add_argument("--timeout", type=float, default=600.0,
                        help="Give up after this many seconds. Default: 600")
    p_wait.set_defaults(func=cmd_tasks_wait)

    return parser


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.error("missing command (try `sonilo --help`)")
    client = build_client(getattr(args, "api_key", None))
    try:
        func(client, args)
    except APIError as exc:
        # Show the API's error code alongside the message: it is what the
        # docs tell people to branch on, and "(trial_exhausted)" is the
        # difference between "add a payment method" and "retry later".
        _fail(f"{exc}{f' ({exc.code})' if exc.code else ''}")
    except SoniloError as exc:
        _fail(str(exc))
    finally:
        client.close()


if __name__ == "__main__":
    main()
