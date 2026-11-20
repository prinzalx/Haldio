# 0005 — Ready2tts gate instead of unload hooks

Date: 2026-11-20
Status: accepted (Correction 2)

The machine has 31.6 GB shared memory. The big editor LLM and the Qwen3-TTS worker
do not fit in at the same time: loading the TTS worker a second time while the LLM
was loaded froze the whole system (power cycle needed). No `lms` command ends the
model process, so a `before_speak` hook cannot free the memory by itself.

Decision: conversion becomes a time-shifted process.

- Stages S1-S7 run in one go with the big LLM.
- When only the TTS is left, the job pauses in state `awaiting_tts` (the ready2tts
  pool). The job page asks: close all other local LLM, then confirm with OK.
- After the OK the worker runs S8-S9; many prepared jobs can be started together
  ("Alle TTS starten") or one by one.
- `tts.confirm_before_start` (default on) controls the gate. The hooks stay
  available as an optional mechanism.

Consequences: a prepared PDF survives days between the two halves; the user controls
when GPU memory is used; the CLI (`haldio run`) is not gated.
