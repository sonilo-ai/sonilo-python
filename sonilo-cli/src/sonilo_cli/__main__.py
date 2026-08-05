from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, NoReturn, Optional, Tuple
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


# --- --segments ----------------------------------------------------------
#
# `segments` is the only structured parameter the API takes — every other
# flag on this CLI is a scalar. The value follows the curl / gh / aws
# convention for anything that can get long: a leading `@` makes the value a
# *source* to read from rather than the value itself, and `@-` means stdin.
#
# Validation here is deliberately shape-only. The server owns the semantic
# rules (first segment at 0, minimum spacing, the label enum, item caps) and
# a copy of them in the CLI would drift the moment the backend changes, so a
# request that is the right shape but the wrong content is left to earn its
# own 422.

_STDIN = "@-"


class _SegmentShape(NamedTuple):
    """One command's segment contract, as used for validation and messages."""

    summary: str
    """What a correct segment looks like, shown verbatim in errors."""
    required: Tuple[Tuple[str, str], ...]
    optional: Tuple[Tuple[str, str], ...]
    foreign: Tuple[str, ...]
    """Fields that belong to the *other* shape — see _check_segment."""


MUSIC_SHAPE = _SegmentShape(
    summary="{start, prompt, label?}",
    required=(("start", "number"), ("prompt", "string")),
    optional=(("label", "string"),),
    foreign=("end",),
)

SFX_SHAPE = _SegmentShape(
    summary="{start, end, prompt}",
    required=(("start", "number"), ("end", "number"), ("prompt", "string")),
    optional=(),
    foreign=("label",),
)

# JSON booleans are not numbers, but bool is an int subclass in Python, so
# `isinstance(True, int)` would let `{"start": true}` through.
_TYPE_CHECKS = {
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "string": lambda v: isinstance(v, str),
}


def _describe(value: Any) -> str:
    """Name a JSON value the way the error messages talk about it. For an
    object this lists its keys, which is what makes a shape mix-up obvious."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, list):
        return "an empty array" if not value else "an array"
    if isinstance(value, dict):
        return f"an object with keys {', '.join(value)}" if value else "an object with no keys"
    return "an unsupported value"


def _read_segments_source(raw: str) -> Tuple[str, str]:
    """Resolve a raw --segments value to (text, source name for errors)."""
    if not raw.startswith("@"):
        return raw, "--segments"
    if raw == _STDIN:
        return sys.stdin.read(), "stdin"
    path = raw[1:]
    if not path:
        _fail("--segments @ needs a filename, e.g. --segments @segments.json (@- reads stdin)")
    try:
        return Path(path).read_text(), path
    except OSError as exc:
        _fail(f"could not read segments from {path}: {exc.strerror or exc}")


def _check_segment(item: Any, index: int, shape: _SegmentShape, command: str) -> None:
    expected = f"{command} segments take {shape.summary}"
    # Element-level problems name the offending index (0-based, matching the
    # Node CLI): an array is usually three or four items, and pointing at one
    # saves the reader counting. The shape mismatch below is the exception —
    # it is a whole-payload mistake, so it reads better without an index.
    if not isinstance(item, dict):
        _fail(f"{expected} — element {index} is not an object")
    # A key that belongs to the *other* shape is the tell for the one
    # predictable mistake here — SFX-shaped segments on a music command, or
    # the reverse — so it is reported instead of forwarded, even though it
    # would otherwise look like a required field is merely missing. Keys that
    # belong to neither shape pass through untouched, so a field added to the
    # API later needs no CLI release.
    if any(key in item for key in shape.foreign) or any(
        field not in item for field, _ in shape.required
    ):
        _fail(f"{expected} — got {_describe(item)}")
    for field, kind in shape.required + shape.optional:
        if field in item and not _TYPE_CHECKS[kind](item[field]):
            _fail(f'{expected} — "{field}" must be a {kind} (element {index})')


def parse_segments(
    raw: Optional[str], shape: _SegmentShape, command: str
) -> Optional[List[Dict[str, Any]]]:
    """Read, parse and shape-check one --segments value.

    `raw` is the flag as typed (inline JSON, `@file`, or `@-`). Returns None
    when the flag was not given, so the field stays out of the request
    entirely rather than being sent as an empty list.
    """
    if raw is None:
        return None
    text, source = _read_segments_source(raw)
    try:
        value = json.loads(text)
    except ValueError as exc:
        _fail(f"could not parse segments from {source}: {exc}")
    if not isinstance(value, list) or not value:
        _fail(
            f"{command} --segments must be a non-empty JSON array of "
            f"{shape.summary} objects — got {_describe(value)}"
        )
    for index, item in enumerate(value):
        _check_segment(item, index, shape, command)
    return value


def _ducking(args: argparse.Namespace) -> Optional[bool]:
    """Resolve --ducking / --no-ducking, or None to let the server default win.

    `ducking` used to be default-ON server-side, so the only direction worth
    expressing was turning it off and --no-ducking was the only flag. It is now
    default-OFF, which makes --ducking the useful one. --no-ducking is kept
    because dropping it would turn every script that passes it into a hard
    argparse error; it now sends the explicit False the server would have
    applied anyway.

    Passing both is a contradiction with no sensible winner, so it exits rather
    than silently picking one.
    """
    on = getattr(args, "ducking", False)
    off = getattr(args, "no_ducking", False)
    if on and off:
        raise SystemExit("pass at most one of --ducking or --no-ducking")
    if on:
        return True
    if off:
        return False
    return None


def _segments(args: argparse.Namespace) -> Optional[List[Dict[str, Any]]]:
    """parse_segments() for whichever subcommand is running."""
    return parse_segments(args.segments, args.segments_shape, args.command)


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


def _variant_path(out: str, index: int) -> str:
    """Turn one --output value into a per-variant path: `clip.mp4` + `1`
    becomes `clip.1.mp4`. Same transform as _stem_path/_language_path, used
    whenever --variants > 1 fans a single --output into one file per variant."""
    base = Path(out)
    return str(base.with_name(f"{base.stem}.{index}{base.suffix}"))


def _save_music_variants(result: Any, out: str) -> None:
    """Save every entry of an async music result's `audio` list. With
    --variants unset (or 1) this is a single file at `out`, byte-identical
    to the pre-variants behaviour; with --variants > 1 it fans out to
    `out.0.ext`, `out.1.ext`, etc."""
    count = len(result.audio or [])
    if count <= 1:
        path = result.save(out)
        _wrote(path, path.stat().st_size)
        return
    for index in range(count):
        path = result.save(_variant_path(out, index), index=index)
        _wrote(path, path.stat().st_size)


def cmd_text_to_music(client: Sonilo, args: argparse.Namespace) -> None:
    fmt = args.format
    multi = args.variants is not None and args.variants > 1
    use_async = args.use_async or fmt != "m4a" or multi
    out = _music_output(args, fmt)
    segments = _segments(args)
    if use_async:
        result = client.text_to_music.generate_async(
            prompt=args.prompt,
            duration=args.duration,
            segments=segments,
            output_format=fmt if fmt != "m4a" else None,
            variants_num=args.variants,
        )
        _save_music_variants(result, out)
    else:
        track = client.text_to_music.generate(
            prompt=args.prompt, duration=args.duration, segments=segments
        )
        path = track.save(out)
        _wrote(path, len(track.audio))


def cmd_video_to_music(client: Sonilo, args: argparse.Namespace) -> None:
    fmt = args.format
    multi = args.variants is not None and args.variants > 1
    use_async = (
        args.use_async or fmt != "m4a" or args.isolate_vocals or args.preserve_speech or multi
    )
    out = _music_output(args, fmt)
    segments = _segments(args)
    if use_async:
        result = client.video_to_music.generate_async(
            video=args.video,
            video_url=args.video_url,
            prompt=args.prompt,
            segments=segments,
            isolate_vocals=args.isolate_vocals or None,
            preserve_speech=args.preserve_speech or None,
            output_format=fmt if fmt != "m4a" else None,
            variants_num=args.variants,
        )
        _save_music_variants(result, out)
    else:
        track = client.video_to_music.generate(
            video=args.video, video_url=args.video_url, prompt=args.prompt,
            segments=segments,
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
        prompt=args.prompt, segments=_segments(args), audio_format=args.format,
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
    # video-to-video-sound only. Its parser is the only one that defines the
    # flag, and video_to_sound.generate() does not accept the keyword at all,
    # so it has to be omitted here rather than forwarded as None — the same
    # split the SDK enforces by never passing it from the audio resource.
    extra: Dict[str, Any] = {}
    if getattr(args, "keep_original_sound", False):
        extra["keep_original_sound"] = True
    result = resource.generate(
        video=args.video,
        video_url=args.video_url,
        music_prompt=args.music_prompt,
        sfx_prompt=args.sfx_prompt,
        segments=_segments(args),
        preserve_speech=True if args.preserve_speech else None,
        ducking=_ducking(args),
        variants_num=args.variants,
        **extra,
    )
    multi = args.variants is not None and args.variants > 1 and len(result.outputs) > 1
    if not multi:
        path = result.save(out)
        _wrote(path, path.stat().st_size)
        for stem in args.stems or []:
            stem_path = _stem_path(out, stem, getattr(result, stem, None))
            saved = result.save_stem(stem_path, which=stem)
            _wrote(saved, saved.stat().st_size)
        return
    for index, entry in enumerate(result.outputs):
        variant_out = _variant_path(out, index)
        path = result.save(variant_out, index=index)
        _wrote(path, path.stat().st_size)
        for stem in args.stems or []:
            stem_path = _stem_path(variant_out, stem, getattr(entry, stem, None))
            saved = result.save_stem(stem_path, which=stem, index=index)
            _wrote(saved, saved.stat().st_size)


def cmd_video_to_sound(client: Sonilo, args: argparse.Namespace) -> None:
    _run_sound(client, args, client.video_to_sound, "wav")


def cmd_video_to_video_sound(client: Sonilo, args: argparse.Namespace) -> None:
    _run_sound(client, args, client.video_to_video_sound, "mp4")


def _run_video(args: argparse.Namespace, resource: Any, **params: Any) -> None:
    """Run one of the video-returning endpoints and save the result.

    These return the source picture with the generated audio muxed in — no
    stems — so the default destination is an `.mp4`, matching
    video-to-video-sound. A `variants_num` in `params` fans out into one
    indexed file per variant when it is greater than 1; otherwise this stays
    the single-file save from before variants existed.
    """
    out = args.output if args.output is not None else "output.mp4"
    result = resource.generate(video=args.video, video_url=args.video_url, **params)
    variants = params.get("variants_num")
    if variants is not None and variants > 1 and len(result.videos) > 1:
        for index in range(len(result.videos)):
            path = result.save(_variant_path(out, index), index=index)
            _wrote(path, path.stat().st_size)
        return
    path = result.save(out)
    _wrote(path, path.stat().st_size)


def cmd_video_to_video_music(client: Sonilo, args: argparse.Namespace) -> None:
    _run_video(
        args,
        client.video_to_video_music,
        prompt=args.prompt,
        # Unset flags forward None, not False, so the server default stands —
        # same reasoning as --ducking on the sound commands. Both ducking and
        # keep_original_sound are default-OFF server-side, so each is only ever
        # sent to change the default, never to restate it.
        keep_original_sound=True if args.keep_original_sound else None,
        ducking=_ducking(args),
        preserve_speech=True if args.preserve_speech else None,
        isolate_vocals=True if args.isolate_vocals else None,
        variants_num=args.variants,
    )


def cmd_video_to_video_sfx(client: Sonilo, args: argparse.Namespace) -> None:
    _run_video(
        args,
        client.video_to_video_sfx,
        prompt=args.prompt,
        segments=_segments(args),
    )


# Matched to the dubbing backend's own ceiling: it polls its pipeline for up
# to 7200s (2 hours), so anything shorter abandons a job the user has already
# been charged for. The SDK's generic DEFAULT_WAIT_TIMEOUT of 600s is far too
# short for this endpoint. --timeout overrides.
DUBBING_WAIT_TIMEOUT = 7200.0


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


def _add_segments(parser: argparse.ArgumentParser, shape: _SegmentShape) -> None:
    parser.add_argument(
        "--segments", default=None,
        help=f"Timed segments, as a JSON array of {shape.summary} objects. "
             "Pass the JSON inline, @FILE to read it from a file, "
             "or @- to read it from stdin.",
    )
    # Carried on the namespace so the one shared reader knows which contract
    # to check the value against, and can name it when the check fails.
    parser.set_defaults(segments_shape=shape)


def _add_variants(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--variants", type=int, default=None,
        help="How many distinct variants to generate in one request, 1-10 "
             "(default 1). Cost scales linearly, and values above 1 are never "
             "covered by the free trial. Values above 1 force async and write "
             "one indexed file per variant (output.0.ext, output.1.ext, ...) "
             "instead of a single --output.",
    )


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
    _add_segments(p_t2m, MUSIC_SHAPE)
    p_t2m.add_argument("--output", default=None, help="Where to save the audio.")
    p_t2m.add_argument("--format", choices=["m4a", "wav", "mp3"], default="m4a",
                       help="Output container. Anything but m4a forces async. mp3 is 320 kbps. Default: m4a")
    p_t2m.add_argument("--async", dest="use_async", action="store_true",
                       help="Submit and poll instead of streaming.")
    _add_variants(p_t2m)
    p_t2m.set_defaults(func=cmd_text_to_music)

    p_v2m = sub.add_parser("video-to-music", help="Generate music matched to a video")
    _add_global(p_v2m)
    _add_video_source(p_v2m)
    p_v2m.add_argument("--prompt", default=None, help="Optional creative direction.")
    _add_segments(p_v2m, MUSIC_SHAPE)
    p_v2m.add_argument("--output", default=None, help="Where to save the audio.")
    p_v2m.add_argument("--format", choices=["m4a", "wav", "mp3"], default="m4a",
                       help="Output container. Anything but m4a forces async. mp3 is 320 kbps.")
    p_v2m.add_argument("--preserve-speech", dest="preserve_speech", action="store_true",
                       help="Keep source speech in the mix. Forces async.")
    # The API ORs isolate_vocals into preserve_speech (video_to_music.py:
    # `isolate_vocals = bool(preserve_speech) or bool(isolate_vocals)`), so
    # the two flags are one feature under two names, not two behaviours.
    # isolate_vocals is the legacy name kept for existing callers.
    p_v2m.add_argument("--isolate-vocals", dest="isolate_vocals", action="store_true",
                       help="Legacy alias for --preserve-speech. Forces async.")
    p_v2m.add_argument("--async", dest="use_async", action="store_true",
                       help="Submit and poll instead of streaming.")
    _add_variants(p_v2m)
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
    _add_segments(p_v2s, SFX_SHAPE)
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
    _add_segments(p_v2sd, SFX_SHAPE)
    p_v2sd.add_argument("--preserve-speech", dest="preserve_speech", action="store_true",
                        help="Keep source speech in the mix.")
    p_v2sd.add_argument("--ducking", dest="ducking", action="store_true",
                        help="Bring the source video's own speech into the mix and duck "
                             "the generated bed under it. Off by default, so by default "
                             "the result is the generated music and effects alone and "
                             "there is no music_processed stem.")
    p_v2sd.add_argument("--no-ducking", dest="no_ducking", action="store_true",
                        help="Explicit opt-out. Same as the default; kept so existing "
                             "scripts keep working.")
    p_v2sd.add_argument("--stem", dest="stems", action="append", choices=_SOUND_STEMS,
                        default=None, help="Also save an individual stem. Repeatable.")
    p_v2sd.add_argument("--output", default=None, help="Where to save the combined audio.")
    _add_variants(p_v2sd)
    p_v2sd.set_defaults(func=cmd_video_to_sound)

    p_v2vm = sub.add_parser(
        "video-to-video-music", help="Generate music muxed into the source video"
    )
    _add_global(p_v2vm)
    _add_video_source(p_v2vm)
    p_v2vm.add_argument("--prompt", default=None, help="Optional creative direction.")
    p_v2vm.add_argument("--keep-original-sound", dest="keep_original_sound",
                        action="store_true",
                        help="Keep the source video's whole original audio, with the "
                             "generated music under it. Off by default, so by default "
                             "the result's audio is the generated music alone. "
                             "Supersedes --preserve-speech.")
    p_v2vm.add_argument("--ducking", dest="ducking", action="store_true",
                        help="Duck the music under the voice instead of mixing it in at "
                             "a static level. No effect without --keep-original-sound "
                             "or --preserve-speech.")
    p_v2vm.add_argument("--no-ducking", dest="no_ducking", action="store_true",
                        help="Explicit opt-out. Same as the default; kept so existing "
                             "scripts keep working.")
    p_v2vm.add_argument("--preserve-speech", dest="preserve_speech", action="store_true",
                        help="Keep only the source's isolated speech in the mix.")
    # Same aliasing as video-to-music, and here the endpoint collapses the two
    # into a single boolean before it reaches the model (video_to_video.py:
    # `keep_speech = bool(preserve_speech) or bool(isolate_vocals)`), with no
    # vocals stem in the result — the output is one muxed video.
    p_v2vm.add_argument("--isolate-vocals", dest="isolate_vocals", action="store_true",
                        help="Legacy alias for --preserve-speech; no separate stem.")
    p_v2vm.add_argument("--output", default=None, help="Where to save the scored video.")
    _add_variants(p_v2vm)
    p_v2vm.set_defaults(func=cmd_video_to_video_music)

    p_v2vfx = sub.add_parser(
        "video-to-video-sfx", help="Generate sound effects muxed into the source video"
    )
    _add_global(p_v2vfx)
    _add_video_source(p_v2vfx)
    p_v2vfx.add_argument("--prompt", default=None, help="Optional creative direction.")
    _add_segments(p_v2vfx, SFX_SHAPE)
    p_v2vfx.add_argument("--output", default=None, help="Where to save the scored video.")
    p_v2vfx.set_defaults(func=cmd_video_to_video_sfx)

    p_v2vsd = sub.add_parser(
        "video-to-video-sound", help="Generate matched music+sfx muxed into the source video"
    )
    _add_global(p_v2vsd)
    _add_video_source(p_v2vsd)
    p_v2vsd.add_argument("--music-prompt", dest="music_prompt", default=None,
                         help="Optional creative direction for the music bed.")
    p_v2vsd.add_argument("--sfx-prompt", dest="sfx_prompt", default=None,
                         help="Optional creative direction for the sound effects.")
    _add_segments(p_v2vsd, SFX_SHAPE)
    p_v2vsd.add_argument("--keep-original-sound", dest="keep_original_sound",
                         action="store_true",
                         help="Keep the source video's whole original audio, with the "
                              "generated music and effects under it. Off by default, so "
                              "by default the result's audio is the generated audio "
                              "alone and there is no music_processed stem. Supersedes "
                              "--preserve-speech. This command only.")
    p_v2vsd.add_argument("--preserve-speech", dest="preserve_speech", action="store_true",
                         help="Keep only the source's isolated speech in the mix.")
    p_v2vsd.add_argument("--ducking", dest="ducking", action="store_true",
                         help="Duck the generated bed under the voice instead of mixing "
                              "it in at a static level. No effect without "
                              "--keep-original-sound or --preserve-speech.")
    p_v2vsd.add_argument("--no-ducking", dest="no_ducking", action="store_true",
                         help="Explicit opt-out. Same as the default; kept so existing "
                              "scripts keep working.")
    p_v2vsd.add_argument("--stem", dest="stems", action="append", choices=_SOUND_STEMS,
                         default=None, help="Also save an individual stem. Repeatable.")
    p_v2vsd.add_argument("--output", default=None, help="Where to save the combined video.")
    _add_variants(p_v2vsd)
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
        help="Give up waiting after this many seconds. Default: 7200, matching the "
             "backend's own ceiling for a dubbing job. A timed-out "
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
