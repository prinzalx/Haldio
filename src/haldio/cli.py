"""Command line entry point. Subcommands are added by later milestones."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from haldio import __version__
from haldio.config import load_config
from haldio.pipeline.run import run_script


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hoerbuch", description="PDF to audiobook.")
    parser.add_argument("--version", action="version", version=f"hoerbuch {__version__}")
    parser.add_argument("--config", type=str, default=None, help="Path to config.yaml")
    sub = parser.add_subparsers(dest="command")
    inspect_parser = sub.add_parser("inspect", help="Print the structure of a PDF (M1).")
    inspect_parser.add_argument("pdf", help="Path to the PDF file")
    inspect_parser.add_argument("--json", action="store_true", help="Write document.json")
    # M2: script <pdf>, M3: run <pdf>, M4: serve
    for name, help_text in (
        ("script", "Build script.md and the QA report (M2)."),
        ("run", "Build the audiobook end to end (M3)."),
        ("serve", "Start the web interface (M4)."),
    ):
        sub.add_parser(name, help=help_text)
    return parser


def _inspect(args: argparse.Namespace) -> int:
    from haldio.extract import PyMuPDFExtractor
    from haldio.inspect_report import format_inspect
    from haldio.pipeline.ingest import ingest

    pdf_path = Path(args.pdf)
    if not pdf_path.is_file():
        print(f"error: file not found: {pdf_path}")
        return 2
    result = ingest(pdf_path)
    if not result.is_pdf:
        print(f"error: {result.error}")
        return 1
    if not result.has_text_layer:
        print(f"error: {result.error}")
        return 1
    document = PyMuPDFExtractor().extract(pdf_path)
    if args.json:
        import json

        out = pdf_path.with_name(f"{pdf_path.stem}.document.json")
        payload = json.dumps(document.to_dict(), ensure_ascii=False, indent=2)
        out.write_text(payload, encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(format_inspect(document))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(Path(args.config) if args.config else None)
    if args.command == "inspect":
        return _inspect(args)
    if args.command == "script":
        out_dir = Path(args.out) if args.out else Path(".")
        result = run_script(Path(args.pdf), config, out_dir)
        print(result.summary())
        return result.return_code
    if args.command is None:
        parser.print_help()
        return 0
    print(f"hoerbuch {args.command}: not implemented yet (config: {config.server.port})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
