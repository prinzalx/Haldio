# Decision 0003 — reference repo license: Apache-2.0, borrow concepts only

Date: 2026-11-20. Status: accepted.

## Context

The brief asks us to read the LICENSE of ebook2audiobook before copying anything, and to
record the result.

## Findings

- ebook2audiobook is **Apache-2.0** (its own `LICENSE` file).
- Apache-2.0 permits copying into our AGPL project, but keeps obligations: keep the
  copyright notice and the attribution, and state changes for the files we copy.
- The study in `docs/reference-notes.md` found nothing we need to copy as code. The
  useful parts are concepts: the hard→soft→space→cut fallback for over-long TTS units,
  expanding abbreviations before splitting, registry-by-subclass for TTS backends,
  the ffmpeg concat demuxer plus `FFMETADATA1` chapter files, cache-per-unit with a
  resume pointer.

## Decision

Borrow concepts, copy no code. If we later copy a code block, we add this notice next to
it and keep it Apache-2.0:

> Portions from ebook2audiobook (https://github.com/DrewThomasson/ebook2audiobook),
> Copyright (c) the ebook2audiobook authors, used under Apache-2.0.

## Consequences

- No `NOTICE` file needed in the first version; add one if real copies appear.
- Fork verdict: the reference has no PDF layout analysis and no editorial LLM stage, so
  the default decision (new project, not a fork) stands.
