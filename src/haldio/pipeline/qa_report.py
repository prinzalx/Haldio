"""QA report: an HTML summary of editor verification for one job."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from haldio.pipeline.verify import Issue


@dataclass
class ChunkQA:
    """Verification outcome for one chunk."""

    chunk_id: str
    issues: list[Issue] = field(default_factory=list)
    needs_review: bool = False
    no_script: bool = False

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.is_error]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if not i.is_error]


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def render_qa_html(qa: list[ChunkQA], doc_meta: dict[str, Any]) -> str:
    """Render a compact, self-contained QA report."""
    total_errors = sum(len(c.errors) for c in qa)
    total_warnings = sum(len(c.warnings) for c in qa)
    review = [c for c in qa if c.needs_review]
    no_script = [c for c in qa if c.no_script]
    rows: list[str] = []
    for chunk in qa:
        badge = "ok"
        if chunk.errors or chunk.no_script:
            badge = "review"
        elif chunk.warnings:
            badge = "warn"
        detail = "; ".join(f"{i.rule}:{_esc(i.detail)[:60]}" for i in chunk.issues)
        if chunk.no_script:
            detail = f"kein Hörtext; {detail}"
        rows.append(
            f"<tr class='{badge}'><td>{chunk.chunk_id}</td>"
            f"<td>{badge}</td><td>{len(chunk.errors)}</td>"
            f"<td>{len(chunk.warnings)}</td><td>{_esc(detail)}</td></tr>"
        )
    title = _esc(str(doc_meta.get("title", "")))
    return (
        "<!doctype html><html lang='de'><head><meta charset='utf-8'>"
        f"<title>QA report {title}</title><style>"
        "body{font-family:system-ui;margin:24px}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccc;padding:4px 8px;font-size:14px}"
        "tr.review{background:#f8d7da}tr.warn{background:#fff3cd}</style></head><body>"
        f"<h1>QA report: {title}</h1>"
        f"<p>Chunks: {len(qa)} · errors: {total_errors} · warnings: {total_warnings} · "
        f"needs review: {len(review)} · ohne Hörtext: {len(no_script)}</p>"
        "<table><tr><th>chunk</th><th>state</th><th>errors</th><th>warnings</th>"
        "<th>detail</th></tr>" + "".join(rows) + "</table></body></html>"
    )


def write_qa_report(out_dir: Path, html: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "qa_report.html"
    path.write_text(html, encoding="utf-8")
    return path
