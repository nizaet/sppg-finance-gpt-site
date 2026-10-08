import base64
import json
from datetime import date
from fastapi import APIRouter,HTTPException,Request,Query
from pydantic import BaseModel,Field
from backend.db import connection
from backend.document_numbering import claim_number,suggest_number
from backend.topup_receipt import defaults,validate_profile,financial,digest,attach,render_receipt,checked_number

router=APIRouter()
class ReceiptIn(BaseModel):
    site:str
    service_date:date
    row_index:int=Field(ge=0,le=120)
    expected_funds:dict
    funds:dict|None=None
    document_number:str=Field(min_length=1,max_length=100)
    profile:dict
class ActionIn(BaseModel):
    expected_hash:str=Field(min_length=64,max_length=64)
    reason:str=Field(default='',max_length=600)

def context(request,site,service_date,cur):
    from backend.lpdh_api import _site,_require_db,_role
    from backend.accountant_generated_document_api import daily_lock
    _require_db();site=_site(request,site);daily_lock(cur,site,service_date)
    cur.execute('select data,status from lpdh_daily_state where site=%s and service_date=%s for update',(site,service_date));state=cur.fetchone()
    if not state:raise HTTPException(409,'Simpan & Validasi Data Harian terlebih dahulu.')
    if state['status']=='GENERATED' or state['data'].get('_historicalGeneratedSnapshot'):
        raise HTTPException(409,'LPDH sudah diterbitkan; kuitansi tidak boleh mengubah snapshot tersebut.')
    return site,state['data'],_role(request)

def save_daily(cur,site,day,data,actor):
    data['_reviewValidated']=False
    cur.execute("update lpdh_daily_state set data=%s::jsonb,revision=revision+1,updated_by=%s,updated_at=now() where site=%s and service_date=%s",(json.dumps(data,ensure_ascii=False),actor,site,day))

def serialize(row):
    return {'id':row['id'],'documentNumber':row['document_number'],'status':row['status'],
        'hash':digest(row['snapshot']),'snapshot':row['snapshot'],'pdfLink':row.get('pdf_link'),
        'cancelReason':row.get('cancelled_reason')}

def get_receipt(cur,request,receipt_id,lock=True):
    from backend.lpdh_api import _site,_require_db
    _require_db();cur.execute('select * from lpdh_topup_receipts where id=%s'+(' for update' if lock else ''),(receipt_id,));row=cur.fetchone()
    if not row:raise HTTPException(404,'Kuitansi tidak ditemukan.')
    _site(request,row['site']);return row

@router.get('/topup/receipts')
def list_receipts(request:Request,site:str=Query(),service_date:date=Query(alias='date')):
    from backend.lpdh_api import _site,_require_db,_load_master
    _require_db();site=_site(request,site);profile=defaults(_load_master(site)['data'])
    with connection() as conn,conn.cursor() as cur:
        cur.execute('select data from lpdh_topup_receipt_profiles where site=%s',(site,));stored=cur.fetchone()
        if stored:profile.update(stored['data'])
        cur.execute('select * from lpdh_topup_receipts where site=%s and service_date=%s order by id',(site,service_date));receipts=[serialize(r) for r in cur.fetchall()]
        roman=['I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII'][service_date.month-1]
        number=suggest_number(cur,site,'TOPUP_RECEIPT',f'001/KWT/SPPG-{site}/{roman}/{service_date.year}')
    return {'profile':profile,'documentNumber':number,'receipts':receipts}

@router.post('/topup/receipts')
def save_draft(payload:ReceiptIn,request:Request):
    try:profile=validate_profile(payload.profile);number=checked_number(payload.document_number);expected=financial(payload.expected_funds)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    with connection() as conn,conn.cursor() as cur:
        site,data,actor=context(request,payload.site,payload.service_date,cur)
        rows=data.setdefault('topups', [])
        if payload.row_index == len(rows) and not any(expected[k] for k in ('rawAmount','operationalAmount','incentiveAmount')) and expected['date'] == payload.service_date.isoformat():
            rows.append({**expected,'receiptNo':'','evidenceLink':''})
        if payload.row_index>=len(rows):raise HTTPException(409,'Baris TopUp berubah. Muat ulang.')
        target=rows[payload.row_index]
        try:funds=financial(target)
        except ValueError as exc:raise HTTPException(422,'Isi tanggal dan nominal penerimaan TopUp.') from exc
        if expected!=funds:raise HTTPException(409,'Isian belum sama dengan data tersimpan. Klik Simpan & Validasi dahulu.')
        baseline=funds
        if payload.funds is not None:
            try:funds=financial(payload.funds)
            except ValueError as exc:raise HTTPException(422,str(exc)) from exc
        if sum(funds[k] for k in ('rawAmount','operationalAmount','incentiveAmount'))<=0:raise HTTPException(422,'Nominal TopUp harus lebih dari nol.')
        current=None
        if target.get('_topupReceiptId'):
            cur.execute('select * from lpdh_topup_receipts where id=%s and site=%s and service_date=%s for update',(target['_topupReceiptId'],site,payload.service_date));current=cur.fetchone()
        if current and current['status']=='FINAL':raise HTTPException(409,'Batalkan kuitansi FINAL sebelum mengeditnya.')
        snapshot={'funds':funds,'sourceFunds':baseline,'profile':profile,'number':number,'previousReceipt':target.get('receiptNo') or '', 'previousLink':target.get('evidenceLink') or ''}
        if current and current['status']=='DRAFT':
            receipt_id=current['id']
            cur.execute('delete from document_number_serials where site=%s and namespace=%s and owner_key=%s',(site,'TOPUP_RECEIPT','TOPUP:'+str(receipt_id)))
            cur.execute('update lpdh_topup_receipts set snapshot=%s::jsonb,document_number=%s,updated_at=now() where id=%s returning *',(json.dumps(snapshot,ensure_ascii=False),number,receipt_id));receipt=cur.fetchone()
        else:
            cur.execute('insert into lpdh_topup_receipts(site,service_date,document_number,snapshot,created_by) values(%s,%s,%s,%s::jsonb,%s) returning *',(site,payload.service_date,number,json.dumps(snapshot,ensure_ascii=False),actor));receipt=cur.fetchone();receipt_id=receipt['id']
        claim_number(cur,site,'TOPUP_RECEIPT',number,'TOPUP:'+str(receipt_id))
        target['_topupReceiptId']=receipt_id
        cur.execute('insert into lpdh_topup_receipt_profiles(site,data) values(%s,%s::jsonb) on conflict(site) do update set data=excluded.data,updated_at=now()',(site,json.dumps(profile,ensure_ascii=False)))
        save_daily(cur,site,payload.service_date,data,actor);conn.commit()
    return {'receipt':serialize(receipt),'data':data}

@router.get('/topup/receipts/{receipt_id}/pdf')
def pdf(receipt_id:int,request:Request):
    with connection() as conn,conn.cursor() as cur:receipt=get_receipt(cur,request,receipt_id)
    content=render_receipt(receipt,receipt['status']=='FINAL')
    return {'filename':'Kuitansi_TopUp_'+str(receipt_id)+'.pdf','mimeType':'application/pdf','contentBase64':base64.b64encode(content).decode(),'hash':digest(receipt['snapshot'])}

@router.post('/topup/receipts/{receipt_id}/finalize')
def finalize(receipt_id:int,payload:ActionIn,request:Request):
    from backend.accountant_drive import upload_accountant_artifact
    with connection() as conn,conn.cursor() as cur:
        receipt=get_receipt(cur,request,receipt_id,False)
        site,data,actor=context(request,receipt['site'],receipt['service_date'],cur)
        receipt=get_receipt(cur,request,receipt_id)
        if receipt['status']=='CANCELLED':raise HTTPException(409,'Kuitansi dibatalkan. Buat draft baru.')
        if digest(receipt['snapshot'])!=payload.expected_hash:raise HTTPException(409,'Draft berubah. Buka preview terbaru.')
        attach(data,receipt,receipt.get('pdf_link') or '') # Validate row before any upload.
        link=receipt.get('pdf_link')
        if not link:
            try:
                archive=upload_accountant_artifact(kind='invoice',site=site,service_date=str(receipt['service_date']),
                    filename='Kuitansi_TopUp_'+str(receipt_id)+'.pdf',data=render_receipt(receipt,True),mime_type='application/pdf',
                    artifact_key='topup-receipt-'+str(receipt_id)+'-'+payload.expected_hash)
                link=archive['driveUri']
                if not str(link).startswith('https://'):raise ValueError('invalid link')
            except Exception as exc:raise HTTPException(502,'Drive gagal. Kuitansi tetap DRAFT dan link lama tidak berubah; coba lagi.') from exc
        attach(data,receipt,link)
        cur.execute("update lpdh_topup_receipts set status='FINAL',pdf_link=%s,finalized_by=coalesce(finalized_by,%s),finalized_at=coalesce(finalized_at,now()),updated_at=now() where id=%s returning *",(link,actor,receipt_id));receipt=cur.fetchone()
        save_daily(cur,site,receipt['service_date'],data,actor);conn.commit()
    return {'receipt':serialize(receipt),'data':data}

@router.post('/topup/receipts/{receipt_id}/cancel')
def cancel(receipt_id:int,payload:ActionIn,request:Request):
    if not payload.reason.strip():raise HTTPException(422,'Isi alasan pembatalan.')
    with connection() as conn,conn.cursor() as cur:
        receipt=get_receipt(cur,request,receipt_id,False);site,data,actor=context(request,receipt['site'],receipt['service_date'],cur)
        receipt=get_receipt(cur,request,receipt_id)
        if digest(receipt['snapshot'])!=payload.expected_hash:raise HTTPException(409,'Kuitansi berubah. Muat ulang.')
        for row in data.get('topups') or []:
            if row.get('_topupReceiptId')==receipt_id:
                if row.get('receiptNo')==receipt['document_number']:row['receiptNo']=receipt['snapshot']['previousReceipt']
                if row.get('evidenceLink')==receipt.get('pdf_link'):row['evidenceLink']=receipt['snapshot']['previousLink']
        cur.execute("update lpdh_topup_receipts set status='CANCELLED',cancelled_reason=%s,updated_at=now() where id=%s returning *",(payload.reason.strip(),receipt_id));receipt=cur.fetchone()
        cur.execute('delete from document_number_serials where site=%s and namespace=%s and owner_key=%s',(site,'TOPUP_RECEIPT','TOPUP:'+str(receipt_id)))
        save_daily(cur,site,receipt['service_date'],data,actor);conn.commit()
    return {'receipt':serialize(receipt),'data':data}

