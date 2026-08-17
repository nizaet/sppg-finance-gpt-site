from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalize_item_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _contains(text: str, pattern: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


# Operational stock types: brand, grade and cultivar suffixes are ignored only
# when the underlying ingredient remains interchangeable for warehouse usage.
_STOCK_TYPE_PATTERNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("TEPUNG_TAPIOKA", "Tepung Tapioka", (r"\btepung\s+tapioka\b", r"\btapioka\b")),
    ("TEPUNG_TERIGU", "Tepung Terigu", (r"\btepung\s+terigu\b", r"\bterigu\b")),
    ("TEPUNG_MAIZENA", "Tepung Maizena", (r"\btepung\s+maizena\b", r"\bmaizena\b")),
    ("TEPUNG_BERAS", "Tepung Beras", (r"\btepung\s+beras\b",)),
    ("TEPUNG_PANIR", "Tepung Panir", (r"\btepung\s+panir\b", r"\bbreadcrumbs?\b")),
    ("KALDU_AYAM_BUBUK", "Kaldu Ayam Bubuk", (r"\bknorr\b.*\bchicken\b", r"\bchicken\s+powder\b", r"\bkaldu\s+ayam\b")),
    ("KALDU_JAMUR", "Kaldu Jamur", (r"\btotole\b", r"\bkaldu\s+jamur\b")),
    ("MINYAK_GORENG", "Minyak Goreng", (r"\bminyak\s+goreng\b",)),
    ("MINYAK_WIJEN", "Minyak Wijen", (r"\bminyak\s+wijen\b",)),
    ("KECAP_MANIS", "Kecap Manis", (r"\bkecap\s+manis\b",)),
    ("KECAP_ASIN", "Kecap Asin", (r"\bkecap\s+asin\b",)),
    ("KECAP_INGGRIS", "Kecap Inggris", (r"\bkecap\s+inggris\b", r"\bworcestershire\b")),
    ("SAUS_TOMAT", "Saus Tomat", (r"\bsaus\s+tomat\b", r"\bsaos\s+tomat\b")),
    ("SAUS_SAMBAL", "Saus Sambal", (r"\bsaus\s+sambal\b", r"\bsaos\s+sambal\b")),
    ("GULA_PASIR", "Gula Pasir", (r"\bgula\s+pasir\b", r"\bgula\s+putih\b")),
    ("GARAM", "Garam", (r"\bgaram\b",)),
    ("BAKING_POWDER", "Baking Powder", (r"\bbaking\s+powder\b",)),
    ("CUKA", "Cuka", (r"\bcuka\b",)),
    ("LADA_PUTIH", "Lada Putih", (r"\b(lada|merica)\s+(bubuk\s+)?putih\b",)),
    ("LADA_HITAM", "Lada Hitam", (r"\b(lada|merica)\s+(bubuk\s+)?hitam\b",)),
    ("KETUMBAR", "Ketumbar", (r"\bketumbar\b",)),
    ("KUNYIT_BUBUK", "Kunyit Bubuk", (r"\bkunyit\s+bubuk\b",)),
    ("BAWANG_PUTIH_BUBUK", "Bawang Putih Bubuk", (r"\bbawang\s+putih\s+bubuk\b",)),
    ("ANGGUR", "Anggur", (r"\banggur\b", r"\bgrapes?\b")),
    ("BAWANG_MERAH", "Bawang Merah", (r"\bbawang\s+merah\b",)),
    ("BAWANG_PUTIH", "Bawang Putih", (r"\bbawang\s+putih\b",)),
    ("CABAI_RAWIT", "Cabai Rawit", (r"\b(cabai|cabe)\s+rawit\b",)),
    ("CABAI_MERAH", "Cabai Merah", (r"\b(cabai|cabe)\s+merah\b",)),
    ("TELUR", "Telur", (r"\btelur\b", r"\beggs?\b")),
    ("TEMPE", "Tempe", (r"\btempe\b",)),
    ("TAHU", "Tahu", (r"\btahu\b", r"\btofu\b")),
    ("BERAS", "Beras", (r"\bberas\b", r"\brice\b")),
    ("IKAN_DORI", "Ikan Dori", (r"\bdori\b",)),
)


def stock_type(value: Any) -> dict[str, str]:
    text = normalize_item_text(value)
    for code, label, patterns in _STOCK_TYPE_PATTERNS:
        if any(_contains(text, pattern) for pattern in patterns):
            return {"code": code, "label": label, "method": "ITEM_TYPE_RULE"}
    return {
        "code": re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_") or "UNKNOWN",
        "label": str(value or "").strip() or "Unknown",
        "method": "RAW_FALLBACK",
    }


def item_family(name: Any, category: Any = None) -> str:
    text = normalize_item_text(name)
    category_text = normalize_item_text(category)
    combined = f"{category_text} {text}".strip()

    # Milk is operationally purchased through KOPERASI regardless of a stale
    # calculator supplier/category label. Keep this before protein/category
    # detection so e.g. "Susu Clevo 115ml Full Cream" cannot inherit IKAN.
    if _contains(text, r"\b(susu|milk)\b"):
        return "DRY_GOODS"

    # Pantry/dry goods win before protein words. This prevents e.g.
    # "Knorr Chicken Powder" from becoming chicken/WIKIAN.
    if any(
        _contains(combined, pattern)
        for pattern in (
            r"\bbahan\s+kering\b", r"\bdry\s+goods?\b", r"\bsembako\b", r"\bpackaging\b",
            r"\btepung\b", r"\btapioka\b", r"\bterigu\b", r"\bmaizena\b",
            r"\bknorr\b", r"\bkaldu\b", r"\btotole\b", r"\bpowder\b", r"\bbubuk\b",
            r"\bminyak\b", r"\bgula\b", r"\bgaram\b", r"\bkecap\b", r"\bsaus\b", r"\bsaos\b",
            r"\bcuka\b", r"\bbaking\s+powder\b", r"\blada\b", r"\bmerica\b", r"\bketumbar\b",
            r"\bsantan\b", r"\bsusu\b", r"\bmilk\b",
        )
    ):
        return "DRY_GOODS"

    if _contains(combined, r"\btelur\b|\beggs?\b"):
        return "EGG"
    if _contains(combined, r"\btempe\b"):
        return "TEMPE"
    if _contains(combined, r"\btahu\b|\btofu\b"):
        return "TOFU"
    if _contains(combined, r"\bberas\b|\brice\b"):
        return "RICE"
    if _contains(combined, r"\bdori\b|\bikan\b|\bfish\b"):
        return "FISH"
    if _contains(combined, r"\bgas\b|\blpg\b"):
        return "GAS"
    if _contains(combined, r"\bayam\b|\bchicken\b"):
        return "CHICKEN"

    if any(token in category_text for token in ("sayur", "buah", "bumbu", "vegetable", "fruit", "fresh produce")):
        return "PRODUCE"

    if _contains(
        text,
        r"\b(bawang merah|bawang putih|cabai|cabe|tomat|wortel|buncis|kembang kol|kol|daun bawang|daun jeruk|sereh|serai|"
        r"anggur|apel|melon|semangka|pisang|pepaya|jeruk medan|buah naga|timun|mentimun|kentang|labu|bayam|kangkung|sawi)\b",
    ):
        return "PRODUCE"

    return "UNKNOWN"


def vendor_for_item(name: Any, category: Any, site: str, preferred_vendor: Any = None) -> str | None:
    family = item_family(name, category)
    site_code = str(site or "").upper().strip()
    mapping = {
        "CHICKEN": "WIKIAN",
        "FISH": "RUMAH_DUTA_PANGAN",
        "RICE": "DEDE",
        "GAS": "HERU",
        "EGG": "KOPERASI",
        "PRODUCE": "HOLIL",
        "DRY_GOODS": "KOPERASI",
    }
    if family == "TOFU":
        return "HAJI_BADRI" if site_code == "CEMPLANG" else "KOPERASI"
    if family == "TEMPE":
        # Operator-confirmed: Tempe is fulfilled by KOPERASI at both sites.
        # Lead time remains site/item-specific and is resolved separately; in
        # particular Cemplang must not borrow Tahu or generic Koperasi lead time.
        if site_code in {"MAJA", "CEMPLANG"}:
            return "KOPERASI"
        preferred = str(preferred_vendor or "").upper().strip()
        return preferred or None
    if family in mapping:
        return mapping[family]

    preferred = str(preferred_vendor or "").upper().strip()
    dedicated = {"WIKIAN", "RUMAH_DUTA_PANGAN", "DEDE", "HERU", "HAJI_BADRI"}
    if preferred in dedicated:
        return None
    return preferred or None
