"""Daily payment package sections and master-based incentive defaults."""
from copy import deepcopy

SECTIONS = (("Relawan", "Upah Relawan"), ("Guru", "Insentif Guru"), ("Kader", "Insentif Kader"))


def school_daily_rate(count):
    if count < 0:
        raise ValueError('Jumlah penerima manfaat tidak boleh negatif')
    return 20000 if count <= 100 else 30000 if count <= 500 else 40000


def incentive_default(row, kind):
    fields = ('smallPortions', 'largePortions', 'staffLarge') if kind == 'Guru' else ('balitaSmall', 'pregnantLarge', 'breastfeedingLarge')
    count = sum(float(row.get(field) or 0) for field in fields)
    return {'targetPm': count, 'dailyAmount': school_daily_rate(count) if kind == 'Guru' else count * 1000}


def is_payment_package(document):
    return document.get('documentType') == 'UPAH_RELAWAN' and (document.get('header') or {}).get('combinedPayments') is True


def payment_sections(document):
    """Printable sections keep the single parent number and original line ids."""
    if not is_payment_package(document):
        return []
    sections = []
    for kind, title in SECTIONS:
        items = [deepcopy(item) for item in document['items'] if (item.get('metadata') or {}).get('recipientType') == kind]
        if not items:
            continue
        sections.append((title, {**document, 'documentType': 'UPAH_RELAWAN' if kind == 'Relawan' else 'INSENTIF_GURU_KADER',
            'header': {**document['header'], 'combinedPayments': False, 'recipientSubtype': kind},
            'items': items, 'total': sum(item['lineTotal'] for item in items)}))
    return sections
