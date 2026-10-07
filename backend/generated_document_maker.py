"""Export a locked FINAL snapshot once; never approve or mark a payment paid."""
import json
from fastapi import HTTPException


def maker_category(document):
    kind = document['documentType']
    if kind == 'BAHAN_BAKU': return 'BAHAN_BAKU'
    if kind == 'INSENTIF_MITRA': return 'SEWA_MITRA'
    if kind == 'UPAH_RELAWAN':
        return 'UPAH' if document.get('header', {}).get('combinedPayments') else 'GAJI_RELAWAN'
    if kind == 'INSENTIF_GURU_KADER': return 'UPAH'
    return 'OPERASIONAL_LAIN'


def export_snapshot(cur, document, actor):
    if document['status'] != 'FINAL':
        raise HTTPException(409, 'Hanya invoice FINAL aktif dapat diekspor ke Data Maker.')
    if not document.get('driveUri'):
        raise HTTPException(409, 'Simpan PDF FINAL ke Drive terlebih dahulu.')
    cur.execute('select accountant_invoice_id,maker_id from generated_document_maker_exports where document_id=%s', (document['id'],))
    existing = cur.fetchone()
    if existing and existing.get('accountant_invoice_id'):
        # Queue export never creates a Maker, including after Maker cancellation.
        return {**existing, 'duplicate': True}
    # Use existing Maker categories; retain the exact invoice type in parsed_payload.
    category = maker_category(document)
    cur.execute('select id from accountant_invoices where upper(site)=upper(%s) and lower(trim(invoice_number))=lower(trim(%s)) limit 1',
                (document['site'],document['documentNumber']))
    conflict = cur.fetchone()
    if conflict:
        raise HTTPException(409, f"Nomor invoice sudah ada di pusat operasional (invoice #{conflict['id']}). Periksa invoice/Maker tersebut; ekspor dihentikan agar tidak membuat pembayaran ganda.")
    cur.execute('''insert into accountant_invoices(site,accountant_code,invoice_category,invoice_number,
        invoice_date,period_start,period_end,invoice_amount,invoice_evidence_uri,received_at,source_type,parsed_payload,updated_at)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),'LPDH_FINAL',%s::jsonb,now()) returning id''',
        (document['site'], actor, category, document['documentNumber'], document['serviceDate'],
         document['serviceDate'], document['serviceDate'], document['total'], document['driveUri'],
         json.dumps({'generatedDocumentId':document['id'], 'documentType':document['documentType'], 'header':document['header']},ensure_ascii=False)))
    invoice_id = cur.fetchone()['id']
    # One queued invoice uses the combined cover total. Human action creates Maker.
    for item in document['items']:
        cur.execute('''insert into accountant_invoice_items(accountant_invoice_id,item_name,quantity,unit,unit_price,line_total)
            values (%s,%s,%s,%s,%s,%s)''', (invoice_id,item['itemName'],item['quantity'],item['unit'],item['unitPrice'],item['lineTotal']))
    cur.execute('''insert into generated_document_maker_exports(document_id,accountant_invoice_id,maker_id,exported_by) values (%s,%s,%s,%s)
        on conflict(document_id) do update set accountant_invoice_id=excluded.accountant_invoice_id,maker_id=excluded.maker_id,
        exported_by=excluded.exported_by,exported_at=now()''',
                (document['id'],invoice_id,None,actor))
    return {'accountant_invoice_id':invoice_id,'maker_id':None,'duplicate':False}
