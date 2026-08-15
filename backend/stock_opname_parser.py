from __future__ import annotations

import re
from datetime import date
from typing import Any


MONTHS = {
    "januari": 1,
    "februari": 2,
    "maret": 3,
    "april": 4,
    "mei": 5,
    "juni": 6,
    "juli": 7,
    "agustus": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "desember": 12,
}

UNIT_ALIASES = {
    "kgs": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "gram": "gr",
    "grams": "gr",
    "pc": "pcs",
    "piece": "pcs",
    "pieces": "pcs",
    "packs": "pack",
    "dus": "dus",
    "karton": "karton",
    "karung": "karung",
    "kantong": "kantong",
    "liter": "liter",
    "litre": "liter",
    "ltr": "liter",
    "lt": "liter",
    "l": "liter",
    "ons": "ons",
    "butir": "butir",
    "botol": "botol",
    "pouch": "pouch",
    "ikat": "ikat",
    "papan": "papan",
    "roll": "roll",
    "rol": "roll",
}

SECTION_NAMES = {
    "gudang kering": "GUDANG_KERING",
    "gudang basah": "GUDANG_BASAH",
    "kantor": "KANTOR",
    "protein": "PROTEIN",
    "ayam ikan": "PROTEIN",
}

QUANTITY_PATTERN = re.compile(
    r"(?P<qty>\d+(?:[\.,]\d+)?)\s*(?P<unit>kg|kgs|kilogram|kilograms|gram|grams|gr|pcs|pc|piece|pieces|pack|packs|dus|karton|karung|kantong|liter|litre|ltr|lt|l|ons|butir|botol|pouch|ikat|papan|roll|rol)?\b",
    re.IGNORECASE,
)


def normalize_name(value: str) -> str:
    text = value.lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def canonical_unit(value: str | None) -> str:
    if not value:
        return ""
    unit = value.lower().strip().rstrip(".")
    return UNIT_ALIASES.get(unit, unit)


def parse_decimal(value: str) -> float:
    return float(value.replace(",", "."))


def extract_stock_date(text: str) -> date | None:
    match = re.search(
        r"\b(?:tgl|tanggal)\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    month = MONTHS.get(match.group(2).lower())
    if not month:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1)))
    except ValueError:
        return None


def _clean_line(raw: str) -> str:
    line = raw.strip()
    line = re.sub(r"^\[[^\]]+\]\s*[^:]{1,80}:\s*", "", line)
    line = re.sub(r"^[\-•*\s]+", "", line)
    line = re.sub(r"^\d+\s*[\.\)]\s*", "", line)
    line = line.replace("⁠", "").strip()
    return line


def _section_for(line: str) -> str | None:
    normalized = normalize_name(line.replace("*", ""))
    return SECTION_NAMES.get(normalized)


def _item_name_before_quantity(line: str, match: re.Match[str]) -> str:
    name = line[: match.start()].strip(" :;=-+")
    return re.sub(r"\s+", " ", name).strip()


def parse_stock_opname_text(text: str) -> dict[str, Any]:
    """Parse a WhatsApp-style SO report without guessing unit conversions.

    Mixed units are returned as separate components. A component without a unit
    remains review-required and is never merged with a kg/pcs planning line.
    """

    section = "UNSPECIFIED"
    pending_name: str | None = None
    last_item_name: str | None = None
    last_area = section
    parsed: list[dict[str, Any]] = []
    warnings: list[str] = []

    for raw_line in text.splitlines():
        line = _clean_line(raw_line)
        if not line:
            continue
        found_section = _section_for(line)
        if found_section:
            section = found_section
            last_area = section
            pending_name = None
            continue
        normalized_line = normalize_name(line.replace("*", ""))
        if not normalized_line or normalized_line in {"so barang"}:
            continue
        if re.search(r"\b(?:tgl|tanggal)\b", line, re.IGNORECASE):
            continue

        matches = list(QUANTITY_PATTERN.finditer(line))
        if not matches:
            candidate = line.strip(" :;=-+")
            if candidate and len(candidate) <= 100:
                pending_name = candidate
            continue

        first = matches[0]
        name = _item_name_before_quantity(line, first)
        if normalize_name(name) in {"berat", "total berat"}:
            name = pending_name or last_item_name or "Berat tanpa item"
        elif not name:
            name = pending_name or last_item_name or "Item tanpa nama"
        pending_name = None

        # Ungrouped protein lines commonly follow a second WhatsApp timestamp.
        area = section
        if area == "UNSPECIFIED" and re.search(r"\b(ayam|ikan|dori|daging)\b", name, re.IGNORECASE):
            area = "PROTEIN"
        if re.search(r"\b(ayam|ikan|dori|daging)\b", name, re.IGNORECASE):
            area = "PROTEIN"

        component_count = 0
        for match in matches:
            between = line[first.end() : match.start()] if match is not first else ""
            if match is not first and "+" not in between and "," not in between and ";" not in between:
                continue
            qty = parse_decimal(match.group("qty"))
            unit = canonical_unit(match.group("unit"))
            parse_status = "READY" if unit else "REVIEW"
            item_warnings: list[str] = []
            if not unit:
                item_warnings.append("Satuan tidak tertulis; tidak akan dipakai untuk mengurangi PO beda satuan.")
            parsed.append(
                {
                    "areaCode": area,
                    "itemName": name,
                    "normalizedItemName": normalize_name(name),
                    "qty": qty,
                    "unit": unit,
                    "parseStatus": parse_status,
                    "rawLine": raw_line.strip(),
                    "warnings": item_warnings,
                }
            )
            component_count += 1

        if component_count:
            last_item_name = name
            last_area = area

    seen: dict[tuple[str, str], int] = {}
    for item in parsed:
        key = (item["normalizedItemName"], item["unit"])
        seen[key] = seen.get(key, 0) + 1
    for (name, unit), count in seen.items():
        if count > 1:
            unit_label = unit or "tanpa satuan"
            warning = f"Duplikat {name} ({unit_label}) muncul {count} kali; jumlah akan dijumlahkan jika dikonfirmasi."
            warnings.append(warning)
            for item in parsed:
                if (item["normalizedItemName"], item["unit"]) == (name, unit):
                    item["warnings"].append(warning)
                    item["parseStatus"] = "REVIEW"

    for item in parsed:
        for warning in item["warnings"]:
            if warning not in warnings:
                warnings.append(warning)

    parsed_date = extract_stock_date(text)
    return {
        "detectedStockDate": parsed_date.isoformat() if parsed_date else None,
        "items": parsed,
        "itemCount": len(parsed),
        "readyCount": sum(1 for item in parsed if item["parseStatus"] == "READY"),
        "reviewCount": sum(1 for item in parsed if item["parseStatus"] != "READY"),
        "warnings": warnings,
        "canCommit": bool(parsed),
    }
