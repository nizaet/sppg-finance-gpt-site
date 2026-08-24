from __future__ import annotations

from typing import Any

from backend import accountant_excel_polish_patch as polish

_INSTALLED = False


def _indonesian_qty_format(value: Any) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "General"
    # 0x0421 = Indonesian (Indonesia) locale. Keep numeric cells numeric while
    # displaying the local decimal/group separators in Excel-compatible viewers.
    return "[$-0421]#,##0" if abs(number - round(number)) < 0.0000001 else "[$-0421]#,##0.####"


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    polish._qty_format = _indonesian_qty_format
    _INSTALLED = True
