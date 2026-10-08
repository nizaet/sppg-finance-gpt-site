import json
import unittest
from contextlib import contextmanager,ExitStack
from copy import deepcopy
from datetime import date
from io import BytesIO
from unittest.mock import patch
import test_generated_document_api as fixture
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from pypdf import PdfReader
from backend import lpdh_api,topup_receipt_api as api
from backend.topup_receipt import financial,defaults,render_receipt,protect_final_rows

class Store(fixture.FakeConnection):
    def __init__(self):
        super().__init__();self.data={'topups':[{'date':'2026-10-08','rawAmount':231392400,'operationalAmount':64864000,'incentiveAmount':40576000,'reference':'SP2D-1','receiptNo':'','evidenceLink':''}]};self.receipts={};self.daily_status='DRAFT';self.topup_profile=None
    def execute(self,sql,args=()):
        if sql.startswith('select data,status from lpdh_daily_state'):self.result={'data':deepcopy(self.data),'status':self.daily_status}
        elif sql.startswith('select * from lpdh_topup_receipts where id'):
            r=self.receipts.get(args[0]);self.result=deepcopy(r) if r and (len(args)==1 or (r['site']==args[1] and r['service_date']==args[2])) else None
        elif sql.startswith('select * from lpdh_topup_receipts where site'):self.result=[deepcopy(r) for r in self.receipts.values() if r['site']==args[0] and r['service_date']==args[1]]
        elif sql.startswith('select id,document_number,snapshot,pdf_link'):self.result=[deepcopy(r) for r in self.receipts.values() if r['status']=='FINAL']
        elif sql.startswith('insert into lpdh_topup_receipts'):
            i=len(self.receipts)+1;self.receipts[i]={'id':i,'site':args[0],'service_date':args[1],'document_number':args[2],'snapshot':json.loads(args[3]),'status':'DRAFT'};self.result=deepcopy(self.receipts[i])
        elif sql.startswith('update lpdh_topup_receipts set snapshot'):
            r=self.receipts[args[2]];r.update(snapshot=json.loads(args[0]),document_number=args[1]);self.result=deepcopy(r)
        elif sql.startswith("update lpdh_topup_receipts set status='FINAL'"):
            r=self.receipts[args[2]];r.update(status='FINAL',pdf_link=args[0]);self.result=deepcopy(r)
        elif sql.startswith("update lpdh_topup_receipts set status='CANCELLED'"):
            r=self.receipts[args[1]];r.update(status='CANCELLED',cancelled_reason=args[0]);self.result=deepcopy(r)
        elif sql.startswith('update lpdh_daily_state set data'):self.data=json.loads(args[0])
        elif sql.startswith('insert into lpdh_topup_receipt_profiles'):self.topup_profile=json.loads(args[1])
        elif sql.startswith('select data from lpdh_topup_receipt_profiles'):self.result={'data':self.topup_profile} if self.topup_profile else None
        else:super().execute(sql,args)

class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.db=Store();self.stack=ExitStack();self.addCleanup(self.stack.close)
        @contextmanager
        def connection():yield self.db
        self.stack.enter_context(patch.object(api,'connection',connection))
        self.stack.enter_context(patch.object(fixture.api,'daily_lock',lambda *args:None))
        self.stack.enter_context(patch.object(lpdh_api,'_load_master',return_value={'data':{}}))
        app=FastAPI()
        @app.middleware('http')
        async def auth(request,call_next):request.state.sppg_role=request.headers.get('x-role','MAJA');return await call_next(request)
        app.include_router(lpdh_api.router);self.client=TestClient(app)
        self.profile={**defaults({}),'sppgName':'SPPG Lebak Maja Sangiang 2','foundation':'Yayasan Dermawan Mentari Megha','headName':'Embun Cahyana','foundationName':'Pengurus Yayasan'}
    def draft(self,**changes):
        body={'site':'MAJA','service_date':'2026-10-08','row_index':0,'expected_funds':self.db.data['topups'][0],'document_number':'001/KWT/SPPGSANG2/X/2026','profile':self.profile};body.update(changes)
        return self.client.post('/v1/lpdh/topup/receipts',json=body)
    def action(self,kind,r,**fields):return self.client.post(f"/v1/lpdh/topup/receipts/{r['id']}/{kind}",json={'expected_hash':r['hash'],**fields})
    def test_lifecycle_idempotent_and_no_double_count(self):
        r=self.draft().json()['receipt'];self.assertEqual(r['status'],'DRAFT')
        suggestion=self.client.get('/v1/lpdh/topup/receipts?site=MAJA&date=2026-11-02')
        self.assertEqual(suggestion.json()['documentNumber'],'002/KWT/SPPGSANG2/XI/2026')
        self.assertEqual(self.db.data['topups'][0]['evidenceLink'],'')
        pdf=self.client.get('/v1/lpdh/topup/receipts/1/pdf');self.assertEqual(pdf.status_code,200)
        import base64
        text=PdfReader(BytesIO(base64.b64decode(pdf.json()['contentBase64']))).pages[0].extract_text()
        self.assertIn('336.832.400',text);self.assertIn('DRAFT',text);self.assertIn('08 Oktober 2026',text)
        with patch('backend.accountant_drive.upload_accountant_artifact',return_value={'driveUri':'https://drive.google.com/file/d/topup/view'}) as upload:
            final=self.action('finalize',r);self.assertEqual(final.status_code,200,final.text)
            self.assertEqual(self.action('finalize',r).status_code,200);self.assertEqual(upload.call_count,1)
        row=self.db.data['topups'][0];self.assertEqual(row['receiptNo'],r['documentNumber']);self.assertEqual(sum(row[k] for k in ('rawAmount','operationalAmount','incentiveAmount')),336832400)
        self.assertNotIn('operations',self.db.data);self.assertFalse(self.db.data['_reviewValidated'])
        protect_final_rows(self.db,'MAJA',date(2026,10,8),deepcopy(self.db.data))
        changed=deepcopy(self.db.data);changed['topups'][0]['rawAmount']=1
        with self.assertRaises(HTTPException):protect_final_rows(self.db,'MAJA',date(2026,10,8),changed)
        cancel=self.action('cancel',r,reason='Perbaikan');self.assertEqual(cancel.status_code,200,cancel.text)
        self.assertEqual(self.db.data['topups'][0]['evidenceLink'],'');self.assertEqual(self.db.receipts[1]['pdf_link'],'https://drive.google.com/file/d/topup/view')
    def test_edit_receipt_values_applied_only_on_final(self):
        original=deepcopy(self.db.data['topups'][0])
        funds={**original,'rawAmount':1000,'operationalAmount':2000,'incentiveAmount':3000}
        response=self.draft(funds=funds);self.assertEqual(response.status_code,200,response.text)
        r=response.json()['receipt']
        self.assertEqual(self.db.data['topups'][0]['rawAmount'],original['rawAmount'])
        with patch('backend.accountant_drive.upload_accountant_artifact',return_value={'driveUri':'https://drive.google.com/test'}) as upload:
            response=self.action('finalize',r);self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(self.action('finalize',r).status_code,200)
            self.assertEqual(upload.call_count,1)
        self.assertEqual(len(self.db.data['topups']),1)
        self.assertEqual(self.db.data['topups'][0]['rawAmount'],1000)
        self.assertEqual(self.db.data['topups'][0]['incentiveAmount'],3000)

    def test_new_receipt_without_existing_topup(self):
        self.db.data['topups']=[]
        response=self.client.post('/v1/lpdh/topup/receipts',json={'site':'MAJA','service_date':'2026-10-08','row_index':0,'expected_funds':{'date':'2026-10-08'},'funds':{'date':'2026-10-08','rawAmount':1000},'document_number':'001/KWT/SPPGSANG2/X/2026','profile':self.profile})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(len(self.db.data['topups']),1)
        self.assertEqual(self.db.data['topups'][0]['rawAmount'],0)
        with patch('backend.accountant_drive.upload_accountant_artifact',return_value={'driveUri':'https://drive.google.com/test'}):
            self.assertEqual(self.action('finalize',response.json()['receipt']).status_code,200)
        self.assertEqual(self.db.data['topups'][0]['rawAmount'],1000)

    def test_invalid_mitra_link_recovers_from_final_approval(self):
        from backend.generated_document_logic import merge_final_documents
        data={'incentive':{'paidAmount':6344000,'evidenceLink':'004/KW-INS'},'_approval':{'status':'FINAL','pdfLink':'https://drive.google.com/approval'}}
        result=merge_final_documents(data,[])
        self.assertEqual(result['incentive']['evidenceLink'],'https://drive.google.com/approval')
        self.assertEqual(result['incentive']['paidAmount'],6344000)
        data['incentive']['evidenceLink']='https://manual.example/proof'
        self.assertEqual(merge_final_documents(data,[])['incentive']['evidenceLink'],'https://manual.example/proof')
        data['incentive']['evidenceLink']='';data['_approval']['status']='CANCELLED'
        self.assertEqual(merge_final_documents(data,[])['incentive']['evidenceLink'],'')

    def test_stale_and_locked(self):
        bad=deepcopy(self.db.data['topups'][0]);bad['rawAmount']=1
        self.assertEqual(self.draft(expected_funds=bad).status_code,409)
        r=self.draft().json()['receipt'];self.db.data['topups'][0]['rawAmount']=1
        with patch('backend.accountant_drive.upload_accountant_artifact') as upload:
            self.assertEqual(self.action('finalize',r).status_code,409);upload.assert_not_called()
        self.db.daily_status='GENERATED';self.assertEqual(self.draft().status_code,409)
    def test_permissions_drive_failure_and_amounts(self):
        response=self.client.get('/v1/lpdh/topup/receipts?site=MAJA&date=2026-10-08',headers={'x-role':'CEMPLANG'});self.assertEqual(response.status_code,403)
        r=self.draft().json()['receipt']
        with patch('backend.accountant_drive.upload_accountant_artifact',side_effect=RuntimeError('secret')):
            response=self.action('finalize',r);self.assertEqual(response.status_code,502);self.assertNotIn('secret',response.text)
        self.assertEqual(self.db.receipts[1]['status'],'DRAFT');self.assertEqual(self.db.data['topups'][0]['evidenceLink'],'')
        for value in (-1,'NaN','1.2'):
            with self.assertRaises(ValueError):financial({'date':'2026-10-08','rawAmount':value})
    def test_pdf_without_draft_mark(self):
        r=self.draft().json()['receipt'];row=self.db.receipts[r['id']]
        reader=PdfReader(BytesIO(render_receipt(row,True)));self.assertEqual(len(reader.pages),1);self.assertNotIn('DRAFT',reader.pages[0].extract_text())

if __name__=='__main__':unittest.main()

