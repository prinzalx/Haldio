# Decision 0001 — new project, not a fork

Date: 2026-11-20. Status: accepted (brief section 6, default decision).

## Context

ebook2audiobook supports many e-book formats and many TTS engines. Our value is a
PDF-layout-aware extraction plus an editorial LLM stage in front of the TTS.

## Decision

Start a new project. Clone the reference repo read-only to `../_reference/ebook2audiobook`
(not a submodule) and study it for concepts, not code.

## Consequences

- We own the architecture: file-based stages that can re-run alone.
- We can pick dependencies freely, including PyMuPDF (AGPL).
- If the study shows strong reasons to fork, we stop and ask the user. See
  `docs/reference-notes.md` for the study result.
