# Decision 0002 — PyMuPDF is AGPL, and that is acceptable

Date: 2026-11-20. Status: accepted.

## Context

Section 7 of the brief names PyMuPDF (plus `pymupdf4llm`) as the first extraction
implementation, and notes that PyMuPDF carries the AGPL license.

## Decision

Use PyMuPDF under AGPL and license Haldio itself **AGPL-3.0-only** (the user's choice).
Because our own code links an AGPL library, our code has to be copyleft anyway — so the
PyMuPDF license costs us nothing extra.

## Consequences

- Distribution of Haldio to other people keeps the source available.
- Docling stays the fallback for table extraction if PyMuPDF results are weak (M1).
- `pymupdf4llm` is MIT, so it adds no new obligation.
- If we ever want a permissive license, we must replace PyMuPDF, not just re-label it.
