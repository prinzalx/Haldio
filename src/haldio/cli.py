"""Command line entry point. Subcommands are added by later milestones."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from haldio import __version__
from haldio.config import load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hoerbuch", description="PDF to audiobook.")
    parser.add_argument("--version", action="version", version=f"hoerbuch {__version__}")
    parser.add_argument("--config", type=str, default=None, help="Path to config.yaml")
    sub = parser.add_subparsers(dest="command")
    # M1: inspect <pdf>, M2: script <pdf>, M3: run <pdf>, M4: serve
    for name, help_text in (
        ("inspect", "Print the structure of a PDF (M1)."),
        ("script", "Build script.md and the QA report (M2)."),
        ("run", "Build the audiobook end to end (M3)."),
        ("serve", "Start the web interface (M4)."),
    ):
        sub.add_parser(name, help=help_text)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(Path(args.config) if args.config else None)
    if args.command is None:
        parser.print_help()
        return 0
    print(f"hoerbuch {args.command}: not implemented yet (config: {config.server.port})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
