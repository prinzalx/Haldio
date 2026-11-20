"""ONE-shot check for the qwencpp TTS engine (owner runs this, not the assistant).

Starts tts-server (loads the model on the GPU), lists voices, synthesizes
three German units and prints timing + RTF. Run with the LLM stopped:

    .venv\Scripts\python.exe check_qwencpp.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from haldio.config import load_config  # noqa: E402
from haldio.tts.base import TTSParams  # noqa: E402
from haldio.tts.qwencpp import QwenCppBackend  # noqa: E402

SAMPLES = [
    "Kapitel Eins. Die Umwandlung dieses Buches begann mit einer einfachen Idee.",
    "Der Sprachrechner läuft jetzt direkt auf der Grafikkarte und spricht deutlich schneller.",
    "Alle Pausen zwischen den Absätzen werden später beim Mastern gesetzt.",
]


def main() -> int:
    config = load_config(Path("config.yaml"))
    tts = config.tts
    print(f"backend={tts.backend} speaker={tts.speaker} port={tts.qwencpp_port}")
    for label, raw in (
        ("server", tts.qwencpp_server),
        ("model", tts.qwencpp_model),
        ("codec", tts.qwencpp_codec),
    ):
        path = Path(raw)
        if not path.is_file():
            print(f"MISSING {label}: {path}")
            return 1
        print(f"ok {label}: {path.name} ({path.stat().st_size:,} bytes)")

    backend = QwenCppBackend(tts)
    out_dir = Path(tempfile.gettempdir()) / "qwentts-check"
    out_dir.mkdir(exist_ok=True)
    start = time.monotonic()
    try:
        backend._ensure_server()
        print(f"server health ok in {time.monotonic() - start:.1f}s")
        voices = [str(v.id) for v in backend.list_voices()]
        print(f"voices ({len(voices)}): {', '.join(voices[:20])}")
        print(f"dylan listed: {'dylan' in [v.lower() for v in voices]}")
        items = [(text, out_dir / f"check{i}.wav") for i, text in enumerate(SAMPLES)]
        start = time.monotonic()
        durations = backend.synthesize_batch(items, "de", TTSParams(voice=tts.speaker))
        took = time.monotonic() - start
        audio = sum(durations)
        print(f"synthesized {len(items)} units in {took:.1f}s, audio {audio:.1f}s, RTF {took / max(audio, 0.001):.2f}")
        for path in items:
            print(f"  {path[1].name}: {path[1].stat().st_size:,} bytes")
    finally:
        backend.close()
    print("QWENCPP-CHECK-OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
