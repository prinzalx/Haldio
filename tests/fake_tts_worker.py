"""Fake TTS worker for backend protocol tests (no GPU, no torch).

Speaks each pending unit instantly: sleeps FAKE_SLEEP seconds per unit,
writes a stub file, prints one progress line. FAKE_WORKER_FAIL=1 makes the
second unit fail with an error line and exit code 1.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--units", required=True)
    parser.add_argument("--out-dir", required=True)
    args, _extra = parser.parse_known_args()

    units = [
        json.loads(line)
        for line in Path(args.units).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    out_dir = Path(args.out_dir)
    sleep = float(os.environ.get("FAKE_SLEEP", "0"))
    fail = os.environ.get("FAKE_WORKER_FAIL") == "1"
    pending = [unit for unit in units if not (out_dir / f"{unit['hash']}.wav").is_file()]
    done = len(units) - len(pending)
    if done:
        skipped = {"done": done, "total": len(units), "seconds": 0.0, "skipped": True}
        print(json.dumps(skipped), flush=True)
    for unit in pending:
        if sleep:
            time.sleep(sleep)
        if fail and unit is pending[-1]:
            print(json.dumps({"error": "fake failure"}), flush=True)
            return 1
        (out_dir / f"{unit['hash']}.wav").write_bytes(b"RIFFfake")
        done += 1
        print(json.dumps({"done": done, "total": len(units), "seconds": 0.25}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
