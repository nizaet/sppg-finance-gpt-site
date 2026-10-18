"""Validate explicit confirmation text, including an exact proposal-bound sentence."""
import re


def confirmation_choice(approval_id: str, text: str) -> str:
    normalized = ' '.join(str(text or '').strip().lower().split())
    if normalized in {'batalkan','batal','tolak'}:
        return 'CANCEL'
    if normalized in {'commit true','commit','masukkan','masukan','simpan','konfirmasi'}:
        return 'CONFIRM'
    # A detailed approval must identify this exact proposal. Never interpret
    # questions, conditions, negation or edit requests as permission to execute.
    ids = re.findall(r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b',normalized)
    blocked = re.search(r'\b(jangan|belum|bukan|tidak|tolak|batalkan|nanti|jika|kalau|apakah|boleh|sebelum|sesudah|kecuali|setelah|ubah|edit|koreksi)\b',normalized)
    affirmative = re.match(r'^(?:saya\s+)?(?:konfirmasi|simpan|masukkan|masukan|commit true)\b',normalized)
    if affirmative and ids and set(ids)=={str(approval_id).lower()} and not blocked and '?' not in normalized:
        return 'CONFIRM'
    raise ValueError('Persetujuan harus tegas: konfirmasi / commit true, atau kalimat persetujuan dengan approvalId yang sama')
