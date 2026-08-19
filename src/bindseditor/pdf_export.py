"""Render the binding table to a PDF, grouped by device."""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

from .devices import device_sort_key
from .parser import BindingRow

_HEADER = ["Action", "Slot", "Key", "Modifiers", "Inverted"]
_COL_WIDTHS = (70, 22, 55, 55, 20)


def _group_by_device(rows: list[BindingRow]) -> dict[str, list[BindingRow]]:
    groups: dict[str, list[BindingRow]] = {}
    for row in rows:
        groups.setdefault(row.device_name, []).append(row)
    for device_rows in groups.values():
        device_rows.sort(key=lambda r: (r.label, r.slot))
    return groups


def export_pdf(rows: list[BindingRow], preset_name: str, out_path: Path) -> None:
    groups = _group_by_device(rows)
    device_names = sorted(groups.keys(), key=device_sort_key)

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)

    for device_name in device_names:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, f"{preset_name} - {device_name}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 9)

        table_rows = [_HEADER]
        for r in groups[device_name]:
            table_rows.append([r.label, r.slot, r.key, r.modifiers, r.inverted])

        pdf.table(
            rows=table_rows,
            col_widths=_COL_WIDTHS,
            text_align="LEFT",
            first_row_as_headings=True,
        )

    pdf.output(str(out_path))
