"""Synthetic PDFs for tests (reportlab). Real PDFs are never committed."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = A4
HEADER = "Handbuch der Technik"


def _draw_table(c: canvas.Canvas, x: float, y: float) -> None:
    """A 3 x 3 table with a real grid so PyMuPDF can detect it."""
    col_w, row_h = 130.0, 16.0
    rows = [
        ["Betriebsart", "Max. Strom", "Spannung"],
        ["Standby", "0,5 mA", "3,3 V"],
        ["Aktiv", "120 mA", "3,3 V"],
    ]
    for r, row in enumerate(rows):
        for col, text in enumerate(row):
            c.setFont("Helvetica-Bold" if r == 0 else "Helvetica", 9)
            c.drawString(x + 4 + col * col_w, y - r * row_h - 11, text)
    for r in range(len(rows) + 1):
        c.line(x, y - r * row_h, x + col_w * len(rows[0]), y - r * row_h)
    for col in range(len(rows[0]) + 1):
        c.line(x + col * col_w, y, x + col * col_w, y - len(rows) * row_h)


def _chrome(c: canvas.Canvas, page_no: int) -> None:
    """Running header and page number, drawn on every page."""
    c.setFont("Helvetica", 9)
    c.drawString(50, 810, HEADER)
    c.drawString(50, 30, str(page_no))


def make_test_pdf(path: Path) -> Path:
    """Three pages: headers/footers, headings, list, table, footnote, formula, references."""
    c = canvas.Canvas(str(path), pagesize=A4)
    body_y = 770.0

    # --- page 1 -------------------------------------------------------
    _chrome(c, 1)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, body_y, "Kapitel Eins")
    c.setFont("Helvetica", 10)
    c.drawString(50, body_y - 24, "Dies ist die Einleitung in das erste Kapitel. Sie erklaert")
    c.drawString(50, body_y - 36, "die Grundidee der Verwen-")
    c.drawString(50, body_y - 48, "dung von Grundstoffen.")
    c.drawString(50, body_y - 72, "Vor dem Start pruefen Sie:")
    c.drawString(50, body_y - 84, "\u2022 die Versorgungsspannung")
    c.drawString(50, body_y - 96, "\u2022 die Kabelverbindung")
    c.drawString(50, body_y - 108, "\u2022 den Zustand der Sicherung")
    c.drawString(50, body_y - 132, "Die Grenzwerte stehen in Tabelle 2, siehe Abschnitt 4.2.")
    _draw_table(c, 50, body_y - 152)
    c.showPage()

    # --- page 2 (two columns) ----------------------------------------
    _chrome(c, 2)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, body_y, "Kapitel Zwei")
    c.setFont("Helvetica", 10)
    left = [
        "Der linke Spaltentext beschreibt die Messung der",
        "Spannung an den Klemmen. Dabei gilt die Regel aus",
        "Abschnitt 4.2 mit den bekannten Grenzen.",
    ]
    right = [
        "Der rechte Spaltentext nennt die Folgen. Siehe",
        "Tabelle 2 fuer die Werte und Abbildung 3 zusaetzlich.",
        "Die Leistung folgt aus P = U · I.",
    ]
    for index, line in enumerate(left):
        c.drawString(50, body_y - 24 - index * 12, line)
    for index, line in enumerate(right):
        c.drawString(320, body_y - 24 - index * 12, line)
    c.setFont("Helvetica", 7.5)
    c.drawString(50, 120, "1) Quelle: interne Messung, 2026.")
    c.showPage()

    # --- page 3 -------------------------------------------------------
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, body_y, "Anhang A")
    c.setFont("Helvetica", 10)
    c.drawString(50, body_y - 24, "Ein kurzer Schlussabschnitt auf der letzten Seite dieses")
    c.drawString(50, body_y - 36, "Dokuments mit der Zahl 12 und 3,5 Prozent Anteil.")
    c.showPage()
    c.save()
    return path
