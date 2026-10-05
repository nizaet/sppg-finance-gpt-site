"""Read-only suggestions and durable numeric-prefix claims for daily documents."""
from __future__ import annotations

import re

from fastapi import HTTPException


PREFIX = re.compile(r"^([0-9]+)/(.+)$")


def split_number(value):
    match = PREFIX.fullmatch(str(value or "").strip())
    if not match:
        return None
    serial = int(match.group(1))
    return (serial, len(match.group(1)), match.group(2)) if serial > 0 else None


def next_number(numbers, fallback):
    """Keep the suffix and zero padding of the highest numeric-prefix number."""
    parsed = [(split_number(value), value) for value in numbers]
    parsed = [(parts, value) for parts, value in parsed if parts]
    if not parsed:
        parsed = [(split_number(fallback), fallback)]
        if not parsed[0][0]:
            raise ValueError("Fallback nomor harus diawali angka dan garis miring")
        serial, width, suffix = parsed[0][0]
        return f"{serial:0{width}d}/{suffix}"
    serial, width, suffix = max(parsed, key=lambda item: item[0][0])[0]
    return f"{serial + 1:0{width}d}/{suffix}"


def suggest_number(cur, site, namespace, fallback, existing=None):
    if existing:
        return existing
    cur.execute("select full_number from document_number_serials where site=%s and namespace=%s and serial is not null order by serial desc,created_at desc limit 1", (site, namespace))
    row = cur.fetchone()
    return next_number([row["full_number"]] if row else [], fallback)


def invoice_fallback(masters, site, kind, service_date):
    vendor = masters.get("vendor") or {}
    field = "rawInvoicePrefix" if kind == "BAHAN_BAKU" else "operationalInvoicePrefix"
    configured = str(vendor.get(field) or "").strip()
    if configured.startswith("/"):
        return "001" + configured
    if split_number(configured):
        return configured
    code = "BB" if kind == "BAHAN_BAKU" else "OP"
    roman = ["I","II","III","IV","V","VI","VII","VIII","IX","X","XI","XII"][service_date.month - 1]
    return f"001/{code}/SPPG-{site}/{roman}/{service_date.year}"


def daily_number(cur, site, service_date, masters, existing=None):
    if existing:
        return existing
    cur.execute("select full_number from document_number_serials where site=%s and namespace='LPDH' and owner_key=%s order by created_at desc limit 1", (site, "DAY:" + service_date.isoformat()))
    own = cur.fetchone()
    if own:
        return own["full_number"]
    seed = str((masters.get("identity") or {}).get("lpdhNumber") or
               (masters.get("numbering") or {}).get("lpdhSeed") or "").strip()
    if not split_number(seed):
        roman = ["I","II","III","IV","V","VI","VII","VIII","IX","X","XI","XII"][service_date.month - 1]
        seed = f"001/LPDH/SPPG-{site}/{roman}/{service_date.year}"
    cur.execute("select min(service_date) as first_date from lpdh_daily_state where site=%s", (site,))
    first_date = (cur.fetchone() or {}).get("first_date")
    anchor = str((masters.get("numbering") or {}).get("lpdhSeedDate") or first_date or "")[:10]
    if anchor == service_date.isoformat():
        return seed
    if anchor and service_date.isoformat() > anchor:
        seed = next_number([seed], seed)
    return suggest_number(cur, site, "LPDH", seed)


def claim_number(cur, site, namespace, number, owner_key):
    """Serialize saves for a site/type; a lost race returns a conflict to the editor."""
    number = str(number or "").strip()
    if not number or len(number) > 100:
        raise HTTPException(422, "Nomor wajib diisi (maksimal 100 karakter)")
    parts = split_number(number)
    serial = parts[0] if parts else None
    if serial is not None and serial > 9223372036854775807:
        raise HTTPException(422, "Awalan nomor terlalu besar")
    cur.execute("select pg_advisory_xact_lock(hashtextextended(%s,0))", (f"document-serial:{site}:{namespace}",))
    cur.execute("select owner_key,full_number from document_number_serials where site=%s and namespace=%s and (normalized_number=%s or (serial is not null and serial=%s))", (site, namespace, number.casefold(), serial))
    existing = cur.fetchone()
    if existing:
        if existing["owner_key"] != owner_key:
            raise HTTPException(409, "Awalan nomor sudah dipakai. Muat saran terbaru atau isi nomor lain.")
        # Retain the serial claim, but use the latest manually edited suffix.
        cur.execute("update document_number_serials set full_number=%s where site=%s and namespace=%s and owner_key=%s and serial=%s", (number, site, namespace, owner_key, serial))
    cur.execute("insert into document_number_serials(site,namespace,serial,full_number,normalized_number,owner_key) values (%s,%s,%s,%s,%s,%s) on conflict(site,namespace,normalized_number) do nothing", (site, namespace, serial, number, number.casefold(), owner_key))
