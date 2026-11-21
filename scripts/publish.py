"""Publish the user-facing files to the public GitHub repo (remote `public`).

The local repo tracks everything (development notes included) and is backed
up to the private repo `haldio_dev` (remote `origin`). This script sends only
the files an end user needs to the public repo: it checks the tree, runs lint
and tests, scans for secrets, shows the file list and asks before pushing.

Usage:
    uv run python scripts/publish.py            # full checks + prompt
    uv run python scripts/publish.py --yes      # no prompt (for agents)
    uv run python scripts/publish.py --fast     # skip lint/tests (not advised)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Only paths below are published; everything else stays in haldio_dev.
PUBLIC_PREFIXES = (
    "src/",
    "prompts/",
    "docs/configuration.md",
    "docs/screenshots/",
    ".gitignore",
    "LICENSE",
    "README.md",
    "pyproject.toml",
    "uv.lock",
    "config.example.yaml",
    "pronunciations.yaml",
)

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".txt",
    ".html",
    ".css",
    ".js",
    ".json",
    ".lock",
}

SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\b.{0,15}[A-Za-z0-9+/=_-]{20,}"),
)


def run(*args: str, env: dict[str, str] | None = None) -> str:
    """Run a command inside the repo and return its stdout (abort on error)."""
    proc = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.exit(f"publish: command failed: {' '.join(args)}\n{proc.stderr.strip()}")
    return proc.stdout


def git_files() -> list[str]:
    out = run("git", "ls-files")
    return sorted(line for line in out.splitlines() if line)


def is_public(path: str) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p) for p in PUBLIC_PREFIXES)


def check_clean_tree() -> None:
    out = run("git", "status", "--porcelain")
    dirty = [
        line
        for line in out.splitlines()
        if line.strip() and not line.rstrip().endswith(".qwen/tmp/")
    ]
    if dirty:
        sys.exit(
            "publish: working tree is not clean (commit first):\n"
            + "\n".join(dirty)
        )


def check_tools() -> None:
    steps = (
        ("ruff check", [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"]),
        ("ruff format", [sys.executable, "-m", "ruff", "format", "--check", "src", "tests"]),
        ("pytest", [sys.executable, "-m", "pytest", "-q", "-m", "not live"]),
    )
    for name, cmd in steps:
        print(f"publish: {name} ...")
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if proc.returncode != 0:
            sys.exit(f"publish: {name} failed:\n{proc.stdout}\n{proc.stderr}")


def scan_secrets(files: list[str]) -> list[str]:
    hits: list[str] = []
    for rel in files:
        path = ROOT / rel
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:  # unreadable file: flag it instead of stopping
            hits.append(f"{rel}: unreadable ({exc.strerror})")
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if any(p.search(line) for p in SECRET_PATTERNS):
                hits.append(f"{rel}:{number}: {line.strip()[:90]}")
    return hits


def build_tree(files: list[str]) -> str:
    """Build a git tree object with exactly `files`, without touching the work tree."""
    fd, index = tempfile.mkstemp(dir=ROOT / ".git", suffix=".idx")
    os.close(fd)
    env = dict(os.environ, GIT_INDEX_FILE=index)
    try:
        run("git", "read-tree", "--empty", env=env)
        for rel in files:
            blob = run("git", "hash-object", "-w", "--", rel, env=env).strip()
            run("git", "update-index", "--add", "--cacheinfo", f"100644,{blob},{rel}", env=env)
        return run("git", "write-tree", env=env).strip()
    finally:
        os.unlink(index)


def main(argv: list[str]) -> int:
    assume_yes = "--yes" in argv
    fast = "--fast" in argv

    check_clean_tree()
    if not fast:
        check_tools()

    tracked = git_files()
    include = [p for p in tracked if is_public(p)]
    local_only = [p for p in tracked if not is_public(p)]

    print(f"publish: {len(include)} files go to the public repo:")
    for rel in include:
        print(f"  + {rel}")
    print("stays local (private backup only):")
    for rel in local_only:
        print(f"  - {rel}")

    hits = scan_secrets(include)
    if hits:
        print("secret scan (check by eye):")
        for line in hits:
            print(f"  ! {line}")

    if not assume_yes:
        answer = input("Veröffentlichen? [j/N] ").strip().lower()
        if answer not in ("j", "ja", "y"):
            print("publish: cancelled")
            return 0

    run("git", "fetch", "public", "main")
    parent = run("git", "rev-parse", "refs/remotes/public/main").strip()
    tree = build_tree(include)
    parent_tree = run("git", "rev-parse", f"{parent}^{{tree}}").strip()
    if tree == parent_tree:
        print("publish: public repo already has this state - nothing to do")
        return 0

    message = f"release: publish {date.today().isoformat()} from dev"
    commit = run("git", "commit-tree", tree, "-p", parent, "-m", message).strip()
    run("git", "push", "public", f"{commit}:refs/heads/main")
    print(f"publish: pushed {commit[:7]} to public/main")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
