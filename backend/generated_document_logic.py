"""Canonical document snapshots and idempotent LPDH import (no database I/O)."""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP

OP_CATEGORIES = [
    "BPJS Ketenagakerjaan", "Listrik", "Air PDAM", "Air minum/galon", "Gas",
    "Sewa kendaraan", "BBM", "Pulsa dan internet", "ATK", "Alat kebersihan",
    "APD (masker, sarung tangan, penutup kepala)", "Biaya rapat koordinasi", "Lain-lain",
]
ALIASES = {"gas": "Gas", "gas_lpg": "Gas", "sewa_mobil": "Sewa kendaraan",
           "sewa mobil": "Sewa kendaraan", "air_galon": "Air minum/galon",
           "apd": OP_CATEGORIES[10], "atk": "ATK", "kebersihan": "Alat kebersihan",
           "alat_kebersihan": "Alat kebersihan", "lain_lain": "Lain-lain",
           "internet": "Pulsa dan internet", "retribusi sampah": "Lain-lain"}


def category_name(value, fallback=None):
    text = str(value or "").strip()
    known = next((x for x in OP_CATEGORIES if x.lower() == text.lower()), ALIASES.get(text.lower()))
    return known or (category_name(fallback) if fallback else "Lain-lain")


def line_amount(quantity, price):
    return float((Decimal(str(quantity)) * Decimal(str(price))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


AGGREGATE_PAYMENT_VERSION = 2


def aggregate_payment(document):
    return document.get("documentType") in {"UPAH_RELAWAN", "INSENTIF_GURU_KADER"} and (document.get("header") or {}).get("paymentSnapshotVersion") == AGGREGATE_PAYMENT_VERSION


def receipt_number(document, index):
    if aggregate_payment(document):
        return document["documentNumber"]
    manual = str((document["items"][index].get("metadata") or {}).get("receiptNo") or "").strip()
    if manual:
        return manual
    # Preserve numbers on historical documents created before manual numbering.
    return f"{document['documentNumber']}-{index + 1:03d}"


def document_rows(document):
    """Map exactly the saved/printed snapshot; never look up live prices here."""
    kind = document["documentType"]
    header = document.get("header") or {}
    rows = []
    for index, item in enumerate(document["items"]):
        metadata = item.get("metadata") or {}
        common = {
            "date": document["serviceDate"], "source": "FINAL_DOCUMENT",
            "sourceDocumentId": document["id"], "sourceLine": index + 1,
            "evidenceLink": header.get("evidenceLink") or "",
            "paymentReference": header.get("paymentReference") or "",
            "aggregatePayment": aggregate_payment(document),
        }
        if kind in {"BAHAN_BAKU", "OPERASIONAL"}:
            rows.append({**common, "name": item["itemName"], "description": item["itemName"],
                         "category": item["category"], "itemCode": metadata.get("itemCode") or "",
                         "qty": item["quantity"], "unit": item["unit"], "price": item["unitPrice"],
                         "invoiceNo": document["documentNumber"],
                         "supplier": header.get("issuerName") or "", "note": metadata.get("note") or ""})
        elif kind == "UPAH_RELAWAN":
            rows.append({**common, "name": item["itemName"],
                         "volunteerCode": metadata.get("volunteerCode") or item["itemName"],
                         "role": metadata.get("role") or "", "workDays": 1,
                         "dailyRate": item["unitPrice"], "receiptNo": receipt_number(document, index),
                         "paymentMethod": header.get("paymentMethod") or "Transfer"})
        else:
            rows.append({**common, "name": item["itemName"], "type": metadata.get("recipientType") or "Guru",
                         "unitName": metadata.get("unitName") or "", "amount": item["lineTotal"],
                         "receiptNo": receipt_number(document, index)})
    key = {"BAHAN_BAKU": "rawMaterials", "OPERASIONAL": "operations",
           "UPAH_RELAWAN": "volunteerPayments", "INSENTIF_GURU_KADER": "incentiveRecipients"}[kind]
    return key, rows


def merge_final_documents(daily, documents):
    """Rebuild sourced rows; preserve unrelated data and refuse duplicate payments."""
    out = deepcopy(daily or {})
    finalized = [doc for doc in documents if doc["status"] == "FINAL"]
    if not finalized:
        if out.get("_generatedDocumentIds") or any(r.get("sourceDocumentId") for key in ("rawMaterials", "operations", "volunteerPayments", "incentiveRecipients") for r in out.get(key) or []):
            for key in ("rawMaterials", "operations", "volunteerPayments", "incentiveRecipients"):
                out[key] = [r for r in out.get(key) or [] if not r.get("sourceDocumentId")]
            out["_generatedDocumentIds"] = []
        return out
    incoming = {key: [] for key in ("rawMaterials", "operations", "volunteerPayments", "incentiveRecipients")}
    invoice_numbers = {doc["documentNumber"] for doc in finalized}
    for doc in finalized:
        key, rows = document_rows(doc)
        incoming[key].extend(rows)
    for key, rows in incoming.items():
        supplemental = {(str(r.get("sourceDocumentId")), r.get("sourceLine")): r for r in out.get(key) or [] if r.get("sourceDocumentId")}
        for row in rows:
            saved = supplemental.get((str(row["sourceDocumentId"]), row["sourceLine"]), {})
            for field in ("evidenceLink", "paymentReference"):
                if field in saved:
                    row[field] = saved[field]
        kept = [row for row in out.get(key) or [] if not row.get("sourceDocumentId") and row.get("source") != "FINAL_KALKULATOR"]
        if any(row.get("invoiceNo") in invoice_numbers for row in kept):
            raise ValueError("Nomor invoice final sudah diisi manual pada data harian. Hapus baris manual yang sama sebelum menarik dokumen.")
        if key in {"volunteerPayments", "incentiveRecipients"}:
            recipients = set()
            for row in kept + rows:
                amount = float(row.get("amount") or 0) if key == "incentiveRecipients" else float(row.get("workDays") or 0) * float(row.get("dailyRate") or 0)
                if amount <= 0:
                    continue
                identity = (str(row.get("name") or "").strip().casefold(), str(row.get("type") or "").strip().casefold() if key == "incentiveRecipients" else "")
                if identity in recipients:
                    raise ValueError(f"Pembayaran harian untuk {row.get('name')} sudah tercatat. Periksa kuitansi agar tidak dibayar dua kali.")
                recipients.add(identity)
            names = {str(row.get("name") or "").strip().casefold() for row in rows}
            kept = [r for r in kept if str(r.get("name") or "").strip().casefold() not in names or float(r.get("amount") or 0) > 0 or float(r.get("workDays") or 0) > 0]
        out[key] = kept + rows
    if len(out["rawMaterials"]) > 40 or len(out["volunteerPayments"]) > 60:
        raise ValueError("Jumlah baris melebihi kapasitas workbook (40 bahan atau 60 relawan). Gabungkan item sebelum finalisasi.")
    register_count = sum(1 if d["documentType"] in {"BAHAN_BAKU", "OPERASIONAL"} or aggregate_payment(d) else len(d["items"]) for d in finalized)
    register_count += sum(1 for key in incoming for r in out[key] if not r.get("sourceDocumentId"))
    register_count += len(out.get("topups") or [])
    if float((out.get("incentive") or {}).get("paidAmount") or 0) > 0:
        register_count += 1
    if register_count > 121:
        raise ValueError("Register bukti melebihi kapasitas 121 dokumen/baris workbook. Kurangi atau gabungkan dokumen sebelum finalisasi.")
    out["_documentWorkflow"] = True
    out["_generatedDocumentIds"] = [doc["id"] for doc in finalized]
    for key, prefix in (("volunteerPayments", "volunteer"), ("incentiveRecipients", "incentive")):
        if incoming[key]:
            out[f"{prefix}PaymentDate"] = incoming[key][0]["date"]
    return out


def grouped_operations(rows):
    groups = {}
    for row in rows:
        category = category_name(row.get("category"), row.get("description"))
        groups.setdefault(category, []).append(row)
    result = []
    for category, items in groups.items():
        if len(items) == 1:
            result.append({**items[0], "description": category, "category": category})
            continue
        amount = sum(float(x.get("amount") or 0) for x in items)
        numbers = list(dict.fromkeys(str(x.get("invoiceNo") or "") for x in items if x.get("invoiceNo")))
        links = list(dict.fromkeys(str(x.get("evidenceLink") or "") for x in items if x.get("evidenceLink")))
        refs = list(dict.fromkeys(str(x.get("paymentReference") or "") for x in items if x.get("paymentReference")))
        result.append({"description": category, "category": category, "qty": 1, "unit": "paket",
                       "sourceDocumentIds": list(dict.fromkeys(x["sourceDocumentId"] for x in items if x.get("sourceDocumentId"))),
                       "price": amount, "amount": amount, "date": items[0].get("date"),
                       "invoiceNo": "; ".join(numbers), "evidenceLink": "; ".join(links), "paymentReference": "; ".join(refs),
                       "note": "; ".join(f"{x.get('description')}: {x.get('qty')} {x.get('unit')} ({x.get('invoiceNo') or '-'})" for x in items)})
    return result
