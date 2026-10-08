from contextlib import contextmanager, ExitStack
from copy import deepcopy
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
import test_generated_document_api as fixture
from backend import lpdh_api as api


class CancelValidationTests(unittest.TestCase):
    def setUp(self):
        self.state={'status':'READY','data':{'_reviewValidated':True,'incentive':{'paidAmount':5572000},'operations':[{'sourceDocumentId':47}]}}
        self.calls=[]
        self.committed=False
        @contextmanager
        def connection(): yield self
        self.stack=ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(api,'connection',connection))
        self.stack.enter_context(patch.object(api,'_load_daily',side_effect=lambda *args:deepcopy(self.state)))
        self.stack.enter_context(patch.object(fixture.api,'daily_lock',lambda *args:None))
        app=FastAPI()
        @app.middleware('http')
        async def authenticated(request,call_next):
            request.state.sppg_role=request.headers.get('x-test-role','')
            return await call_next(request)
        app.include_router(api.router)
        self.client=TestClient(app)

    @contextmanager
    def cursor(self): yield self

    def execute(self,sql,args): self.calls.append((sql,args))

    def commit(self): self.committed=True

    def cancel(self,role='MAJA'):
        return self.client.post('/v1/lpdh/daily/validation/cancel',json={'site':'MAJA','service_date':'2026-10-08'},headers={'x-test-role':role})

    def test_only_marker_and_status_changed(self):
        before=deepcopy(self.state)
        response=self.cancel()
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(self.committed)
        self.assertEqual(self.state,before)
        self.assertEqual(len(self.calls),1)
        self.assertIn("jsonb_set(data,'{_reviewValidated}','false'::jsonb)",self.calls[0][0])
        self.assertNotIn('accountant_documents',self.calls[0][0])

    def test_final_snapshot_protected(self):
        self.state['status']='GENERATED'
        self.assertEqual(self.cancel().status_code,409)
        self.assertFalse(self.calls)

    def test_other_site_forbidden(self):
        self.assertEqual(self.cancel('CEMPLANG').status_code,403)
        self.assertFalse(self.calls)

