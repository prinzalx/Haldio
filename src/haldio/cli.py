"""Command line entry point. Subcommands are added by later milestones."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from haldio import __version__
from haldio.config import Config, load_config
from haldio.pipeline.run import run_book, run_script


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="haldio", description="PDF to audiobook.")
    parser.add_argument("--version", action="version", version=f"haldio {__version__}")
    parser.add_argument("--config", type=str, default=None, help="Path to config.yaml")
    sub = parser.add_subparsers(dest="command")
    inspect_parser = sub.add_parser("inspect", help="Print the structure of a PDF (M1).")
    inspect_parser.add_argument("pdf", help="Path to the PDF file")
    inspect_parser.add_argument("--json", action="store_true", help="Write document.json")
    # M4: serve
    run_parser = sub.add_parser("run", help="Build the audiobook end to end (M3).")
    run_parser.add_argument("pdf", help="Path to the PDF file")
    run_parser.add_argument("-o", "--out", default=None, help="Output directory")
    serve_parser = sub.add_parser("serve", help="Start the web interface (M4).")
    serve_parser.add_argument("--host", default=None, help="Bind address (default: config)")
    serve_parser.add_argument("--port", type=int, default=None, help="Port (default: config)")
    script_parser = sub.add_parser("script", help="Build script.md and the QA report (M2).")
    script_parser.add_argument("pdf", help="Path to the PDF file")
    script_parser.add_argument("-o", "--out", default=None, help="Output directory")
    pull_parser = sub.add_parser("tts-pull", help="Download the Qwen3-TTS weights once.")
    pull_parser.add_argument("--model-id", default=None, help="Override tts.model_id")
    check_parser = sub.add_parser("tts-check", help="Load the TTS model and write a test WAV.")
    check_parser.add_argument("--text", default=None, help="Sentence to speak")
    check_parser.add_argument("-o", "--out", default="tts-check.wav", help="Output WAV path")
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


def _tts_pull(config: Config, model_id: str | None) -> int:
    from haldio.tts.qwen_local import QwenLocalBackend

    backend = QwenLocalBackend(config.tts)
    source = model_id or backend.resolve_source()
    name = source.split("/")[-1]
    dest = Path(config.tts.model_path) if config.tts.model_path else Path("models") / name
    try:
        backend.pull(source, dest)
    except RuntimeError as error:
        print(f"error: {error}")
        return 1
    return 0


CHECK_TEXT = "Guten Tag. Dies ist ein Test der Sprachausgabe mit der Zahl 3,5 Prozent."


def _tts_check(config: Config, text: str | None, out: Path) -> int:
    from haldio.tts import create_backend
    from haldio.tts.qwen_local import QwenLocalBackend

    backend = create_backend(config.tts)
    sentence = text if text is not None else CHECK_TEXT
    try:
        if isinstance(backend, QwenLocalBackend):
            result = backend.check(sentence, out)
            voices = ", ".join(str(s) for s in result["speakers"][:10])
            print(f"speakers: {voices or '(none)'}")
            print(f"languages: {', '.join(str(s) for s in result['languages'][:10])}")
            print(f"wrote {result['wav'] or out}")
        else:
            from haldio.tts import TTSParams

            audio = backend.synthesize(sentence, config.tts.language, TTSParams())
            out.write_bytes(audio.data)
            print(f"mock ok: wrote {out} ({audio.duration_seconds:.1f}s)")
    except RuntimeError as error:
        print(f"error: {error}")
        return 1
    finally:
        backend.close()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(Path(args.config) if args.config else None)
    if args.command == "inspect":
        return _inspect(args)
    if args.command == "tts-pull":
        return _tts_pull(config, args.model_id)
    if args.command == "tts-check":
        return _tts_check(config, args.text, Path(args.out))
    if args.command == "script":
        out_dir = Path(args.out) if args.out else Path(".")
        result = run_script(Path(args.pdf), config, out_dir)
        print(result.summary())
        return result.return_code
    if args.command == "run":
        out_dir = Path(args.out) if args.out else Path("data/jobs/run")
        result = run_book(Path(args.pdf), config, out_dir)
        print(result.summary())
        return result.return_code
    if args.command == "serve":
        import logging
        import sys

        import uvicorn

        from haldio.settings_store import effective_config
        from haldio.web.app import create_app

        # job log lines also appear on the serve console (same text)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        worker_log = logging.getLogger("haldio.worker")
        worker_log.setLevel(logging.INFO)
        worker_log.addHandler(handler)
        # CLI flags win over the settings page, which wins over config.yaml
        eff = effective_config(config)
        host = args.host or eff.server.host
        port = args.port if args.port is not None else eff.server.port
        uvicorn.run(create_app(config), host=host, port=port)
        return 0
    if args.command is None:
        parser.print_help()
        return 0
    print(f"haldio {args.command}: not implemented yet (config: {config.server.port})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
