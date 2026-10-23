"""Allowlisted operational form editing; never commits domain data."""
from copy import deepcopy
from decimal import Decimal
import math
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

LABELS = {'code':'Kode master','canonical_name':'Nama barang kanonis','base_unit':'Satuan dasar','category_code':'Kategori master','vendor_code':'Vendor','purchase_order_id':'PO','goods_receipt_id':'Penerimaan','date':'Tanggal pencatatan','received_at':'Tanggal/jam diterima','stock_date':'Tanggal SO','invoice_date':'Tanggal invoice','due_date':'Jatuh tempo','paid_at':'Tanggal/jam pembayaran','paid_date':'Tanggal lunas','payment_status':'Status pembayaran','paid_amount':'Sudah dibayar (Rp)','amount':'Nilai (Rp)','distribution_date':'Tanggal distribusi','cooking_date':'Tanggal masak','description':'Keterangan','note':'Catatan','reason':'Alasan','text':'Laporan barang asli','invoice_number':'Nomor invoice','reference_number':'Referensi bukti','reporter':'Pelapor','qty':'Jumlah','received_qty':'Diterima','unit':'Satuan','unit_price':'Harga satuan','vendor_cost_price':'Harga vendor','rejected_qty':'Reject','invoiced_qty':'Qty invoice','po_qty':'Qty PO','item_name':'Barang','category':'Kategori','type':'Jenis','payment_source':'Sumber pembayaran'}
COMMON = {'vendor_code','purchase_order_id','goods_receipt_id','date','received_at','stock_date','invoice_date','due_date','paid_at','paid_date','payment_status','paid_amount','amount','distribution_date','cooking_date','description','note','reason','text','invoice_number','reference_number','reporter','payment_source','exception_reason'}
ROW_KEYS = {'item_name','description','date','qty','received_qty','unit','unit_price','vendor_cost_price','rejected_qty','invoiced_qty','po_qty','amount','payment_status','paid_amount','paid_date','category','type','note','order_by'}
NUMBERS={'purchase_order_id','goods_receipt_id','amount','paid_amount','qty','received_qty','unit_price','vendor_cost_price','rejected_qty','invoiced_qty','po_qty'}
DEFAULTS = {
 'UPSERT_INVENTORY_ITEM_MASTER':['code','canonical_name','base_unit','category_code','aliases','active'],
 'RECORD_GOODS_RECEIPT':['vendor_code','received_at','purchase_order_id','reporter','text'],
 'RECORD_STOCK_OPNAME':['stock_date','reporter','text'],
 'CREATE_NO_PO_PAYABLE':['vendor_code','invoice_number','invoice_date','due_date','exception_reason'],
 'CREATE_PAYABLE_FROM_RECEIPT':['purchase_order_id','goods_receipt_id','invoice_number','invoice_date','due_date'],
 'RECORD_VENDOR_PAYMENT':['vendor_code','paid_at','amount','reference_number','payment_source'],
 'CREATE_PO':['vendor_code','distribution_date','cooking_date','note'],
}

def field(key, value=None):
    if key=='aliases': return {'key':key,'label':'Alias barang','type':'list','value':value or [],'options':[]}
    if key=='active': return {'key':key,'label':'Status master','type':'select','value':value,'options':[{'value':True,'label':'Aktif'},{'value':False,'label':'Nonaktif'}]}
    kind='number' if key in NUMBERS else 'select' if key in {'payment_status','type'} else 'datetime-local' if key in {'received_at','paid_at'} else 'date' if key=='date' or key.endswith('_date') else 'textarea' if key in {'text','source_raw_text','note','description'} else 'text'
    if kind=='datetime-local' and value:
        try:
            dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
            value=(dt.replace(tzinfo=ZoneInfo('Asia/Jakarta')) if dt.tzinfo is None else dt.astimezone(ZoneInfo('Asia/Jakarta'))).isoformat()[:16]
        except ValueError: value=None
    options=([{'value':'paid','label':'Lunas'},{'value':'unpaid','label':'Belum lunas / hutang'},{'value':'partial','label':'Dibayar sebagian'}] if key=='payment_status' else [{'value':'expense','label':'Pengeluaran'},{'value':'income','label':'Pemasukan'}] if key=='type' else [])
    return {'key':key,'label':LABELS.get(key,key.replace('_',' ')),'type':kind,'value':value,'options':options}

def describe_form(action, payload, preview):
    data=payload.get('patch',{}) if action=='UPDATE_ACCOUNTANT_TRANSACTION' else payload
    keys=list(dict.fromkeys(DEFAULTS.get(action,[])+[k for k in data if k in COMMON]))
    fields=[field(k,data.get(k)) for k in keys]
    rows=[]; row_path=next((k for k in ('items','lines','po_lines') if isinstance(data.get(k),list)),None)
    if row_path:
        for index,row in enumerate(data[row_path]):
            keys=list(dict.fromkeys(list(row)+(['payment_status','paid_date'] if action=='CREATE_ACCOUNTANT_TRANSACTIONS' else [])))
            rows.append({'index':index,'label':row.get('item_name') or row.get('description') or f'Barang {index+1}','fields':[field(k,row.get(k)) for k in keys if k in ROW_KEYS]})
    elif action=='RECORD_GOODS_RECEIPT':
        for index,row in enumerate(preview.get('reportedItems',[])):
            rows.append({'index':index,'label':row.get('reported_item_name','Barang'),'fields':[field('item_name',row.get('reported_item_name')),field('received_qty',row.get('received_qty')),field('unit',row.get('unit'))]})
    elif action=='RECORD_STOCK_OPNAME':
        for index,row in enumerate(preview.get('items',[])):
            rows.append({'index':index,'label':row.get('itemName','Barang'),'fields':[field('item_name',row.get('itemName')),field('qty',row.get('qty')),field('unit',row.get('unit'))]})
    return {'fields':fields,'rows':rows,'rowPath':row_path,'receiptRows':action=='RECORD_GOODS_RECEIPT','stockRows':action=='RECORD_STOCK_OPNAME','timezone':'Asia/Jakarta'}

def _value(key,value):
    if key=='aliases':
        if not isinstance(value,list) or any(not isinstance(x,str) or not x.strip() for x in value): raise ValueError('Alias harus daftar nama yang tidak kosong')
        return list(dict.fromkeys(x.strip() for x in value))
    if key=='active':
        if not isinstance(value,bool): raise ValueError('Status aktif harus true/false')
        return value
    if key in NUMBERS:
        number=float(str(value).replace(',','.'))
        if not math.isfinite(number) or number<0: raise ValueError('Nilai harus angka nonnegatif yang valid')
        if key.endswith('_id'):
            if number<=0 or not number.is_integer(): raise ValueError('ID tidak valid')
            return int(number)
        return number
    if key in {'received_at','paid_at'} and value:
        dt=datetime.fromisoformat(str(value))
        return dt.replace(tzinfo=ZoneInfo('Asia/Jakarta')).isoformat() if dt.tzinfo is None else dt.isoformat()
    if key=='payment_status' and value not in {'paid','unpaid','partial'}: raise ValueError('Status pembayaran tidak valid')
    if key=='type' and value not in {'income','expense'}: raise ValueError('Jenis transaksi tidak valid')
    return value

def apply_form(action,payload,preview,edits):
    data=deepcopy(payload); target=data.setdefault('patch',{}) if action=='UPDATE_ACCOUNTANT_TRANSACTION' else data
    schema=describe_form(action,payload,preview)
    allowed={f['key'] for f in schema['fields']}
    for key,value in (edits.get('fields') or {}).items():
        if key not in allowed: raise ValueError('Kolom tidak boleh diubah: '+key)
        if value in ('',None): target.pop(key,None)
        else: target[key]=_value(key,value)
    rows=edits.get('rows')
    selection=edits.get('selected_indices')
    if rows is not None or selection is not None:
        if rows is not None and (not isinstance(rows,list) or not rows): raise ValueError('Perubahan barang harus berisi baris yang diubah')
        originals={r['index']:r for r in schema['rows']}; selected=[]; seen=set()
        changes={}
        for change in rows or []:
            index=change.get('index')
            if type(index) is not int or index not in originals or index in seen: raise ValueError('Baris barang tidak valid')
            seen.add(index); changes[index]=change
        indices=list(originals)
        if selection is not None:
            if not isinstance(selection,list) or not selection or any(type(i) is not int or i not in originals for i in selection) or len(set(selection))!=len(selection):
                raise ValueError('Pilih minimal satu barang dengan indeks yang valid dan unik')
            indices=[i for i in originals if i in selection]
            if not set(changes)<=set(indices): raise ValueError('Tidak boleh mengedit barang yang dikeluarkan')
        for index in indices:
            change=changes.get(index,{})
            original=originals[index]
            allowed={f['key'] for f in original['fields']}
            updates=change.get('fields') or {}
            if not set(updates)<=allowed: raise ValueError('Kolom barang tidak diizinkan')
            row=deepcopy(target[schema['rowPath']][index]) if schema['rowPath'] else {f['key']:f['value'] for f in original['fields']}
            for key,value in updates.items():
                if value in ('',None): row.pop(key,None)
                else: row[key]=_value(key,value)
            if 'payment_status' in row:
                status=row['payment_status']; amount=float(row.get('amount') or 0)
                row['is_debt']=status!='paid'
                if status=='paid': row['paid_amount']=amount; row['paid_date']=row.get('paid_date') or row.get('date')
                elif status=='unpaid': row['paid_amount']=0; row['paid_date']=None
                elif not 0<=float(row.get('paid_amount') or 0)<amount: raise ValueError('Pembayaran sebagian harus kurang dari nilai tagihan')
            selected.append(row)
        if schema['rowPath']: target[schema['rowPath']]=selected
        if schema['receiptRows']:
            # Preserve the original evidence separately, and parse only operator-selected rows.
            data.setdefault('source_raw_text',payload.get('source_raw_text') or payload.get('text',''))
            target['text']='\n'.join(f"{r['item_name']} - {r.get('received_qty',r.get('qty'))} {r['unit']}" for r in selected)
            normalized=[{'item_name':r['item_name'],'received_qty':r.get('received_qty',r.get('qty')),'unit':r['unit']} for r in selected]
            summary={'itemCount':len(normalized),'items':normalized,'operatorEdited':True}
            if len({r['unit'] for r in normalized})==1:
                summary.update(actualQty=float(sum((Decimal(str(r['received_qty'])) for r in normalized),Decimal(0))),unit=normalized[0]['unit'])
            target['receipt_input_summary']=summary
        elif schema['stockRows']:
            original_items=preview.get('items',[])
            target['reviewed_items']=[]
            for index,row in zip(indices,selected):
                original=original_items[index]
                keep_name=row['item_name']==original.get('itemName')
                target['reviewed_items'].append({'client_key':original.get('clientKey'),'include':True,'raw_item_name':row['item_name'],'canonical_item_name':original.get('canonicalItemName') if keep_name else row['item_name'],'inventory_item_code':original.get('inventoryItemCode') if keep_name else None,'area_code':original.get('areaCode'),'qty':row['qty'],'unit':row.get('unit')})
                source = next((item for item in payload.get('reviewed_items', []) if item.get('client_key') == original.get('clientKey')), {})
                if source.get('raw_line'):
                    target['reviewed_items'][-1]['raw_line'] = source['raw_line']
        elif not schema['rowPath']: raise ValueError('Action ini tidak memiliki barang pilihan')
    return data


