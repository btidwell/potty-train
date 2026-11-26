"""Paper data sheet as a PDF.

The columns, circled codes, and footnotes match the training log. A row's
interval is the one in effect for that sit. The comment says when the next
row's interval changes, which is how the practice sheet is marked.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from fpdf import FPDF

from potty_train.rules import recompute_entries

PAGE_W = 612.0
PAGE_H = 792.0
MARGIN_X = 32.0
HEADER_H = 32.0
FOOT_H = 58.0
FOOT_GAP = 8.0
MARGIN_BOTTOM = 28.0
ROW_MIN = 22.0
PEN = (13, 46, 140)
COL_FRACTIONS = (0.125, 0.105, 0.115, 0.235, 0.145, 0.275)


def render_log_pdf(entries: list[dict[str, Any]], settings: dict[str, Any]) -> bytes:
    ordered = recompute_entries(deepcopy(entries), settings)
    rows = [_row(entry) for entry in ordered]
    name = str(settings.get("child_name") or "").strip()
    step = int(settings["step_minutes"])
    pdf = FPDF(unit="pt", format="Letter")
    pdf.set_auto_page_break(False)
    pdf.set_margin(0)
    _draw(pdf, rows, step, name)
    return bytes(pdf.output())


def paper_comment(entry: dict[str, Any]) -> str:
    note = str(entry.get("decision_note") or "")
    if (
        not note
        and entry.get("decision") == "same"
        and int(entry.get("interval_minutes") or 0) > 0
        and not (entry.get("accident_wet") or entry.get("accident_soiled"))
        and int(entry.get("dry_streak_after") or 0) == 3
        and not entry.get("dry_streak_has_void")
    ):
        note = "keep interval same"
    comment = str(entry.get("comment") or "").strip()
    if note and comment:
        return f"{note} - {comment}"
    return note or comment


def _row(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": _short_date(str(entry["date"])),
        "time": str(entry["time"])[:5],
        "interval": str(int(entry["interval_minutes"])),
        "bm": bool(entry.get("toilet_bm")),
        "urine": bool(entry.get("toilet_urine")),
        "soiled": bool(entry.get("accident_soiled")),
        "wet": bool(entry.get("accident_wet")),
        "comment": paper_comment(entry),
    }


def _short_date(iso: str) -> str:
    year, month, day = iso.split("-")
    return f"{int(month):02d}-{int(day):02d}-{year[2:]}"


def _pdf_text(value: str) -> str:
    cleaned = (
        value.replace("\u2014", "-")
        .replace("\u2013", "-")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u00a0", " ")
    )
    return cleaned.encode("latin-1", "replace").decode("latin-1")


def _table_top(has_name: bool) -> float:
    return 50.0 if has_name else 36.0


def _rows_per_page(has_name: bool) -> tuple[float, float]:
    body = _table_bottom() - _table_top(has_name) - HEADER_H
    count = max(1, int(body // ROW_MIN))
    return count, body / count


def _table_bottom() -> float:
    return PAGE_H - MARGIN_BOTTOM - FOOT_H - FOOT_GAP


def _columns(top: float) -> list[tuple[float, float]]:
    width = PAGE_W - 2 * MARGIN_X
    columns = []
    x = MARGIN_X
    for fraction in COL_FRACTIONS:
        column_width = width * fraction
        columns.append((x, column_width))
        x += column_width
    # Keep the last edge on the table border.
    columns[-1] = (columns[-1][0], MARGIN_X + width - columns[-1][0])
    return columns


def _draw(pdf: FPDF, rows: list[dict[str, Any]], step: int, name: str) -> None:
    per_page, row_h = _rows_per_page(bool(name))
    per_page = int(per_page)
    pages: list[list[dict[str, Any] | None]] = []
    if not rows:
        pages.append([None] * per_page)
    else:
        for start in range(0, len(rows), per_page):
            chunk: list[dict[str, Any] | None] = list(rows[start : start + per_page])
            if len(chunk) < per_page:
                chunk.extend([None] * (per_page - len(chunk)))
            pages.append(chunk)
    for number, chunk in enumerate(pages, start=1):
        pdf.add_page()
        _draw_page(pdf, chunk, row_h, step, name, number, len(pages))


def _draw_page(
    pdf: FPDF,
    rows: list[dict[str, Any] | None],
    row_h: float,
    step: int,
    name: str,
    page_no: int,
    page_count: int,
) -> None:
    top = _table_top(bool(name))
    bottom = _table_bottom()
    columns = _columns(top)
    table_w = PAGE_W - 2 * MARGIN_X
    if name:
        _centered_text(pdf, MARGIN_X, 22, table_w, 16, [_pdf_text(name)], "B", 14, PEN, left=True)

    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.8)
    pdf.rect(MARGIN_X, top, table_w, bottom - top)
    header_bottom = top + HEADER_H
    pdf.line(MARGIN_X, header_bottom, MARGIN_X + table_w, header_bottom)
    for x, _width in columns[1:]:
        pdf.line(x, top, x, bottom)
    for index in range(1, len(rows)):
        y = header_bottom + index * row_h
        pdf.line(MARGIN_X, y, MARGIN_X + table_w, y)

    headers = [
        ["Date"],
        ["Time"],
        ["Off-potty", "Interval"],
        ["TOILET VOIDS", "BM or Urine"],
        ["ACCIDENT", "Soiled or Wet"],
        ["COMMENTS"],
    ]
    for (x, width), lines in zip(columns, headers):
        _centered_text(pdf, x, top, width, HEADER_H, lines, "B", 8 if len(lines) > 1 else 9, (0, 0, 0))

    code_size = 8
    for index, row in enumerate(rows):
        row_top = header_bottom + index * row_h
        baseline = row_top + (row_h + code_size * 0.72) / 2
        void_x, void_w = columns[3]
        acc_x, acc_w = columns[4]
        void_centers = [void_x + void_w * 0.20, void_x + void_w * 0.52, void_x + void_w * 0.82]
        acc_centers = [acc_x + acc_w * 0.36, acc_x + acc_w * 0.66]
        no_void = bool(row) and not row["bm"] and not row["urine"]
        _token(pdf, "Y(BM)", void_centers[0], baseline, code_size, bool(row and row["bm"]))
        _token(pdf, "Y(U)", void_centers[1], baseline, code_size, bool(row and row["urine"]))
        _token(pdf, "N", void_centers[2], baseline, code_size, no_void)
        _token(pdf, "S", acc_centers[0], baseline, code_size, bool(row and row["soiled"]))
        _token(pdf, "W", acc_centers[1], baseline, code_size, bool(row and row["wet"]))
        if not row:
            continue
        for column, key in ((0, "date"), (1, "time"), (2, "interval")):
            x, width = columns[column]
            _centered_text(pdf, x, row_top, width, row_h, [row[key]], "", 10, PEN)
        if row["comment"]:
            _comment(pdf, columns[5][0], columns[5][1], baseline, row["comment"])

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(MARGIN_X, bottom + FOOT_GAP)
    pdf.multi_cell(
        table_w,
        10,
        (
            f"*If he stays dry for 3 consecutive intervals AND voids on the toilet for 1 of those intervals, "
            f"increase off-potty interval by {step} minutes.\n"
            f"*If he has an accident in 2 consecutive intervals, decrease off-potty interval by {step} minutes.\n\n"
            "Good luck :)"
        ),
    )
    if page_count > 1:
        label = f"{page_no} / {page_count}"
        pdf.set_font("Helvetica", "", 8)
        width = pdf.get_string_width(label)
        pdf.text(PAGE_W - MARGIN_X - width, PAGE_H - 16, label)


def _centered_text(
    pdf: FPDF,
    x: float,
    y: float,
    width: float,
    height: float,
    lines: list[str],
    style: str,
    size: float,
    color: tuple[int, int, int],
    left: bool = False,
) -> None:
    pdf.set_font("Helvetica", style, size)
    pdf.set_text_color(*color)
    line_h = size + 1.4
    block = line_h * len(lines)
    baseline = y + (height - block) / 2 + size * 0.8
    for line in lines:
        text_width = pdf.get_string_width(line)
        text_x = x + 4 if left else x + (width - text_width) / 2
        if left and text_width > width - 8:
            while line and pdf.get_string_width(line + "...") > width - 8:
                line = line[:-1]
            line = line.rstrip() + "..."
            text_width = pdf.get_string_width(line)
        pdf.text(text_x, baseline, line)
        baseline += line_h


def _token(pdf: FPDF, text: str, center_x: float, baseline: float, size: float, circled: bool) -> None:
    pdf.set_font("Helvetica", "", size)
    pdf.set_text_color(0, 0, 0)
    width = pdf.get_string_width(text)
    x = center_x - width / 2
    pdf.text(x, baseline, text)
    if circled:
        pdf.set_draw_color(*PEN)
        pdf.set_line_width(1.05)
        pad_x = 2.6
        top = baseline - size * 0.78
        pdf.ellipse(x - pad_x, top - 1.2, width + pad_x * 2, size * 0.95 + 2.4)


def _comment(pdf: FPDF, x: float, width: float, baseline: float, comment: str) -> None:
    text = _pdf_text(comment)
    size = 8.0
    max_width = width - 8
    pdf.set_text_color(*PEN)
    pdf.set_font("Helvetica", "", size)
    while size > 6 and pdf.get_string_width(text) > max_width:
        size -= 0.25
        pdf.set_font("Helvetica", "", size)
    if pdf.get_string_width(text) > max_width:
        while text and pdf.get_string_width(text + "...") > max_width:
            text = text[:-1]
        text = text.rstrip() + "..."
    pdf.text(x + 4, baseline, text)
    if text.startswith(("increase", "decrease", "keep interval")):
        phrase = text.split(" - ")[0]
        pdf.set_draw_color(*PEN)
        pdf.set_line_width(0.7)
        pdf.line(x + 4, baseline + 1.6, x + 4 + pdf.get_string_width(phrase), baseline + 1.6)
