from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, List, NoReturn, Optional

from sonilo import Sonilo
from sonilo.errors import SoniloError

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
    return Sonilo(api_key=key)


def cmd_account(client: Sonilo, args: argparse.Namespace) -> None:
    _print_json(client.account.services())


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
    except SoniloError as exc:
        _fail(str(exc))
    finally:
        client.close()


if __name__ == "__main__":
    main()
