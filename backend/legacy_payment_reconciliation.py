"""Explicit, snapshot-checked replacement of manual payment inputs, never FINAL rows."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from backend.generated_document_logic import aggregate_payment


def legacy_payment_plan(daily, document):
    if document.get('header', {}).get('combinedPayments'):
        indexes = {key:[i for i,row in enumerate(daily.get(key) or []) if not row.get('sourceDocumentId')]
                   for key in ('volunteerPayments','incentiveRecipients')}
        groups = {key:[daily[key][i] for i in positions] for key,positions in indexes.items()}
        def nominal(key,row):
            return float(row.get('amount') or 0) if key == 'incentiveRecipients' else float(row.get('workDays') or 0)*float(row.get('dailyRate') or 0)
        positive = [(key,row) for key,rows in groups.items() for row in rows if nominal(key,row)>0]
        old_names = {str(row.get('name') or '').strip().casefold() for key,row in positive}
        new_names = {str(item['itemName']).strip().casefold() for item in document['items']}
        if not old_names.intersection(new_names):
            return None
        snapshot = json.dumps({'groups':groups,'document':document},sort_keys=True,ensure_ascii=False,default=str)
        return {'key':'PAYMENT_PACKAGE','indexes':indexes,'snapshotHash':hashlib.sha256(snapshot.encode()).hexdigest(),
                'legacyCount':len(positive),'legacyTotal':sum(nominal(key,row) for key,row in positive),
                'newCount':len(document['items']),'newTotal':document['total'],
                'removedCount':len(old_names-new_names),'addedCount':len(new_names-old_names)}
    if not aggregate_payment(document):
        return None
    key = 'volunteerPayments' if document['documentType'] == 'UPAH_RELAWAN' else 'incentiveRecipients'
    subtype = document.get('header', {}).get('recipientSubtype')
    def selected(row):
        if row.get('sourceDocumentId'):
            return False
        if key == 'volunteerPayments':
            return True
        kind = str(row.get('type') or 'Guru').casefold().strip()
        return kind in ({'guru','sekolah','penanggung jawab satuan pendidikan'} if subtype == 'Guru' else {'kader','posyandu','kader posyandu'})
    indexes = [i for i,row in enumerate(daily.get(key) or []) if selected(row)]
    rows = [daily[key][i] for i in indexes]
    def amount(row):
        return float(row.get('amount') or 0) if key == 'incentiveRecipients' else float(row.get('workDays') or 0)*float(row.get('dailyRate') or 0)
    positive = [row for row in rows if amount(row)>0]
    if not positive:
        return None
    old_names = {str(r.get('name') or '').strip().casefold() for r in positive}
    new_names = {str(r['itemName']).strip().casefold() for r in document['items']}
    if not old_names.intersection(new_names):
        return None
    snapshot = json.dumps({'list':key,'rows':rows,'document':document},sort_keys=True,ensure_ascii=False,default=str)
    return {'key':key,'indexes':indexes,'snapshotHash':hashlib.sha256(snapshot.encode()).hexdigest(),
            'legacyCount':len(positive),'legacyTotal':sum(amount(r) for r in positive),
            'newCount':len(document['items']),'newTotal':document['total'],
            'removedCount':len(old_names-new_names),'addedCount':len(new_names-old_names)}


def replace_legacy_payments(daily, document, snapshot_hash, actor):
    plan = legacy_payment_plan(daily, document)
    if not plan or plan['snapshotHash'] != snapshot_hash:
        raise ValueError('Isian lama atau draft kuitansi berubah. Refresh register dan periksa konfirmasi penggantian lagi.')
    out = deepcopy(daily)
    if plan['key'] == 'PAYMENT_PACKAGE':
        originals = {}
        for key,indexes in plan['indexes'].items():
            selected = set(indexes)
            original = out.get(key) or []
            originals[key] = [row for i,row in enumerate(original) if i in selected]
            out[key] = [row for i,row in enumerate(original) if i not in selected]
        out.setdefault('_replacedLegacyPayments',[]).append({'sourceDocumentId':document['id'],
            'documentNumber':document['documentNumber'],'groups':originals,'confirmedBy':actor,
            'confirmedAt':datetime.now(timezone.utc).isoformat(),'snapshotHash':snapshot_hash})
        return out
    selected = set(plan['indexes'])
    original = out.get(plan['key']) or []
    out.setdefault('_replacedLegacyPayments', []).append({
        'sourceDocumentId':document['id'],'documentNumber':document['documentNumber'],
        'list':plan['key'],'rows':[row for i,row in enumerate(original) if i in selected],
        'confirmedBy':actor,'confirmedAt':datetime.now(timezone.utc).isoformat(),
        'snapshotHash':snapshot_hash,
    })
    out[plan['key']] = [row for i,row in enumerate(original) if i not in selected]
    return out
