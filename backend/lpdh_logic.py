from __future__ import annotations

import base64
import io
import re
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.workbook import Workbook

ROOT = Path(__file__).resolve().parents[1]
LPDH_TEMPLATE = ROOT / "backend" / "templates" / "LPDH_SPPG_Format_Excel_PPK.xlsx"

GROUPS = [
    ("KS-01", "PAUD/TK/RA", "Kecil", "Sekolah"),
    ("KS-02", "SD/MI Kelas 1–3", "Kecil", "Sekolah"),
    ("KS-03", "SD/MI Kelas 4–6", "Besar", "Sekolah"),
    ("KS-04", "SMP/MTs", "Besar", "Sekolah"),
    ("KS-05", "SMA/MA/SMK/SLB", "Besar", "Sekolah"),
    ("KS-06", "Santri", "Besar", "Sekolah"),
    ("KS-07", "Ibu Hamil", "Besar", "3B"),
    ("KS-08", "Ibu Menyusui", "Besar", "3B"),
    ("KS-09", "Anak Balita (6–59 bulan)", "Kecil", "3B"),
    ("PTK", "Pendidik dan Tenaga Kependidikan", "Besar", "Sekolah"),
]

DEFAULT_PARAMETERS = {
    "incentiveTariff": 2000,
    "rawSmall": 8000,
    "rawLarge": 10000,
    "operationalPerPm": 3000,
    "maxVa": 500_000_000,
    "maxHpePerWeek": 5,
    "uploadHour": 6,
    "bufferPct": None,
    "dateTolerance": 1,
    "applyIndexRaw": True,
    "applyIndexOp": True,
    "cityIndex": 1.0,
    "cityIndexSource": "",
}

OPERATIONAL_DEFAULTS = [
    "Insentif relawan (daftar nominatif C1_Relawan)",
    "Insentif penanggung jawab satuan pendidikan",
    "Insentif kader posyandu",
    "BPJS Ketenagakerjaan",
    "Listrik",
    "Air PDAM",
    "Air minum/galon",
    "Gas",
    "Sewa kendaraan",
    "BBM",
    "Pulsa dan internet",
    "ATK",
    "Alat kebersihan",
    "APD (masker, sarung tangan, penutup kepala)",
    "Biaya rapat koordinasi",
    "Lain-lain",
]


def as_number(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("Rp", "").replace(" ", "")
    if not text:
        return default
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return default


def as_int(value: Any, default: int = 0) -> int:
    return int(round(as_number(value, default)))


def yes(value: Any) -> bool:
    return str(value or "").strip().lower() in {"ya", "yes", "y", "true", "1", "signed", "terlampir", "ada"}


def https_url(value: Any) -> bool:
    return str(value or "").strip().lower().startswith("https://")


def parse_iso_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_time(value: Any) -> time | None:
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            pass
    return None


def valid_id(identity_type: Any, number: Any) -> bool:
    digits = re.sub(r"\D", "", str(number or ""))
    kind = str(identity_type or "").strip().upper()
    if kind == "NIK":
        return len(digits) == 16
    if kind == "NIP":
        return len(digits) == 18
    return bool(digits)


def parameters(masters: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(DEFAULT_PARAMETERS)
    out.update(masters.get("parameters") or {})
    return out


def master_target_by_group(masters: dict[str, Any]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for row in masters.get("beneficiaries") or []:
        if str(row.get("status") or "Aktif").strip().lower() in {"nonaktif", "inactive"}:
            continue
        code = str(row.get("groupCode") or row.get("kodeKelompok") or row.get("code") or "").upper().strip()
        if code in {x[0] for x in GROUPS}:
            totals[code] += as_number(row.get("targetPm") if "targetPm" in row else row.get("target"))
    return totals


def merged_pm_rows(masters: dict[str, Any], daily: dict[str, Any], effective: bool) -> list[dict[str, Any]]:
    targets = master_target_by_group(masters)
    supplied = daily.get("pm", {}).get("rows") or []
    supplied_by_code = {
        str(row.get("code") or row.get("groupCode") or "").upper().strip(): row
        for row in supplied
    }
    result: list[dict[str, Any]] = []
    for code, label, portion, pic in GROUPS:
        source = supplied_by_code.get(code, {})
        target = as_number(source.get("targetPm"), targets.get(code, 0))
        distributed = as_number(source.get("distributed"))
        received = as_number(source.get("received"))
        not_received = as_number(source.get("notReceived"))
        bast_no = str(source.get("bastNo") or "").strip()
        bast_link = str(source.get("bastLink") or "").strip()
        bnba = source.get("bnba")
        bast_ok = received <= 0 or (bool(bast_no) and https_url(bast_link))
        calculated = received if effective and yes(bnba) and bast_ok else 0
        result.append({
            "code": code,
            "label": label,
            "portion": portion,
            "pic": pic,
            "targetPm": target,
            "distributed": distributed,
            "received": received,
            "notReceived": not_received,
            "reason": str(source.get("reason") or "").strip(),
            "difference": distributed - received - not_received,
            "bnba": "Ya" if yes(bnba) else "Tidak",
            "bastNo": bast_no,
            "bastLink": bast_link,
            "bastStatus": "Terlampir" if bast_ok and received > 0 else ("Tidak wajib" if received <= 0 else "Belum lengkap"),
            "calculatedPm": calculated,
            "achievement": (calculated / target) if target > 0 else 0,
            "note": str(source.get("note") or ""),
        })
    return result


def final_plan_raw_rows(final_plan: dict[str, Any] | None, service_date: str) -> list[dict[str, Any]]:
    payload = (final_plan or {}).get("payload") or {}
    shopping = (payload.get("shoppingListJSON") or {}).get("shoppingList") or []
    rows = []
    for item in shopping[:40]:
        qty = as_number(item.get("jumlah") if "jumlah" in item else item.get("qty"))
        price = as_number(item.get("harga_satuan") if "harga_satuan" in item else item.get("price"))
        rows.append({
            "date": service_date,
            "name": str(item.get("item") or item.get("name") or item.get("source_ingredient") or "").strip(),
            "category": str(item.get("category") or item.get("supplier_category") or ""),
            "qty": qty,
            "unit": str(item.get("satuan") or item.get("unit") or ""),
            "price": price,
            "supplier": str(item.get("supplier") or item.get("vendor") or ""),
            "invoiceNo": "",
            "evidenceLink": "",
            "note": str(item.get("note") or ""),
            "source": "FINAL_KALKULATOR",
        })
    return [row for row in rows if row["name"]]


def raw_rows(daily: dict[str, Any], final_plan: dict[str, Any] | None, service_date: str) -> list[dict[str, Any]]:
    rows = deepcopy(daily.get("rawMaterials") or [])
    if not rows:
        rows = final_plan_raw_rows(final_plan, service_date)
    for row in rows:
        row["qty"] = as_number(row.get("qty"))
        row["price"] = as_number(row.get("price"))
        row["amount"] = row["qty"] * row["price"]
    return rows[:40]


def volunteer_rows(masters: dict[str, Any], daily: dict[str, Any]) -> list[dict[str, Any]]:
    master = {
        str(row.get("code") or row.get("kode") or row.get("name") or "").strip(): row
        for row in masters.get("volunteers") or []
        if str(row.get("status") or "Aktif").lower() not in {"nonaktif", "inactive"}
    }
    supplied = daily.get("volunteerPayments") or []
    if supplied:
        rows = deepcopy(supplied)
    else:
        rows = [{
            "volunteerCode": key,
            "name": value.get("name") or value.get("nama") or key,
            "role": value.get("role") or value.get("tugas") or "",
            "workDays": 0,
            "dailyRate": value.get("dailyRate") or value.get("rate") or 0,
            "paymentMethod": value.get("paymentMethod") or "",
            "receiptNo": "",
            "evidenceLink": "",
            "date": "",
        } for key, value in master.items()]
    for row in rows:
        key = str(row.get("volunteerCode") or row.get("code") or row.get("name") or "").strip()
        ref = master.get(key, {})
        row["name"] = row.get("name") or ref.get("name") or ref.get("nama") or key
        row["role"] = row.get("role") or ref.get("role") or ref.get("tugas") or ""
        row["dailyRate"] = as_number(row.get("dailyRate"), as_number(ref.get("dailyRate") or ref.get("rate")))
        row["workDays"] = as_number(row.get("workDays"))
        row["amount"] = row["dailyRate"] * row["workDays"]
        row["paymentMethod"] = row.get("paymentMethod") or ref.get("paymentMethod") or ""
        row["date"] = row.get("date") or daily.get("volunteerPaymentDate") or ""
        row["evidenceLink"] = row.get("evidenceLink") or daily.get("volunteerBatchEvidenceLink") or ""
        row["paymentReference"] = row.get("paymentReference") or daily.get("volunteerPaymentReference") or ""
    return rows[:60]


def incentive_recipient_rows(daily: dict[str, Any]) -> list[dict[str, Any]]:
    rows = deepcopy(daily.get("incentiveRecipients") or [])
    for row in rows:
        row["amount"] = as_number(row.get("amount"))
        row["date"] = row.get("date") or daily.get("incentivePaymentDate") or ""
        row["evidenceLink"] = row.get("evidenceLink") or daily.get("incentiveBatchEvidenceLink") or ""
        row["paymentReference"] = row.get("paymentReference") or daily.get("incentivePaymentReference") or ""
    return rows


def operational_rows(masters: dict[str, Any], daily: dict[str, Any]) -> list[dict[str, Any]]:
    rows = deepcopy(daily.get("operations") or [])
    master_by_code = {str(x.get("code") or ""): x for x in masters.get("operations") or []}
    for row in rows:
        ref = master_by_code.get(str(row.get("itemCode") or ""), {})
        row["description"] = row.get("description") or ref.get("name") or ref.get("description") or ""
        row["unit"] = row.get("unit") or ref.get("unit") or ""
        row["qty"] = as_number(row.get("qty"))
        row["price"] = as_number(row.get("price"), as_number(ref.get("defaultPrice")))
        row["amount"] = row["qty"] * row["price"]
    return rows


def assign_document_numbers(rows: list[dict[str, Any]], base_key: str, explicit_key: str = "proofNo") -> list[dict[str, Any]]:
    cloned = deepcopy(rows)
    groups: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(cloned):
        base = str(row.get(explicit_key) or row.get(base_key) or "").strip()
        row["_baseProofNo"] = base
        if base:
            groups[base].append(index)
    for base, indexes in groups.items():
        if len(indexes) == 1:
            cloned[indexes[0]]["proofNoDerived"] = base
        else:
            width = max(2, len(str(len(indexes))))
            for seq, index in enumerate(indexes, start=1):
                cloned[index]["proofNoDerived"] = f"{base}-{seq:0{width}d}"
    return cloned


def service_date_from_rows(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        value = str(row.get("date") or "").strip()
        if value:
            return value
    return ""


def build_register(
    raw: list[dict[str, Any]],
    operations: list[dict[str, Any]],
    volunteers: list[dict[str, Any]],
    incentive_recipients: list[dict[str, Any]],
    daily: dict[str, Any],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    raw_numbered = assign_document_numbers(raw, "invoiceNo")
    for idx, row in enumerate(raw_numbered, 1):
        if as_number(row.get("amount")) <= 0 and not row.get("_baseProofNo"):
            continue
        entries.append({
            "source": "B_BahanBaku",
            "code": f"BB-{idx:03d}",
            "proofNo": row.get("proofNoDerived") or row.get("_baseProofNo") or "",
            "date": row.get("date") or "",
            "amount": as_number(row.get("amount")),
            "link": row.get("evidenceLink") or "",
        })

    # Normal operational rows. Guru/kader are added below as the aggregate
    # C_Operasional rows used by the official workbook.
    op_numbered = assign_document_numbers(operations, "invoiceNo")
    for idx, row in enumerate(op_numbered, 1):
        if as_number(row.get("amount")) <= 0 and not row.get("_baseProofNo"):
            continue
        entries.append({
            "source": "C_Operasional",
            "code": f"OP-{idx + 3:03d}",
            "proofNo": row.get("proofNoDerived") or row.get("_baseProofNo") or "",
            "date": row.get("date") or "",
            "amount": as_number(row.get("amount")),
            "link": row.get("evidenceLink") or "",
        })

    incentive_base = str(daily.get("incentiveReceiptBaseNo") or "").strip()
    school_rows = [
        x for x in incentive_recipients
        if str(x.get("type") or "").strip().lower() in {"guru", "sekolah", "penanggung jawab satuan pendidikan"}
    ]
    cadre_rows = [
        x for x in incentive_recipients
        if str(x.get("type") or "").strip().lower() in {"kader", "posyandu", "kader posyandu"}
    ]
    for code, rows, suffix, explicit_key in [
        ("OP-002", school_rows, "GURU", "schoolPicOperationalProofNo"),
        ("OP-003", cadre_rows, "KADER", "cadreOperationalProofNo"),
    ]:
        amount = sum(as_number(x.get("amount")) for x in rows)
        if amount <= 0:
            continue
        proof = str(
            daily.get(explicit_key)
            or (f"{incentive_base}-{suffix}" if incentive_base else "")
        ).strip()
        entries.append({
            "source": "C_Operasional",
            "code": code,
            "proofNo": proof,
            "date": daily.get("incentivePaymentDate") or service_date_from_rows(rows),
            "amount": amount,
            "link": daily.get("incentiveBatchEvidenceLink") or "",
        })

    # Relawan remain nominative and are registered per person.
    volunteer_base = str(daily.get("volunteerReceiptBaseNo") or "").strip()
    volunteer_for_number = []
    for row in volunteers:
        copy = deepcopy(row)
        copy["receiptBase"] = copy.get("receiptNo") or volunteer_base
        volunteer_for_number.append(copy)
    volunteer_numbered = assign_document_numbers(volunteer_for_number, "receiptBase")
    for idx, row in enumerate(volunteer_numbered, 1):
        if as_number(row.get("amount")) <= 0:
            continue
        entries.append({
            "source": "C1_Relawan",
            "code": f"RL-{idx:03d}",
            "proofNo": row.get("proofNoDerived") or row.get("_baseProofNo") or "",
            "date": row.get("date") or "",
            "amount": as_number(row.get("amount")),
            "link": row.get("evidenceLink") or "",
        })

    incentive = daily.get("incentive") or {}
    if as_number(incentive.get("paidAmount")) > 0 or incentive.get("proofNo"):
        entries.append({
            "source": "D_Insentif",
            "code": "INS-001",
            "proofNo": str(incentive.get("proofNo") or "").strip(),
            "date": incentive.get("paymentDate") or "",
            "amount": as_number(incentive.get("paidAmount")),
            "link": incentive.get("evidenceLink") or "",
        })

    for idx, row in enumerate(daily.get("topups") or [], 1):
        amount = (
            as_number(row.get("rawAmount"))
            + as_number(row.get("operationalAmount"))
            + as_number(row.get("incentiveAmount"))
        )
        if amount <= 0 and not row.get("receiptNo"):
            continue
        entries.append({
            "source": "E_Saldo",
            "code": f"TU-{idx:03d}",
            "proofNo": str(row.get("receiptNo") or "").strip(),
            "date": row.get("date") or "",
            "amount": amount,
            "link": row.get("evidenceLink") or "",
        })

    counts = Counter(
        str(x["proofNo"]).strip().upper()
        for x in entries
        if str(x["proofNo"]).strip()
    )
    for row in entries:
        proof = str(row["proofNo"]).strip()
        row["proofStatus"] = (
            "UNIK"
            if proof and counts[proof.upper()] == 1
            else ("DUPLIKAT" if proof else "BELUM ADA")
        )
    return entries


def compute_preview(
    masters: dict[str, Any],
    daily: dict[str, Any],
    service_date: str,
    effective: bool,
    final_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = parameters(masters)
    hpe_number = as_int(daily.get("hpeNumber"), 1)
    day_status = str(daily.get("dayStatus") or "HPE").strip()
    hpe_eligible = bool(
        effective
        and day_status == "HPE"
        and 1 <= hpe_number <= as_int(params.get("maxHpePerWeek"), 5)
    )
    pm = merged_pm_rows(masters, daily, hpe_eligible)
    raw = raw_rows(daily, final_plan, service_date)
    volunteers = volunteer_rows(masters, daily)
    incentive_recipients = incentive_recipient_rows(daily)
    operations = operational_rows(masters, daily)

    production = daily.get("pm", {}).get("production") or {}
    distributed = sum(row["distributed"] for row in pm)
    received = sum(row["received"] for row in pm)
    not_received = sum(row["notReceived"] for row in pm)
    calculated_pm = sum(row["calculatedPm"] for row in pm)
    produced_default = as_number((final_plan or {}).get("payload", {}).get("porsiKecil")) + as_number((final_plan or {}).get("payload", {}).get("porsiBesar"))
    produced = as_number(production.get("produced"), produced_default)
    organoleptic = as_number(production.get("organoleptic"))
    retained_sample = as_number(production.get("retainedSample"))
    production_not_distributed = as_number(production.get("notDistributed"))
    buffer_qty = as_number(production.get("buffer"))
    production_diff = produced - (distributed + organoleptic + retained_sample + production_not_distributed + buffer_qty)

    incentive_pm = calculated_pm + (organoleptic if hpe_eligible else 0) + (retained_sample if hpe_eligible else 0)
    index = as_number(params.get("cityIndex"), 1.0) or 1.0
    raw_small = as_number(params.get("rawSmall"), 8000) * (index if params.get("applyIndexRaw", True) else 1)
    raw_large = as_number(params.get("rawLarge"), 10000) * (index if params.get("applyIndexRaw", True) else 1)
    small_distributed = sum(row["distributed"] for row in pm if row["portion"] == "Kecil")
    large_distributed = sum(row["distributed"] for row in pm if row["portion"] == "Besar")
    weighted_raw_pagu = (
        (small_distributed * raw_small + large_distributed * raw_large) / distributed
        if distributed else 0
    )
    raw_total = sum(as_number(row.get("amount")) for row in raw)
    raw_per_portion = raw_total / produced if produced else 0

    volunteer_total = sum(as_number(row.get("amount")) for row in volunteers)
    incentive_recipient_total = sum(as_number(row.get("amount")) for row in incentive_recipients)
    normal_operational_total = sum(as_number(row.get("amount")) for row in operations)
    operational_total = volunteer_total + incentive_recipient_total + normal_operational_total
    op_pagu = as_number(params.get("operationalPerPm"), 3000) * (index if params.get("applyIndexOp", True) else 1)
    op_per_pm = operational_total / incentive_pm if incentive_pm else 0

    incentive = daily.get("incentive") or {}
    incentive_tariff = as_number(params.get("incentiveTariff"), 2000)
    incentive_calculated = incentive_pm * incentive_tariff
    register = build_register(raw, operations, volunteers, incentive_recipients, daily)

    balance = daily.get("balance") or {}
    opening = {
        "raw": as_number(balance.get("openingRaw")),
        "operational": as_number(balance.get("openingOperational")),
        "incentive": as_number(balance.get("openingIncentive")),
    }
    topups = daily.get("topups") or []
    topup_total = {
        "raw": sum(as_number(x.get("rawAmount")) for x in topups),
        "operational": sum(as_number(x.get("operationalAmount")) for x in topups),
        "incentive": sum(as_number(x.get("incentiveAmount")) for x in topups),
    }
    expenditure = {
        "raw": raw_total,
        "operational": operational_total,
        "incentive": as_number(incentive.get("paidAmount")),
    }
    closing = {key: opening[key] + topup_total[key] - expenditure[key] for key in opening}
    closing_total = sum(closing.values())
    bank_balance = as_number(balance.get("bankBalance"))
    bank_difference = closing_total - bank_balance

    required_topup = raw_total + operational_total + incentive_calculated
    room_to_max = max(0, as_number(params.get("maxVa"), 500_000_000) - closing_total)

    service_dt = parse_iso_date(service_date)
    tolerance = as_int(params.get("dateTolerance"), 1)
    valid_from = service_dt - timedelta(days=tolerance) if service_dt else None
    valid_to = service_dt

    def register_date_ok(row: dict[str, Any]) -> bool:
        tx = parse_iso_date(row.get("date"))
        if as_number(row.get("amount")) <= 0:
            return True
        return bool(tx and valid_from and valid_to and valid_from <= tx <= valid_to)

    evidence_missing = [r for r in register if as_number(r.get("amount")) > 0 and not https_url(r.get("link"))]
    duplicates = [r for r in register if r.get("proofStatus") == "DUPLIKAT"]
    invalid_dates = [r for r in register if not register_date_ok(r)]

    identity = masters.get("identity") or {}
    required_identity = ["sppgId", "sppgName", "vaNumber"]
    identity_ok = all(str(identity.get(key) or "").strip() for key in required_identity) and service_dt is not None
    city_reference_ok = bool(str(identity.get("city") or "").strip())

    all_distributions_balance = all(abs(row["difference"]) < 0.0001 for row in pm)
    reasons_ok = all(row["notReceived"] <= 0 or bool(row["reason"]) for row in pm)
    receiving_docs_ok = all(row["received"] <= 0 or (row["bnba"] == "Ya" and bool(row["bastNo"])) for row in pm)
    bast_links_ok = all(row["received"] <= 0 or https_url(row["bastLink"]) for row in pm)
    target_ok = all(row["calculatedPm"] <= row["targetPm"] + 0.0001 for row in pm if row["targetPm"] > 0)

    volunteer_complete = all(
        as_number(row.get("amount")) <= 0 or (
            bool(str(row.get("receiptNo") or daily.get("volunteerReceiptBaseNo") or "").strip())
            and https_url(row.get("evidenceLink"))
            and parse_iso_date(row.get("date")) is not None
        )
        for row in volunteers
    )

    eligibility = incentive.get("eligibility") or {}
    incentive_eligible = (
        hpe_eligible
        and not yes(eligibility.get("contamination"))
        and not yes(eligibility.get("fatalIncident"))
        and not yes(eligibility.get("suspended"))
        and yes(eligibility.get("verified"))
        and yes(eligibility.get("pmInputSipgn"))
    )

    paid = as_number(incentive.get("paidAmount"))
    statement = as_number(incentive.get("statementAmount"))
    incentive_payment_matches = abs(paid - statement) < 0.0001
    incentive_evidence_ok = paid <= 0 or (
        bool(str(incentive.get("proofNo") or "").strip())
        and bool(str(incentive.get("receiptNo") or "").strip())
        and yes(incentive.get("receiptSigned"))
        and https_url(incentive.get("evidenceLink"))
        and parse_iso_date(incentive.get("paymentDate")) is not None
    )

    topup_evidence_ok = all(
        (as_number(x.get("rawAmount")) + as_number(x.get("operationalAmount")) + as_number(x.get("incentiveAmount"))) <= 0
        or (bool(str(x.get("receiptNo") or "").strip()) and https_url(x.get("evidenceLink")) and parse_iso_date(x.get("date")) is not None)
        for x in topups
    )

    signers = masters.get("signers") or []
    signer_ok = len(signers) >= 3 and all(
        str(x.get("name") or "").strip()
        and valid_id(x.get("identityType"), x.get("identityNumber"))
        and yes(x.get("signed"))
        for x in signers[:3]
    )

    upload = daily.get("upload") or {}
    upload_date = parse_iso_date(upload.get("date"))
    upload_time = parse_time(upload.get("time"))
    deadline_date = service_dt + timedelta(days=1) if service_dt else None
    deadline_hour = as_int(params.get("uploadHour"), 6)
    upload_ok = bool(
        upload_date and upload_time and deadline_date
        and (
            upload_date < deadline_date
            or (upload_date == deadline_date and upload_time <= time(deadline_hour, 0))
        )
    )

    buffer_limit = params.get("bufferPct")
    if buffer_limit in (None, ""):
        buffer_ok = True
        buffer_status = "BELUM DITETAPKAN"
    else:
        buffer_ok = produced > 0 and (buffer_qty / produced) <= as_number(buffer_limit)
        buffer_status = "OK" if buffer_ok else "PERIKSA"

    checks = [
        ("01", "Identitas wajib terisi (ID SPPG, nama, tanggal, VA)", identity_ok, "PERIKSA", "Lengkapi ID SPPG, nama SPPG, tanggal pelayanan, dan nomor VA."),
        ("02", "Hari berstatus HPE dan HPE ke- tidak lebih dari 5", hpe_eligible, "PERIKSA", "Tanggal harus aktif sebagai HPE dan HPE ke- berada pada rentang yang diizinkan."),
        ("03", "Produksi POP seimbang (distribusi + organoleptik + sampel + tidak terdistribusi + buffer)", abs(production_diff) < 0.0001, "PERIKSA", f"Selisih produksi {production_diff:,.2f}."),
        ("04", "Distribusi POP sesuai penerimaan Fleet (per baris dan total)", all_distributions_balance, "PERIKSA", "Ada kelompok dengan distribusi tidak sama dengan diterima + tidak diterima."),
        ("05", "Porsi tidak diterima seluruhnya diberi alasan", reasons_ok, "PERIKSA", "Isi alasan untuk setiap porsi yang tidak diterima."),
        ("06", "Buffer produksi dalam batas yang ditetapkan", buffer_ok, buffer_status, "Batas buffer belum ditetapkan PPK." if buffer_status == "BELUM DITETAPKAN" else "Buffer melebihi ambang PPK."),
        ("07", "Kelompok yang menerima porsi memiliki BNBA dan nomor BAST", receiving_docs_ok, "PERIKSA", "Ada penerima dengan BNBA atau nomor BAST belum lengkap."),
        ("08", "Bukti autentik BAST ter-link ke Cloud SIPGN", bast_links_ok, "PERIKSA", "Link BAST wajib HTTPS untuk kelompok yang menerima."),
        ("09", "PM dihitung tidak melebihi target SPS (indikasi anomali)", target_ok, "PERIKSA", "Ada PM dihitung melebihi target master SPS."),
        ("10", "Indeks kemahalan Kab/Kota tercantum di Ref", city_reference_ok, "PERIKSA", "Isi Kabupaten/Kota pada Identitas dan indeks kemahalan pada Master Parameter."),
        ("11", "Biaya bahan per porsi dalam pagu setelah indeks kemahalan", produced > 0 and raw_per_portion <= weighted_raw_pagu + 0.0001, "PERIKSA", f"Biaya/porsi Rp{raw_per_portion:,.0f}; pagu Rp{weighted_raw_pagu:,.0f}."),
        ("12", "Biaya operasional per PM dalam pagu setelah indeks kemahalan", incentive_pm > 0 and op_per_pm <= op_pagu + 0.0001, "PERIKSA", f"Operasional/PM Rp{op_per_pm:,.0f}; pagu Rp{op_pagu:,.0f}."),
        ("13", "Setiap transaksi bernilai memiliki link bukti autentik", len(evidence_missing) == 0, "PERIKSA", f"{len(evidence_missing)} transaksi belum punya link HTTPS."),
        ("14", "Nomor bukti transaksi tidak duplikat", len(duplicates) == 0, "PERIKSA", f"{len(duplicates)} baris memakai nomor bukti duplikat."),
        ("15", "Tanggal transaksi sesuai periode kegiatan/produksi", len(invalid_dates) == 0, "PERIKSA", f"{len(invalid_dates)} transaksi di luar periode {valid_from} s.d. {valid_to}."),
        ("16", "Pembayaran insentif relawan lengkap (nominatif, nomor bukti, link bukti bayar)", volunteer_complete, "PERIKSA", "Ada relawan tanpa nomor kuitansi, tanggal, atau link bukti."),
        ("17", "Syarat pemberian Insentif terpenuhi", incentive_eligible, "PERIKSA", "Syarat Insentif Ketersediaan dan Mutu Layanan belum terpenuhi."),
        ("18", "Insentif dihitung = tarif × PM dihitung", True, "PERIKSA", ""),
        ("19", "Pembayaran Insentif sama dengan pernyataan PPK", incentive_payment_matches, "PERIKSA", "Nilai dibayar harus sama dengan nilai pernyataan PPK."),
        ("20", "Pembayaran Insentif ke Mitra/Yayasan didukung bukti autentik", incentive_evidence_ok, "PERIKSA", "Bukti pembayaran Insentif Mitra/Yayasan belum lengkap."),
        ("21", "Penerimaan top up didukung kuitansi/bukti terima, nilai, dan tanggal", topup_evidence_ok, "PERIKSA", "Ada top up tanpa kuitansi, tanggal, atau link bukti."),
        ("22", "Saldo akhir setiap komponen tidak negatif", all(value >= -0.0001 for value in closing.values()), "PERIKSA", "Ada saldo komponen negatif."),
        ("23", "Jumlah saldo komponen sama dengan saldo VA", bool(str(balance.get("bankBalance") if balance.get("bankBalance") is not None else "").strip()) and abs(bank_difference) < 1, "PERIKSA", f"Selisih saldo komponen vs VA Rp{bank_difference:,.0f}."),
        ("24", "Tanda tangan tiga pihak lengkap, dengan nama dan NIK/NIP valid", signer_ok, "PERIKSA", "Lengkapi Pengawas Keuangan, Kepala SPPG, dan Perwakilan Mitra/Yayasan."),
        ("25", "LPDH diunggah tepat waktu (H+1 pukul 06.00)", upload_ok, "PERIKSA", "Isi tanggal dan jam unggah; batas H+1 mengikuti Ref."),
        ("26", "Usulan top up dalam batas saldo VA", required_topup <= room_to_max + 0.0001, "PERIKSA", f"Usulan otomatis Rp{required_topup:,.0f}; ruang VA Rp{room_to_max:,.0f}."),
    ]
    check_rows = []
    for no, label, ok, fail_status, detail in checks:
        if no == "06" and buffer_status == "BELUM DITETAPKAN":
            status = buffer_status
        else:
            status = "OK" if ok else fail_status
        check_rows.append({
            "no": no,
            "check": label,
            "ok": status != "PERIKSA",
            "status": status,
            "detail": detail if status != "OK" else "",
        })
    error_count = sum(1 for row in check_rows if row["status"] == "PERIKSA")

    return {
        "serviceDate": service_date,
        "effective": effective,
        "hpeEligible": hpe_eligible,
        "dayStatus": day_status,
        "hpeNumber": hpe_number,
        "pmRows": pm,
        "production": {
            "produced": produced,
            "distributed": distributed,
            "received": received,
            "notReceived": not_received,
            "organoleptic": organoleptic,
            "retainedSample": retained_sample,
            "notDistributed": production_not_distributed,
            "buffer": buffer_qty,
            "difference": production_diff,
            "calculatedPm": calculated_pm,
            "incentivePm": incentive_pm,
        },
        "rawMaterials": raw,
        "rawTotal": raw_total,
        "rawPerPortion": raw_per_portion,
        "weightedRawPagu": weighted_raw_pagu,
        "rawStatus": "DALAM PAGU" if produced > 0 and raw_per_portion <= weighted_raw_pagu + 0.0001 else "MELEBIHI PAGU",
        "operations": operations,
        "volunteers": volunteers,
        "incentiveRecipients": incentive_recipients,
        "volunteerTotal": volunteer_total,
        "incentiveRecipientTotal": incentive_recipient_total,
        "operationalTotal": operational_total,
        "operationalPerPm": op_per_pm,
        "operationalPagu": op_pagu,
        "operationalStatus": "DALAM PAGU" if incentive_pm > 0 and op_per_pm <= op_pagu + 0.0001 else "MELEBIHI PAGU",
        "incentiveCalculated": incentive_calculated,
        "register": register,
        "balance": {
            "opening": opening,
            "topups": topup_total,
            "expenditure": expenditure,
            "closing": closing,
            "closingTotal": closing_total,
            "bankBalance": bank_balance,
            "bankDifference": bank_difference,
        },
        "topup": {
            "requiredRaw": raw_total,
            "requiredOperational": operational_total,
            "requiredIncentive": incentive_calculated,
            "requiredTotal": required_topup,
            "proposalTotal": required_topup,
            "roomToMax": room_to_max,
            "withinMax": required_topup <= room_to_max + 0.0001,
        },
        "validPeriod": {"from": valid_from.isoformat() if valid_from else "", "to": valid_to.isoformat() if valid_to else ""},
        "checks": check_rows,
        "errorCount": error_count,
        "ready": error_count == 0,
        "parameters": params,
        "finalPlan": final_plan or {},
    }


def _excel_date(value: Any) -> date | None:
    return parse_iso_date(value)


def _set_if(ws, cell: str, value: Any) -> None:
    if value is not None:
        ws[cell] = value



def fallback_lpdh_workbook() -> Workbook:
    """Formula-capable fallback in the same sheet order as the official workbook."""
    wb = Workbook()
    wb.active.title = "Petunjuk"
    for name in ["Identitas", "A_PM", "B_BahanBaku", "C_Operasional", "C1_Relawan", "D_Insentif", "E_Saldo", "F_TopUp", "G_CekPPK", "H_RekapPPK", "I_RegisterBukti", "J_Pengesahan", "Ref"]:
        wb.create_sheet(name)

    ws = wb["Petunjuk"]
    ws["A1"] = "LPDH SPPG"
    ws["A3"] = "Workbook fallback berformula. Unggah template resmi di Master Data untuk mempertahankan layout resmi persis."

    ws = wb["Identitas"]
    for row, label in [
        (5, "Nomor LPDH"), (6, "ID SPPG"), (7, "Nama SPPG"), (8, "Desa/Kelurahan"),
        (9, "Kecamatan"), (10, "Kabupaten/Kota"), (11, "Provinsi"), (12, "Yayasan"),
        (13, "Nomor VA"), (14, "Bank"), (15, "Tanggal Pelayanan"), (16, "Hari"),
        (17, "Minggu ke"), (18, "Status Hari"), (19, "HPE ke"), (20, "Dihitung HPE"),
        (21, "Indeks Kemahalan"), (22, "Sumber Indeks"), (25, "Tanggal Upload"),
        (26, "Jam Upload"), (27, "Deadline"), (28, "Status Upload"), (29, "Nama File"),
        (32, "Tanggal transaksi mulai"), (33, "Tanggal transaksi akhir"),
    ]:
        ws[f"A{row}"] = label
    ws["B16"] = '=IF(B15="","",CHOOSE(WEEKDAY(B15),"Minggu","Senin","Selasa","Rabu","Kamis","Jumat","Sabtu"))'
    ws["B17"] = '=IF(B15="","",INT((DAY(B15)-1)/7)+1)'
    ws["B20"] = '=IF(AND(INDEX(Ref!$B$34:$B$39,MATCH(B18,Ref!$A$34:$A$39,0))="Ya",B19>=1,B19<=Ref!$B$10),"Ya","Tidak")'
    ws["B21"] = '=IFERROR(INDEX(Ref!$C$64:$C$213,MATCH(B10,Ref!$B$64:$B$213,0)),1)'
    ws["B22"] = '=IFERROR(INDEX(Ref!$D$64:$D$213,MATCH(B10,Ref!$B$64:$B$213,0)),"Belum tercantum di Ref: dipakai 100%")'
    ws["B27"] = '=B15+1+TIME(Ref!$B$11,0,0)'
    ws["B28"] = '=IF(OR(B25="",B26=""),"Belum diunggah",IF(B25+B26<=B27,"Ya","Terlambat"))'
    ws["B29"] = '=B6&"_"&B7&"_LPDH_"&TEXT(B15,"yyyymmdd")'
    ws["B32"] = '=IF(B15="","",B15-Ref!B13)'
    ws["B33"] = '=B15'
    for offset, role in enumerate(["Disusun oleh: Pengawas Keuangan SPPG", "Mengetahui: Kepala SPPG", "Menyetujui: Perwakilan Mitra/Yayasan"]):
        rr = 36 + offset
        ws[f"A{rr}"] = role
        expected_len = 18 if rr == 37 else 16
        id_label = "NIP" if rr == 37 else "NIK"
        ws[f"C{rr}"] = id_label
        ws[f"E{rr}"] = f'=IF(D{rr}="","BELUM DIISI",IF(AND(LEN(D{rr})={expected_len},ISNUMBER(--D{rr})),"Valid","PERIKSA: {id_label} harus {expected_len} digit angka"))'

    ws = wb["A_PM"]
    headers = ["Kode","Kelompok Sasaran","Kategori Porsi","Jenis PIC","Target PM SPS","Didistribusikan POP","Diterima Fleet","Tidak Diterima","Alasan","Selisih","BNBA","No BAST","Link BAST","Status BAST","PM Dihitung","Capaian","Pagu Bahan Disesuaikan","Keterangan"]
    for col, header in enumerate(headers, 1):
        ws.cell(5, col, header)
    for rr, (code, label, portion, pic) in enumerate(GROUPS, 6):
        ws.cell(rr, 1, code); ws.cell(rr, 2, label); ws.cell(rr, 3, portion); ws.cell(rr, 4, pic)
        ws.cell(rr, 10, f"=F{rr}-G{rr}-H{rr}")
        ws.cell(rr, 14, f'=IF(G{rr}<=0,"Tidak wajib",IF(AND(L{rr}<>"",LEFT(M{rr},8)="https://"),"Terlampir","Belum lengkap"))')
        ws.cell(rr, 15, f'=IF(AND(Identitas!B20="Ya",K{rr}="Ya",N{rr}="Terlampir"),G{rr},0)')
        ws.cell(rr, 16, f'=IF(E{rr}=0,0,O{rr}/E{rr})')
        ws.cell(rr, 17, f'=IF(C{rr}="Kecil",Ref!B6,Ref!B7)*IF(Ref!B14="Ya",Identitas!B21,1)')
    for col in [5, 6, 7, 8, 10, 15]:
        ws.cell(16, col, f"=SUM({ws.cell(6,col).coordinate}:{ws.cell(15,col).coordinate})")
    ws["P16"] = '=IF(E16>0,O16/E16,"")'
    ws["Q16"] = '=IF(F16>0,SUMPRODUCT(F6:F15,Q6:Q15)/F16,0)'
    for cell, label in [("B19","Total Diproduksi"),("B20","Total Didistribusikan"),("B21","Organoleptik"),("B22","Retained Sample"),("B23","Tidak Didistribusikan"),("B24","Buffer"),("B25","Total Alokasi"),("B26","Selisih Produksi"),("B27","Buffer %")]:
        ws[cell] = label
    ws["C20"] = "=F16"; ws["C25"] = "=SUM(C20:C24)"; ws["C26"] = "=C19-C25"; ws["C27"] = '=IF(C19=0,0,C24/C19)'
    ws["B44"] = "PM Dihitung"; ws["C44"] = "=O16"
    ws["B45"] = "Organoleptik"; ws["C45"] = '=IF(Identitas!B20="Ya",C21,0)'
    ws["B46"] = "Retained Sample"; ws["C46"] = '=IF(Identitas!B20="Ya",C22,0)'
    ws["B47"] = "PM Dasar Insentif"; ws["C47"] = "=SUM(C44:C46)"
    ws["B50"] = "Kelompok sasaran yang menerima porsi"; ws["C50"] = '=COUNTIF(G6:G15,">0")'
    ws["B51"] = "Kelompok dengan bukti BAST ter-link"; ws["C51"] = '=COUNTIF(N6:N15,"Terlampir")'
    ws["B52"] = "Kelompok tanpa link bukti BAST"; ws["C52"] = "=C50-C51"

    ws = wb["B_BahanBaku"]
    headers = ["No","Kode Unik","Tanggal","Bahan","Kategori","Volume","Unit","Harga Satuan","Jumlah","Supplier","Nomor Bukti/Nota","Link Bukti","Status No","Status Tanggal","Catatan"]
    for col, header in enumerate(headers, 1):
        ws.cell(5, col, header)
    for rr in range(6, 46):
        ws.cell(rr, 1, rr - 5)
        ws.cell(rr, 2, f'=IF(D{rr}="","","ID-"&TEXT(C{rr},"yyyymmdd")&"-BB-"&TEXT(A{rr},"000"))')
        ws.cell(rr, 9, f'=IFERROR(F{rr}*H{rr},0)')
        ws.cell(rr, 13, f'=IF(K{rr}="","BELUM ADA",IF(COUNTIF($K$6:$K$45,K{rr})=1,"UNIK","DUPLIKAT"))')
        ws.cell(rr, 14, f'=IF(I{rr}=0,"OK",IF(AND(C{rr}>=Identitas!B32,C{rr}<=Identitas!B33),"OK","PERIKSA"))')
    ws["H46"] = "TOTAL"; ws["I46"] = "=SUM(I6:I45)"
    ws["H49"] = "Porsi diproduksi"; ws["I49"] = "=A_PM!C19"
    ws["H50"] = "Biaya/porsi"; ws["I50"] = '=IF(I49=0,0,I46/I49)'
    ws["H51"] = "Pagu/porsi"; ws["I51"] = '=A_PM!Q16'
    ws["H52"] = "Status"; ws["I52"] = '=IF(I50<=I51,"Dalam pagu","Melebihi pagu: jelaskan")'

    ws = wb["C_Operasional"]
    headers = ["No","Kode Unik","Tanggal","Uraian","Volume","Unit","Harga Satuan","Jumlah","Nomor Bukti","Link Bukti","Status No","Status Tanggal","Catatan"]
    for col, header in enumerate(headers, 1):
        ws.cell(5, col, header)
    for rr, item_name in enumerate(OPERATIONAL_DEFAULTS, 6):
        ws.cell(rr, 1, rr - 5); ws.cell(rr, 4, item_name)
        if rr == 6:
            ws.cell(rr, 2, "Lihat C1_Relawan")
            ws.cell(rr, 3, '=IF(H6>0,Identitas!B15,"")')
            ws.cell(rr, 5, "='C1_Relawan'!C66")
            ws.cell(rr, 6, "orang")
            ws.cell(rr, 8, "='C1_Relawan'!H66")
            ws.cell(rr, 9, "Per orang di C1_Relawan")
            ws.cell(rr, 10, "Per orang di C1_Relawan")
            ws.cell(rr, 11, '=IF(COUNTIF(\'C1_Relawan\'!L6:L65,"DUPLIKAT")>0,"DUPLIKAT","Lihat C1")')
            ws.cell(rr, 12, '=IF(COUNTIF(\'C1_Relawan\'!M6:M65,"DI LUAR PERIODE")>0,"DI LUAR PERIODE","Lihat C1")')
        else:
            ws.cell(rr, 2, f'=IF(I{rr}="","",Identitas!$B$6&"-"&TEXT(Identitas!$B$15,"yyyymmdd")&"-OP-"&TEXT(A{rr},"000"))')
            ws.cell(rr, 8, f'=IF(OR(E{rr}="",G{rr}=""),0,E{rr}*G{rr})')
            ws.cell(rr, 11, f'=IF(I{rr}="","",IF(COUNTIF(I_RegisterBukti!$C$5:$C$130,I{rr})>1,"DUPLIKAT","Unik"))')
            ws.cell(rr, 12, f'=IF(I{rr}="","",IF(C{rr}="","TANGGAL KOSONG",IF(AND(C{rr}>=Identitas!$B$32,C{rr}<=Identitas!$B$33),"Sesuai","DI LUAR PERIODE")))')
    ws["G22"] = "TOTAL"; ws["H22"] = "=SUM(H6:H21)"
    ws["G25"] = "PM Dihitung"; ws["H25"] = "=A_PM!C47"
    ws["G26"] = "Operasional/PM"; ws["H26"] = '=IF(H25=0,0,H22/H25)'
    ws["G27"] = "Pagu/PM"; ws["H27"] = '=Ref!B8*IF(Ref!B15="Ya",Identitas!B21,1)'
    ws["G28"] = "Status"; ws["H28"] = '=IF(H26<=H27,"Dalam pagu","Melebihi pagu: jelaskan")'

    ws = wb["C1_Relawan"]
    headers = ["No","Kode Unik","Nama Relawan","Tugas","Tanggal Pembayaran","Hari Kerja","Besaran Harian","Jumlah Diterima","Metode Bayar","No Bukti Pembayaran","Link Bukti","Status No","Status Tanggal","Status Bukti"]
    for col, header in enumerate(headers, 1):
        ws.cell(5, col, header)
    for rr in range(6, 66):
        ws.cell(rr, 1, rr - 5)
        ws.cell(rr, 2, f'=IF(C{rr}="","","ID-"&TEXT(E{rr},"yyyymmdd")&"-RL-"&TEXT(A{rr},"000"))')
        ws.cell(rr, 8, f'=IF(OR(F{rr}="",G{rr}=""),0,F{rr}*G{rr})')
        ws.cell(rr, 12, f'=IF(J{rr}="","",IF(COUNTIF(I_RegisterBukti!$C$5:$C$130,J{rr})>1,"DUPLIKAT","Unik"))')
        ws.cell(rr, 13, f'=IF(C{rr}="","",IF(E{rr}="","TANGGAL KOSONG",IF(AND(E{rr}>=Identitas!$B$32,E{rr}<=Identitas!$B$33),"Sesuai","DI LUAR PERIODE")))')
        ws.cell(rr, 14, f'=IF(N(H{rr})=0,"",IF(AND(J{rr}<>"",LEFT(K{rr},8)="https://"),"Lengkap","BELUM LENGKAP"))')
    ws["A66"] = "JUMLAH"; ws["C66"] = '=COUNTIF(H6:H65,">0")'; ws["H66"] = "=SUM(H6:H65)"

    ws = wb["D_Insentif"]
    labels = {
        5:"Hari berstatus HPE (Identitas)",6:"Terjadi kontaminasi makanan/gagal penyaluran",
        7:"Terjadi kejadian fatal (keracunan)",8:"SPPG dalam status suspend",
        9:"Hasil verifikasi ketersediaan dan mutu layanan memenuhi",
        10:"Data penerima manfaat telah diinput pada SIPGN",11:"Insentif dapat diberikan",
        14:"PM dihitung (A_PM)",15:"Tarif per PM per HPE (Rp)",16:"Insentif dihitung hari ini (Rp)",
        19:"Nomor pernyataan besaran Insentif dari PPK",20:"Nilai pernyataan PPK (Rp)",
        21:"Nominal Insentif dibayarkan hari ini (Rp)",22:"Tanggal pembayaran",
        23:"Nomor bukti pembayaran (unik)",24:"Nomor kuitansi",
        25:"Kuitansi ditandatangani Mitra (Ya/Tidak)",26:"Link PDF bukti bayar (Cloud SIPGN)",
        27:"Referensi transaksi VA (maker: Mitra; approver: Kepala SPPG)",28:"Kode unik transaksi (otomatis)",
        31:"Selisih pembayaran thd pernyataan PPK (Rp)",32:"Status nomor bukti",
        33:"Status tanggal pembayaran",34:"Status bukti autentik (nomor bukti, kuitansi bertanda tangan, link PDF)",
    }
    for rr, label in labels.items():
        ws[f"A{rr}"] = label
    ws["B5"] = "=Identitas!B20"; ws["C5"] = '=IF(B5="Ya","Ya","Tidak")'
    for rr in (6,7,8):
        ws[f"C{rr}"] = f'=IF(B{rr}="Tidak","Ya","Tidak")'
    for rr in (9,10):
        ws[f"C{rr}"] = f'=IF(B{rr}="Ya","Ya","Tidak")'
    ws["C11"] = '=IF(COUNTIF(C5:C10,"Tidak")=0,"Ya","Tidak")'
    ws["C14"] = "=A_PM!C47"; ws["C15"] = "=Ref!B5"; ws["C16"] = '=IF(C11="Ya",C14*C15,0)'
    ws["C28"] = '=IF(C23="","",Identitas!$B$6&"-"&TEXT(Identitas!$B$15,"yyyymmdd")&"-INS-001")'
    ws["C31"] = "=C21-C20"
    ws["C32"] = '=IF(C23="","",IF(COUNTIF(I_RegisterBukti!$C$5:$C$130,C23)>1,"DUPLIKAT","Unik"))'
    ws["C33"] = '=IF(N(C21)=0,"",IF(C22="","TANGGAL KOSONG",IF(AND(C22>=Identitas!$B$32,C22<=Identitas!$B$33),"Sesuai","DI LUAR PERIODE")))'
    ws["C34"] = '=IF(N(C21)=0,"",IF(AND(C23<>"",C24<>"",C25="Ya",LEFT(C26,8)="https://"),"Lengkap","BELUM LENGKAP"))'

    ws = wb["E_Saldo"]
    for rr, label in [(5,"Bahan Baku"),(6,"Operasional"),(7,"Insentif")]:
        ws[f"A{rr}"] = label; ws[f"E{rr}"] = f"=B{rr}+C{rr}-D{rr}"
    ws["A8"] = "TOTAL"; ws["B8"] = "=SUM(B5:B7)"; ws["C8"] = "=SUM(C5:C7)"; ws["D8"] = "=SUM(D5:D7)"; ws["E8"] = "=SUM(E5:E7)"
    ws["D5"] = "=B_BahanBaku!I46"; ws["D6"] = "=C_Operasional!H22"; ws["D7"] = "=D_Insentif!C21"
    ws["A10"] = "Saldo VA"; ws["A11"] = "Selisih"; ws["E11"] = '=IF(E10="","",E8-E10)'
    top_headers = ["No","Kode","Tanggal","SP2D/Ref","TopUp Bahan","TopUp Operasional","TopUp Insentif","Total","No Kuitansi","Link Bukti","Status No","Status Tanggal","Status Bukti"]
    for col, header in enumerate(top_headers, 1):
        ws.cell(18, col, header)
    for rr in range(19, 24):
        ws.cell(rr, 1, rr - 18)
        ws.cell(rr, 2, f'=IF(D{rr}="","","TU-"&TEXT(C{rr},"yyyymmdd")&"-"&TEXT(A{rr},"000"))')
        ws.cell(rr, 8, f"=SUM(E{rr}:G{rr})")
        ws.cell(rr, 11, f'=IF(I{rr}="","BELUM ADA",IF(COUNTIF($I$19:$I$23,I{rr})=1,"UNIK","DUPLIKAT"))')
        ws.cell(rr, 12, f'=IF(H{rr}=0,"OK",IF(AND(C{rr}>=Identitas!B32,C{rr}<=Identitas!B33),"OK","PERIKSA"))')
        ws.cell(rr, 13, f'=IF(H{rr}=0,"OK",IF(AND(I{rr}<>"",LEFT(J{rr},8)="https://"),"LENGKAP","PERIKSA"))')
    ws["D24"] = "TOTAL"; ws["E24"] = "=SUM(E19:E23)"; ws["F24"] = "=SUM(F19:F23)"; ws["G24"] = "=SUM(G19:G23)"; ws["H24"] = "=SUM(H19:H23)"
    ws["C5"] = "=E24"; ws["C6"] = "=F24"; ws["C7"] = "=G24"

    ws = wb["F_TopUp"]
    for rr, label in [(5,"Bahan Baku"),(6,"Operasional"),(7,"Insentif")]:
        ws[f"A{rr}"] = label
    ws["B5"] = "=B_BahanBaku!I46"; ws["B6"] = "=C_Operasional!H22"; ws["B7"] = "=D_Insentif!C16"; ws["B8"] = "=SUM(B5:B7)"
    ws["B10"] = "Ruang VA"; ws["C10"] = "=MAX(0,Ref!B9-E_Saldo!E8)"; ws["B11"] = "Status"; ws["C11"] = '=IF(B8<=C10,"Ya","Melebihi batas: sesuaikan")'

    ws = wb["I_RegisterBukti"]
    for col, header in enumerate(["Sumber","Kode","Nomor Bukti","Tanggal","Nilai","Link","Status No","Status Tanggal"], 1):
        ws.cell(4, col, header)
    for rr in range(5, 126):
        ws[f"G{rr}"] = f'=IF(C{rr}="","BELUM ADA",IF(COUNTIF($C$5:$C$125,C{rr})=1,"UNIK","DUPLIKAT"))'
        ws[f"H{rr}"] = f'=IF(E{rr}=0,"OK",IF(AND(D{rr}>=Identitas!B32,D{rr}<=Identitas!B33),"OK","PERIKSA"))'
    ws["B127"] = "Jumlah duplikat"; ws["C127"] = '=COUNTIF(G5:G125,"DUPLIKAT")'
    ws["B128"] = "Tanggal di luar periode"; ws["C128"] = '=COUNTIF(H5:H125,"PERIKSA")'
    ws["B129"] = "Bukti belum lengkap"; ws["C129"] = '=COUNTIFS(E5:E125,">0",F5:F125,"<>https://*")'

    ws = wb["G_CekPPK"]
    check_labels = [
        "Identitas wajib lengkap","Hari pelayanan efektif / batas HPE","Produksi seimbang","POP dan Fleet seimbang",
        "Alasan tidak diterima lengkap","Buffer sesuai ambang","BNBA & BAST lengkap","Link BAST valid",
        "PM tidak melebihi target","Indeks kemahalan tersedia","Bahan/porsi dalam pagu","Operasional/PM dalam pagu",
        "Bukti transaksi terlampir","Nomor bukti unik","Tanggal transaksi sesuai periode","Bukti relawan lengkap",
        "Syarat insentif terpenuhi","Hitung insentif sesuai","Pembayaran insentif sesuai PPK","Bukti insentif lengkap",
        "Bukti TopUp lengkap","Saldo komponen tidak negatif","Saldo komponen = VA","Tiga pengesah lengkap",
        "Upload H+1 tepat waktu","TopUp <= plafon VA",
    ]
    check_formulas = [
        '=IF(COUNTA(Identitas!B6,Identitas!B7,Identitas!B13,Identitas!B15)=4,"OK","PERIKSA")',
        '=IF(Identitas!B20="Ya","OK","PERIKSA")',
        '=IF(ABS(A_PM!C26)<0.0001,"OK","PERIKSA")',
        '=IF(COUNTIF(A_PM!J6:J15,"<>0")=0,"OK","PERIKSA")',
        '=IF(COUNTIFS(A_PM!H6:H15,">0",A_PM!I6:I15,"")=0,"OK","PERIKSA")',
        '=IF(Ref!B12="","BELUM DITETAPKAN",IF(A_PM!C27<=Ref!B12,"OK","PERIKSA"))',
        '=IF(SUMPRODUCT((A_PM!G6:G15>0)*((A_PM!K6:K15<>"Ya")+(A_PM!L6:L15="")>0))=0,"OK","PERIKSA")',
        '=IF(A_PM!C52=0,"OK","PERIKSA")',
        '=IF(SUMPRODUCT(--(A_PM!O6:O15>A_PM!E6:E15))=0,"OK","PERIKSA")',
        '=IF(ISNUMBER(MATCH(Identitas!B10,Ref!$B$64:$B$213,0)),"OK","PERIKSA")',
        '=IF(B_BahanBaku!I50<=B_BahanBaku!I51,"OK","PERIKSA")',
        '=IF(C_Operasional!H26<=C_Operasional!H27,"OK","PERIKSA")',
        '=IF(I_RegisterBukti!C129=0,"OK","PERIKSA")',
        '=IF(I_RegisterBukti!C127=0,"OK","PERIKSA")',
        '=IF(I_RegisterBukti!C128=0,"OK","PERIKSA")',
        '=IF(COUNTIF(\'C1_Relawan\'!N6:N65,"BELUM LENGKAP")=0,"OK","PERIKSA")',
        '=IF(D_Insentif!C11="Ya","OK","PERIKSA")',
        '=IF(D_Insentif!C16=D_Insentif!C14*D_Insentif!C15,"OK","PERIKSA")',
        '=IF(D_Insentif!C31=0,"OK","PERIKSA")',
        '=IF(OR(N(D_Insentif!C21)=0,D_Insentif!C34="Lengkap"),"OK","PERIKSA")',
        '=IF(COUNTIF(E_Saldo!M19:M23,"BELUM LENGKAP")=0,"OK","PERIKSA")',
        '=IF(MIN(E_Saldo!E5:E7)>=0,"OK","PERIKSA")',
        '=IF(E_Saldo!E10="","PERIKSA",IF(ABS(E_Saldo!E11)<1,"OK","PERIKSA"))',
        '=IF(AND(COUNTIF(Identitas!F36:F38,"Ya")=3,COUNTIF(Identitas!E36:E38,"Valid")=3,COUNTBLANK(Identitas!B36:B38)=0),"OK","PERIKSA")',
        '=IF(Identitas!B28="Ya","OK","PERIKSA")',
        '=IF(F_TopUp!C11="Ya","OK","PERIKSA")',
    ]
    for rr, (label, formula) in enumerate(zip(check_labels, check_formulas), 5):
        ws[f"A{rr}"] = rr - 4
        ws[f"B{rr}"] = label
        ws[f"C{rr}"] = formula
    ws["B32"] = "Jumlah PERIKSA"; ws["C32"] = '=COUNTIF(C5:C30,"PERIKSA")'
    ws["B33"] = "KESIMPULAN"; ws["C33"] = '=IF(C32=0,"LENGKAP: DAPAT DIPROSES","PERLU PERBAIKAN")'

    ws = wb["H_RekapPPK"]
    ws["A1"] = "REKAP PPK"; ws["A3"] = "Tanggal"; ws["B3"] = "=Identitas!B15"; ws["A4"] = "SPPG"; ws["B4"] = "=Identitas!B7"
    ws["A5"] = "Total Bahan"; ws["B5"] = "=B_BahanBaku!I46"; ws["A6"] = "Total Operasional"; ws["B6"] = "=C_Operasional!H22"
    ws["A7"] = "Insentif"; ws["B7"] = "=D_Insentif!C16"; ws["A8"] = "Status Validasi"; ws["B8"] = "=G_CekPPK!C33"

    ws = wb["J_Pengesahan"]
    ws["A1"] = "LEMBAR PENGESAHAN LPDH"; ws["A3"] = "SPPG"; ws["B3"] = "=Identitas!B7"; ws["A4"] = "Tanggal"; ws["B4"] = "=Identitas!B15"
    ws["A6"] = "Total Bahan"; ws["B6"] = "=B_BahanBaku!I46"; ws["A7"] = "Total Operasional"; ws["B7"] = "=C_Operasional!H22"; ws["A8"] = "Insentif"; ws["B8"] = "=D_Insentif!C16"

    ws = wb["Ref"]
    for rr, (label, value) in enumerate([
        ("Tarif Insentif",2000),("Pagu Bahan Kecil",8000),("Pagu Bahan Besar",10000),("Pagu Operasional/PM",3000),
        ("Maks VA",500000000),("Maks HPE/Minggu",5),("Jam Upload H+1",6),("Buffer %",None),("Toleransi Tanggal",1),
        ("Indeks Bahan","Ya"),("Indeks Operasional","Ya"),
    ], 5):
        ws[f"A{rr}"] = label; ws[f"B{rr}"] = value
    for rr, (status, counted) in enumerate([
        ("HPE","Ya"),
        ("Libur nasional/cuti bersama","Tidak"),
        ("Libur sekolah/libur khusus daerah","Tidak"),
        ("Tanpa pembelajaran tatap muka","Tidak"),
        ("Kondisi tertentu (pemda/BGN)","Tidak"),
        ("Melebihi 5 hari dalam seminggu","Tidak"),
    ], 34):
        ws[f"A{rr}"] = status; ws[f"B{rr}"] = counted
    ws["A64"] = "Provinsi"; ws["B64"] = "Kabupaten/Kota"; ws["C64"] = "Indeks Kemahalan Harga"; ws["D64"] = "Sumber dan Tahun Penetapan"
    return wb


def load_lpdh_workbook(template_bytes: bytes | None = None) -> Workbook:
    if template_bytes:
        return load_workbook(io.BytesIO(template_bytes), data_only=False)
    if LPDH_TEMPLATE.is_file():
        return load_workbook(LPDH_TEMPLATE, data_only=False)
    return fallback_lpdh_workbook()


def populate_workbook(
    masters: dict[str, Any],
    daily: dict[str, Any],
    preview: dict[str, Any],
    service_date: str,
    template_bytes: bytes | None = None,
) -> bytes:
    using_official_template = bool(template_bytes or LPDH_TEMPLATE.is_file())
    wb = load_lpdh_workbook(template_bytes)
    try:
        wb.calculation.calcMode = "auto"
        wb.calculation.fullCalcOnLoad = True
        wb.calculation.forceFullCalc = True
    except Exception:
        pass

    identity = masters.get("identity") or {}
    ws = wb["Identitas"]
    identity_cells = {
        "B5": identity.get("lpdhNumber"),
        "B6": identity.get("sppgId"),
        "B7": identity.get("sppgName"),
        "B8": identity.get("village"),
        "B9": identity.get("district"),
        "B10": identity.get("city"),
        "B11": identity.get("province"),
        "B12": identity.get("foundation"),
        "B13": identity.get("vaNumber"),
        "B14": identity.get("bankName"),
        "B15": _excel_date(service_date),
        "B18": daily.get("dayStatus") or "HPE",
        "B19": as_int(daily.get("hpeNumber"), 1),
        "B25": _excel_date((daily.get("upload") or {}).get("date")),
        "B26": parse_time((daily.get("upload") or {}).get("time")),
    }
    for cell, value in identity_cells.items():
        _set_if(ws, cell, value)
    signers = masters.get("signers") or []
    for offset in range(3):
        if offset >= len(signers):
            continue
        signer = signers[offset]
        row = 36 + offset
        _set_if(ws, f"B{row}", signer.get("name"))
        _set_if(ws, f"C{row}", signer.get("identityType"))
        _set_if(ws, f"D{row}", signer.get("identityNumber"))
        _set_if(ws, f"F{row}", "Ya" if yes(signer.get("signed")) else "Tidak")

    ref = wb["Ref"]
    params = preview["parameters"]
    ref_values = {
        "B5": as_number(params.get("incentiveTariff"), 2000),
        "B6": as_number(params.get("rawSmall"), 8000),
        "B7": as_number(params.get("rawLarge"), 10000),
        "B8": as_number(params.get("operationalPerPm"), 3000),
        "B9": as_number(params.get("maxVa"), 500_000_000),
        "B10": as_int(params.get("maxHpePerWeek"), 5),
        "B11": as_int(params.get("uploadHour"), 6),
        "B12": None if params.get("bufferPct") in (None, "") else as_number(params.get("bufferPct")),
        "B13": as_int(params.get("dateTolerance"), 1),
        "B14": "Ya" if params.get("applyIndexRaw", True) else "Tidak",
        "B15": "Ya" if params.get("applyIndexOp", True) else "Tidak",
    }
    for cell, value in ref_values.items():
        _set_if(ref, cell, value)

    city_name = str(identity.get("city") or "").strip()
    province_name = str(identity.get("province") or "").strip()
    if city_name:
        city_row = None
        for rr in range(64, 214):
            if str(ref.cell(rr, 2).value or "").strip().lower() == city_name.lower():
                city_row = rr
                break
        if city_row is None:
            for rr in range(64, 214):
                if not str(ref.cell(rr, 2).value or "").strip():
                    city_row = rr
                    break
        if city_row is not None:
            ref.cell(city_row, 1, province_name)
            ref.cell(city_row, 2, city_name)
            ref.cell(city_row, 3, as_number(params.get("cityIndex"), 1.0) or 1.0)
            ref.cell(city_row, 4, str(params.get("cityIndexSource") or "Master LPDH"))

    pm_ws = wb["A_PM"]
    for idx, row_data in enumerate(preview["pmRows"], start=6):
        _set_if(pm_ws, f"E{idx}", row_data["targetPm"])
        _set_if(pm_ws, f"F{idx}", row_data["distributed"])
        _set_if(pm_ws, f"G{idx}", row_data["received"])
        _set_if(pm_ws, f"H{idx}", row_data["notReceived"])
        _set_if(pm_ws, f"I{idx}", row_data["reason"])
        _set_if(pm_ws, f"K{idx}", row_data["bnba"])
        _set_if(pm_ws, f"L{idx}", row_data["bastNo"])
        _set_if(pm_ws, f"M{idx}", row_data["bastLink"])
    prod = preview["production"]
    for cell, value in {
        "C19": prod["produced"], "C21": prod["organoleptic"], "C22": prod["retainedSample"],
        "C23": prod["notDistributed"], "C24": prod["buffer"],
    }.items():
        _set_if(pm_ws, cell, value)

    raw_ws = wb["B_BahanBaku"]
    raw_numbered = assign_document_numbers(preview["rawMaterials"], "invoiceNo")
    for i, item in enumerate(raw_numbered[:40], start=6):
        for col, value in {
            "C": _excel_date(item.get("date")), "D": item.get("name"), "E": item.get("category"),
            "F": as_number(item.get("qty")), "G": item.get("unit"), "H": as_number(item.get("price")),
            "J": item.get("supplier"), "K": item.get("proofNoDerived") or item.get("_baseProofNo") or "",
            "L": item.get("evidenceLink"), "O": item.get("note"),
        }.items():
            _set_if(raw_ws, f"{col}{i}", value)

    op_ws = wb["C_Operasional"]
    op_rows = preview["operations"]
    op_numbered = assign_document_numbers(op_rows, "invoiceNo")
    by_name = {str(x.get("description") or "").strip().lower(): x for x in op_numbered}

    school_rows = [
        x for x in preview["incentiveRecipients"]
        if str(x.get("type") or "").strip().lower() in {"guru", "sekolah", "penanggung jawab satuan pendidikan"}
    ]
    cadre_rows = [
        x for x in preview["incentiveRecipients"]
        if str(x.get("type") or "").strip().lower() in {"kader", "posyandu", "kader posyandu"}
    ]
    incentive_base = str(daily.get("incentiveReceiptBaseNo") or "").strip()
    special_rows = {
        7: {
            "description": OPERATIONAL_DEFAULTS[1],
            "qty": len(school_rows),
            "unit": "satuan",
            "amount": sum(as_number(x.get("amount")) for x in school_rows),
            "date": daily.get("incentivePaymentDate") or service_date,
            "proofNo": str(daily.get("schoolPicOperationalProofNo") or (f"{incentive_base}-GURU" if incentive_base and school_rows else "")).strip(),
            "evidenceLink": daily.get("incentiveBatchEvidenceLink") or "",
            "note": f"Kuitansi individual: {len(school_rows)} lembar" if school_rows else "",
        },
        8: {
            "description": OPERATIONAL_DEFAULTS[2],
            "qty": len(cadre_rows),
            "unit": "orang",
            "amount": sum(as_number(x.get("amount")) for x in cadre_rows),
            "date": daily.get("incentivePaymentDate") or service_date,
            "proofNo": str(daily.get("cadreOperationalProofNo") or (f"{incentive_base}-KADER" if incentive_base and cadre_rows else "")).strip(),
            "evidenceLink": daily.get("incentiveBatchEvidenceLink") or "",
            "note": f"Kuitansi individual: {len(cadre_rows)} lembar" if cadre_rows else "",
        },
    }

    for pos, default_name in enumerate(OPERATIONAL_DEFAULTS, start=6):
        if pos == 6:
            # Official workbook row 6 is driven entirely by C1_Relawan formulas.
            continue
        if pos in special_rows:
            item = special_rows[pos]
            if item["qty"] <= 0 and item["amount"] <= 0:
                continue
            price = (item["amount"] / item["qty"]) if item["qty"] else 0
            _set_if(op_ws, f"C{pos}", _excel_date(item.get("date")))
            _set_if(op_ws, f"D{pos}", item.get("description"))
            _set_if(op_ws, f"E{pos}", item.get("qty"))
            _set_if(op_ws, f"F{pos}", item.get("unit"))
            _set_if(op_ws, f"G{pos}", price)
            _set_if(op_ws, f"I{pos}", item.get("proofNo"))
            _set_if(op_ws, f"J{pos}", item.get("evidenceLink"))
            _set_if(op_ws, f"M{pos}", item.get("note"))
            continue

        item = by_name.get(default_name.lower())
        if not item:
            continue
        _set_if(op_ws, f"C{pos}", _excel_date(item.get("date")))
        _set_if(op_ws, f"D{pos}", default_name)
        _set_if(op_ws, f"E{pos}", as_number(item.get("qty")))
        _set_if(op_ws, f"F{pos}", item.get("unit"))
        _set_if(op_ws, f"G{pos}", as_number(item.get("price")))
        _set_if(op_ws, f"I{pos}", item.get("proofNoDerived") or item.get("_baseProofNo") or "")
        _set_if(op_ws, f"J{pos}", item.get("evidenceLink"))
        _set_if(op_ws, f"M{pos}", item.get("note"))

    rel_ws = wb["C1_Relawan"]
    volunteer_numbered = []
    volunteer_base = str(daily.get("volunteerReceiptBaseNo") or "")
    for x in preview["volunteers"]:
        y = deepcopy(x)
        y["receiptBase"] = y.get("receiptNo") or volunteer_base
        volunteer_numbered.append(y)
    volunteer_numbered = assign_document_numbers(volunteer_numbered, "receiptBase")
    for i, item in enumerate(volunteer_numbered[:60], start=6):
        _set_if(rel_ws, f"C{i}", item.get("name"))
        _set_if(rel_ws, f"D{i}", item.get("role"))
        _set_if(rel_ws, f"E{i}", _excel_date(item.get("date")))
        _set_if(rel_ws, f"F{i}", as_number(item.get("workDays")))
        _set_if(rel_ws, f"G{i}", as_number(item.get("dailyRate")))
        _set_if(rel_ws, f"I{i}", item.get("paymentMethod"))
        _set_if(rel_ws, f"J{i}", item.get("proofNoDerived") or item.get("_baseProofNo") or "")
        _set_if(rel_ws, f"K{i}", item.get("evidenceLink"))

    ins_ws = wb["D_Insentif"]
    incentive = daily.get("incentive") or {}
    elig = incentive.get("eligibility") or {}
    # Rows 6-10 are the editable eligibility questions in the official template.
    for cell, value in {
        "B6": "Ya" if yes(elig.get("contamination")) else "Tidak",
        "B7": "Ya" if yes(elig.get("fatalIncident")) else "Tidak",
        "B8": "Ya" if yes(elig.get("suspended")) else "Tidak",
        "B9": "Ya" if yes(elig.get("verified")) else "Tidak",
        "B10": "Ya" if yes(elig.get("pmInputSipgn")) else "Tidak",
        "C19": incentive.get("ppkStatementNo"),
        "C20": as_number(incentive.get("statementAmount")),
        "C21": as_number(incentive.get("paidAmount")),
        "C22": _excel_date(incentive.get("paymentDate")),
        "C23": incentive.get("proofNo"),
        "C24": incentive.get("receiptNo"),
        "C25": "Ya" if yes(incentive.get("receiptSigned")) else "Tidak",
        "C26": incentive.get("evidenceLink"),
        "C27": incentive.get("vaReference"),
    }.items():
        _set_if(ins_ws, cell, value)

    saldo_ws = wb["E_Saldo"]
    bal = daily.get("balance") or {}
    for cell, value in {
        "B5": as_number(bal.get("openingRaw")), "B6": as_number(bal.get("openingOperational")),
        "B7": as_number(bal.get("openingIncentive")), "E10": as_number(bal.get("bankBalance")),
    }.items():
        _set_if(saldo_ws, cell, value)
    for idx, item in enumerate((daily.get("topups") or [])[:5], start=19):
        for col, value in {
            "C": _excel_date(item.get("date")), "D": item.get("reference"),
            "E": as_number(item.get("rawAmount")), "F": as_number(item.get("operationalAmount")),
            "G": as_number(item.get("incentiveAmount")), "I": item.get("receiptNo"),
            "J": item.get("evidenceLink"),
        }.items():
            _set_if(saldo_ws, f"{col}{idx}", value)

    if not using_official_template:
        register_ws = wb["I_RegisterBukti"]
        for idx, item in enumerate(preview.get("register") or [], start=5):
            if idx > 125:
                break
            for col, value in {
                "A": item.get("source"), "B": item.get("code"), "C": item.get("proofNo"),
                "D": _excel_date(item.get("date")), "E": as_number(item.get("amount")),
                "F": item.get("link"),
            }.items():
                _set_if(register_ws, f"{col}{idx}", value)

        check_ws = wb["G_CekPPK"]
        for idx, item in enumerate(preview.get("checks") or [], start=5):
            if idx > 30:
                break
            check_ws[f"D{idx}"] = item.get("detail")

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def make_master_template() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Petunjuk"
    ws.append(["TEMPLATE IMPORT MASTER LPDH"])
    ws.append(["Isi sheet Master_Penerima, Master_Relawan, Master_Operasional, lalu upload ke aplikasi. Jangan ubah nama kolom."])

    pm = wb.create_sheet("Master_Penerima")
    pm.append(["Kode Unit","Jenis Unit","Nama Sekolah / Posyandu","Kode Kelompok","Kelompok Sasaran","Kategori Porsi","Jenis PIC","Target PM","Nama PIC","No. HP PIC","Alamat","Status Aktif","Catatan"])
    pm.append(["SKL-001","Sekolah","SD Contoh 01","KS-02","SD/MI Kelas 1–3","Kecil","Sekolah",220,"Nama PIC","081234567890","Alamat","Aktif",""])

    rv = wb.create_sheet("Master_Relawan")
    rv.append(["Kode Relawan","Nama Relawan","Tugas","Status Aktif","Besaran Harian (Rp)","Metode Bayar Default","Nama Bank","No. Rekening","Nama Pemilik Rekening","No. HP","Catatan"])
    rv.append(["RL-001","Contoh Relawan","Juru masak","Aktif",90000,"Transfer","BRI","1234567890","Contoh Relawan","081234567890",""])

    op = wb.create_sheet("Master_Operasional")
    op.append(["Kode Item","Nama Item Operasional","Kategori","Satuan Default","Harga Default (Rp)","Sifat Biaya","Vendor Default","Status Aktif","Catatan"])
    for idx, name in enumerate(OPERATIONAL_DEFAULTS[3:], 1):
        op.append([f"OP-{idx:03d}", name, "Operasional", "unit", 0, "Rutin", "", "Aktif", ""])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def parse_master_workbook(content: bytes) -> dict[str, list[dict[str, Any]]]:
    wb = load_workbook(io.BytesIO(content), data_only=True)
    result: dict[str, list[dict[str, Any]]] = {"beneficiaries": [], "volunteers": [], "operations": []}

    def records(sheet_name: str) -> list[dict[str, Any]]:
        if sheet_name not in wb.sheetnames:
            return []
        ws = wb[sheet_name]
        headers = [str(cell.value or "").strip() for cell in ws[1]]
        out = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not any(value not in (None, "") for value in row):
                continue
            out.append({headers[idx]: value for idx, value in enumerate(row) if idx < len(headers) and headers[idx]})
        return out

    for row in records("Master_Penerima"):
        result["beneficiaries"].append({
            "code": str(row.get("Kode Unit") or "").strip(),
            "unitType": str(row.get("Jenis Unit") or "").strip(),
            "unitName": str(row.get("Nama Sekolah / Posyandu") or "").strip(),
            "groupCode": str(row.get("Kode Kelompok") or "").strip().upper(),
            "groupName": str(row.get("Kelompok Sasaran") or "").strip(),
            "portionCategory": str(row.get("Kategori Porsi") or "").strip(),
            "picType": str(row.get("Jenis PIC") or "").strip(),
            "targetPm": as_number(row.get("Target PM")),
            "picName": str(row.get("Nama PIC") or "").strip(),
            "phone": str(row.get("No. HP PIC") or "").strip(),
            "address": str(row.get("Alamat") or "").strip(),
            "status": str(row.get("Status Aktif") or "Aktif").strip(),
            "note": str(row.get("Catatan") or "").strip(),
        })

    volunteer_sheet = "Master_Relawan" if "Master_Relawan" in wb.sheetnames else "Import_Relawan"
    for row in records(volunteer_sheet):
        result["volunteers"].append({
            "code": str(row.get("Kode Relawan") or "").strip(),
            "name": str(row.get("Nama Relawan") or "").strip(),
            "role": str(row.get("Tugas") or "").strip(),
            "status": str(row.get("Status Aktif") or "Aktif").strip(),
            "dailyRate": as_number(row.get("Besaran Harian (Rp)")),
            "paymentMethod": str(row.get("Metode Bayar Default") or "").strip(),
            "bankName": str(row.get("Nama Bank") or "").strip(),
            "accountNumber": str(row.get("No. Rekening") or "").strip(),
            "accountName": str(row.get("Nama Pemilik Rekening") or "").strip(),
            "phone": str(row.get("No. HP") or "").strip(),
            "note": str(row.get("Catatan") or "").strip(),
        })

    for row in records("Master_Operasional"):
        result["operations"].append({
            "code": str(row.get("Kode Item") or "").strip(),
            "name": str(row.get("Nama Item Operasional") or "").strip(),
            "category": str(row.get("Kategori") or "").strip(),
            "unit": str(row.get("Satuan Default") or "").strip(),
            "defaultPrice": as_number(row.get("Harga Default (Rp)")),
            "costNature": str(row.get("Sifat Biaya") or "").strip(),
            "vendor": str(row.get("Vendor Default") or "").strip(),
            "status": str(row.get("Status Aktif") or "Aktif").strip(),
            "note": str(row.get("Catatan") or "").strip(),
        })

    return result


def workbook_reference_rows() -> list[list[Any]]:
    wb = load_lpdh_workbook()
    ws = wb["Ref"]
    rows = []
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=min(ws.max_column, 4), values_only=True):
        rows.append(list(row))
    return rows


def encode_bytes(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")
