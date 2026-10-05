"""Private invoice identity/catalogue configuration; never publish source PII."""
import json
import os


def _private_reference():
    try:
        value = json.loads(os.getenv("LPDH_MAJA_DOCUMENT_REFERENCE", "{}"))
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


REFERENCE = _private_reference()
# Source names, addresses and bank details are configured privately in Railway.
# Accountants may override profiles through the existing site master data.
MAJA_PROFILES = REFERENCE.get("profiles") or {
    "KOPERASI": {"issuerName": "", "recipientName": "", "recipientAddress": "", "senderSignatory": "", "assetProfile": "maja-koperasi", "paymentMethod": "Transfer"},
    "YAYASAN": {"issuerName": "", "recipientName": "", "recipientAddress": "", "senderSignatory": "", "assetProfile": "maja-yayasan", "paymentMethod": "Transfer"},
}
MAJA_OPERATION_ITEMS = REFERENCE.get("operationItems") or [
    ("Gas lpj 50 kg", "Gas", "Tabung", 0), ("Gas lpj 12 kg", "Gas", "Tabung", 0),
    ("Sarung Tangan Plastik @200 pcs", "APD", "Pack", 0), ("Mama Lemon 650 ml", "Alat kebersihan", "Pouch", 0),
    ("Sarung tangan Latex/Nitril (100pcs)", "APD", "box", 0), ("Tali rapia Hitam", "Lain-lain", "Rol", 0),
    ("Tali rapia Warna", "Lain-lain", "Rol", 0), ("Plastik sampah 60 x 100", "Alat kebersihan", "Pack", 0),
    ("plastik sampah 90x120", "Alat kebersihan", "Pack", 0), ("Tisu hand towels", "Alat kebersihan", "pack", 0),
    ("Air Galon isi Ulang", "Air minum/galon", "galon", 0), ("Masker 3 Play", "APD", "Pack", 0),
    ("Hair Net (50pcs) - Tebal", "APD", "Pack", 0), ("Clink Pembersih Kaca", "Alat kebersihan", "Pouch", 0),
    ("Karbol Larist 4L", "Alat kebersihan", "jerigen", 0), ("Tinta Printer CF400A CF401A CF402A CF403A", "ATK", "set", 0),
    ("Sewa Mobil Distribusi", "Sewa kendaraan", "unit", 0),
]
