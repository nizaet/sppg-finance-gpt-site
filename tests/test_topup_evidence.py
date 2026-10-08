import base64
from contextlib import ExitStack
from io import BytesIO
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import test_generated_document_api as fixture
from backend import lpdh_api as api
from backend.lpdh_logic import compute_preview
from backend.topup_evidence import decode_evidence,MAX_BYTES


class TopupEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.image=BytesIO();Image.new('RGB',(10,10),'white').save(self.image,format='JPEG')
        self.encoded=base64.b64encode(self.image.getvalue()).decode()
        app=FastAPI()
        @app.middleware('http')
        async def authenticate(request,call_next):
            request.state.sppg_role=request.headers.get('x-test-role','')
            return await call_next(request)
        app.include_router(api.router)
        self.client=TestClient(app)

    def post(self,encoded=None,role='MAJA'):
        return self.client.post('/v1/lpdh/topup/evidence',json={'site':'MAJA','service_date':'2026-10-08','content_base64':encoded if encoded is not None else self.encoded},headers={'x-test-role':role})

    def test_upload_and_scope(self):
        with patch('backend.accountant_drive.upload_accountant_artifact',return_value={'driveUri':'https://drive.google.com/file/d/proof/view'}) as upload:
            response=self.post()
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['evidenceLink'],'https://drive.google.com/file/d/proof/view')
            self.assertEqual(upload.call_args.kwargs['mime_type'],'image/jpeg')
            self.assertEqual(upload.call_args.kwargs['site'],'MAJA')
            self.assertEqual(upload.call_args.kwargs['service_date'],'2026-10-08')
            upload.reset_mock()
            self.assertEqual(self.post(role='CEMPLANG').status_code,403)
            upload.assert_not_called()

    def test_invalid_oversize_and_drive_failure(self):
        self.assertEqual(self.post('invalid').status_code,422)
        with self.assertRaises(ValueError):decode_evidence(base64.b64encode(b'x'*(MAX_BYTES+1)).decode())
        with patch('backend.accountant_drive.upload_accountant_artifact',side_effect=RuntimeError('secret')):
            response=self.post()
            self.assertEqual(response.status_code,502)
            self.assertNotIn('secret',response.text)

    def test_pdf(self):
        from pypdf import PdfWriter
        pdf=BytesIO();writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.write(pdf)
        self.assertEqual(decode_evidence(base64.b64encode(pdf.getvalue()).decode())[1],'application/pdf')

    def test_dummy_ok_but_still_labelled(self):
        row={'code':'KS-01','received':100,'distributed':100,'bnba':'Ya','bastNo':'DRAFT-WAJIB-DIGANTI/2026-10-08/KS-01','bastLink':'https://example.invalid/BAST-DRAFT-WAJIB-DIGANTI/2026-10-08/KS-01'}
        data={'pm':{'rows':[row]}}
        preview=compute_preview({},data,'2026-10-08',True)
        checks={x['no']:x for x in preview['checks']}
        self.assertTrue(checks['07']['ok']);self.assertTrue(checks['08']['ok'])
        self.assertIn('Dummy',checks['08']['detail'])
        self.assertNotEqual(preview['pmRows'][0]['bastStatus'],'Terlampir')
        row['bnba']='Tidak'
        self.assertFalse(next(x for x in compute_preview({},data,'2026-10-08',True)['checks'] if x['no']=='07')['ok'])

