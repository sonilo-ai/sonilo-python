from __future__ import annotations

import argparse
from typing import List, Optional

from sonilo_cli import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sonilo", add_help=True)
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    parser.parse_args(argv)


if __name__ == "__main__":
    main()
