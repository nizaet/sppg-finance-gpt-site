"""Export a locked FINAL snapshot once; never approve or mark a payment paid."""
import json
from fastapi import HTTPException


def export_snapshot(cur, document, actor):
    if document['status'] != 'FINAL':
        raise HTTPException(409, 'Hanya invoice FINAL aktif dapat diekspor ke Data Maker.')
    if not document.get('driveUri'):
        raise HTTPException(409, 'Simpan PDF FINAL ke Drive terlebih dahulu.')
    cur.execute('select accountant_invoice_id,maker_id from generated_document_maker_exports where document_id=%s', (document['id'],))
    existing = cur.fetchone()
    if existing and existing.get('maker_id'):
        return {**existing, 'duplicate': True}
    if existing:
        # The established cancellation workflow removes pending Makers, not invoices.
        from backend.accountant_document_api import _create_maker
        maker = _create_maker(cur,existing['accountant_invoice_id'],document['site'],document['total'],document['documentNumber'])
        cur.execute('update generated_document_maker_exports set maker_id=%s,exported_by=%s,exported_at=now() where document_id=%s',
                    (maker['makerId'],actor,document['id']))
        return {'accountant_invoice_id':existing['accountant_invoice_id'],'maker_id':maker['makerId'],'duplicate':False}
    # Use existing Maker categories; retain the exact invoice type in parsed_payload.
    category = 'BAHAN_BAKU' if document['documentType'] == 'BAHAN_BAKU' else 'UPAH' if document['documentType'] == 'UPAH_RELAWAN' else 'OPERASIONAL_LAIN'
    cur.execute('''insert into accountant_invoices(site,accountant_code,invoice_category,invoice_number,
        invoice_date,period_start,period_end,invoice_amount,invoice_evidence_uri,received_at,source_type,parsed_payload,updated_at)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),'LPDH_FINAL',%s::jsonb,now()) returning id''',
        (document['site'], actor, category, document['documentNumber'], document['serviceDate'],
         document['serviceDate'], document['serviceDate'], document['total'], document['driveUri'],
         json.dumps({'generatedDocumentId':document['id'], 'documentType':document['documentType'], 'header':document['header']},ensure_ascii=False)))
    invoice_id = cur.fetchone()['id']
    # For a combined invoice this remains one maker using the main cover total.
    for item in document['items']:
        cur.execute('''insert into accountant_invoice_items(accountant_invoice_id,item_name,quantity,unit,unit_price,line_total)
            values (%s,%s,%s,%s,%s,%s)''', (invoice_id,item['itemName'],item['quantity'],item['unit'],item['unitPrice'],item['lineTotal']))
    from backend.accountant_document_api import _create_maker
    maker = _create_maker(cur,invoice_id,document['site'],document['total'],document['documentNumber'])
    cur.execute('insert into generated_document_maker_exports(document_id,accountant_invoice_id,maker_id,exported_by) values (%s,%s,%s,%s)',
                (document['id'],invoice_id,maker['makerId'],actor))
    return {'accountant_invoice_id':invoice_id,'maker_id':maker['makerId'],'duplicate':False}
