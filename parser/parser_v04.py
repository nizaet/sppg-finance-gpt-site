from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
import re
import uuid


@dataclass
class ParsedEvent:
    event_id: str
    event_type: str
    confidence: float
    requires_confirmation: bool
    raw_text: str
    actor: Optional[str] = None
    counterparty: Optional[str] = None
    site: Optional[str] = None
    vendor: Optional[str] = None
    structured_payload: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["structured_payload"] = self.structured_payload or {}
        return data


SITE_PATTERNS = {
    "MAJA": [r"\bmaja\b"],
    "CEMPLANG": [r"\bcemplang\b", r"\bcmplang\b"],
}

VENDOR_PATTERNS = {
    "HOLIL": [r"\bholil\b", r"\bholi\b", r"\bhaji holil\b"],
    "WIKIAN": [r"\bwikian\b"],
    "DEDE": [r"\bdede\b", r"\bberas\b"],
    "RUMAH_DUTA_PANGAN": [r"\brumah duta pangan\b", r"\bduta pangan\b"],
    "HERU": [r"\bheru\b", r"\bgas\b"],
    "HAJI_BADRI": [r"\bhaji badri\b", r"\bbadri\b"],
}


def _match_any(text: str, patterns: List[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def infer_site(text: str) -> Optional[str]:
    for site, patterns in SITE_PATTERNS.items():
        if _match_any(text, patterns):
            return site
    return None


def infer_vendor(text: str) -> Optional[str]:
    for vendor, patterns in VENDOR_PATTERNS.items():
        if _match_any(text, patterns):
            return vendor
    return None


def classify_event(text: str) -> ParsedEvent:
    normalized = " ".join(text.strip().split())
    lower = normalized.lower()
    site = infer_site(normalized)
    vendor = infer_vendor(normalized)

    def event(name: str, confidence: float, confirm: bool, payload: Optional[Dict[str, Any]] = None):
        return ParsedEvent(
            event_id=str(uuid.uuid4()),
            event_type=name,
            confidence=confidence,
            requires_confirmation=confirm,
            raw_text=normalized,
            site=site,
            vendor=vendor,
            structured_payload=payload or {},
        )

    # Payment intent must never become PAID.
    if re.search(r"\b(nanti|ntar|engke)\b.*\b(transfer|bayar)\b", lower):
        return event("PAYMENT_INTENT", 0.96, True)

    # Candidate payment evidence; still reconciled against amount/account evidence.
    if re.search(r"\b(sudah|udah|tos)\b.*\b(transfer|bayar|dibayar)\b", lower) or "bukti transfer" in lower:
        return event("PAYMENT_EVIDENCE_CANDIDATE", 0.92, True)

    if any(k in lower for k in ["reject", "bs", "busuk", "rusak", "balikin", "retur"]):
        return event("QUALITY_REJECT_REPORTED", 0.94, True)

    if any(k in lower for k in ["harga naik", "harga turun", "harga berubah", "harga jadi"]):
        return event("VENDOR_PRICE_CHANGED", 0.93, True)

    if any(k in lower for k in ["kosong", "ga ada", "gak ada", "tidak ada"]) and any(k in lower for k in ["barang", "stok", "buah", "sayur", "ayam", "ikan"]):
        return event("VENDOR_AVAILABILITY_CHANGED", 0.88, True)

    if any(k in lower for k in ["tambahan", "tambah ", "kurang ", "revisi", "ubah ", "ganti "]):
        if any(k in lower for k in ["kg", "pcs", "pack", "dus", "liter", "ltr", "butir", "papan", "ikat"]):
            return event("PO_REVISION", 0.90, True)

    if "stok" in lower and "koperasi" in lower and any(k in lower for k in ["kirim", "ambil", "antar", "bawa"]):
        return event("KOPERASI_STOCK_TRANSFER_REQUEST", 0.96, True)

    if any(k in lower for k in ["sudah sampai", "udah sampai", "barang datang", "diterima", "sampe"]):
        return event("GOODS_RECEIVED_CANDIDATE", 0.86, True)

    if any(k in lower for k in ["otw", "jalan", "dikirim", "berangkat"]):
        return event("GOODS_IN_TRANSIT", 0.84, False)

    if any(k in lower for k in ["pesan", "order", "po ", "untuk besok", "buat besok"]):
        if any(k in lower for k in ["kg", "pcs", "pack", "dus", "liter", "ltr", "butir", "papan", "ikat"]):
            return event("PO_NEW_CANDIDATE", 0.82, True)

    if lower in {"ok", "oke", "siap", "ready", "noted"} or re.fullmatch(r"(ok|oke|siap|ready|noted)[.! ]*", lower):
        return event("ACKNOWLEDGEMENT_ONLY", 0.98, False)

    return event("UNCLASSIFIED", 0.30, True)


def parse_message(text: str) -> Dict[str, Any]:
    return classify_event(text).to_dict()
