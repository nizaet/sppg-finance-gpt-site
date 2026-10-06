"""Allowlisted, read-only defaults: never copy a financial/evidence identity."""
from copy import deepcopy

from backend.generated_document_settings import PROFILE_FIELDS


def routine_documents(documents):
    templates = []
    for doc in documents:
        kind = doc['documentType']
        if doc['status'] == 'CANCELLED' or kind not in {'OPERASIONAL', 'INSENTIF_GURU_KADER'}:
            continue
        # Legacy mixed Guru/Kader packages become two separate new daily drafts.
        subtypes = ['Guru', 'Kader'] if kind == 'INSENTIF_GURU_KADER' else [None]
        for subtype in subtypes:
            items = []
            for item in doc['items']:
                meta = item.get('metadata') or {}
                if subtype and meta.get('recipientType') != subtype:
                    continue
                safe_meta = {key: deepcopy(meta[key]) for key in ('recipientType', 'unitName', 'role', 'itemCode') if key in meta}
                items.append({key: deepcopy(item[key]) for key in ('itemName', 'category', 'quantity', 'unit', 'unitPrice')} | {'metadata': safe_meta})
            if not items:
                continue
            h = {key: deepcopy(value) for key, value in doc['header'].items() if key in PROFILE_FIELDS and key != 'recipientSignatureAssetId'}
            if subtype:
                h.update(paymentSnapshotVersion=2, recipientSubtype=subtype)
                for item in items:
                    item.update(quantity=1, unit='hari')
            templates.append({'documentType': kind, 'header': h, 'items': items,
                              'sourceNumber': doc['documentNumber'], 'sourceDate': doc['serviceDate']})
    return templates


def routine_daily(data):
    pm = data.get('pm') or {}
    row_keys = ('code', 'distributed', 'received', 'notReceived', 'reason', 'bnba')
    production_keys = ('produced', 'organoleptic', 'retainedSample', 'notDistributed', 'buffer')
    return {'pm': {'rows': [{key: deepcopy(row[key]) for key in row_keys if key in row} for row in pm.get('rows', [])],
                   'production': {key: deepcopy(pm['production'][key]) for key in production_keys if key in (pm.get('production') or {})}}}
