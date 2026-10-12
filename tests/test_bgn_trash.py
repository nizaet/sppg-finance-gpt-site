"""Synthetic only: no production cancellation or Drive trash operations."""
import hashlib
import unittest
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock,patch
import test_generated_document_api as fixture
from fastapi import HTTPException,Response
from backend import bgn_trash as trash,bgn_drive_api as api


class TrashTests(unittest.TestCase):
    def request(self):
        return {'id':3,'site':'MAJA','file_id':'file','folder_id':'day','artifact_key':'document-revision-1',
            'content_hash':'hash','service_date':'2026-10-12','status':'PENDING'}

    def drive(self,request):
        marker=hashlib.sha256(('MAJA|'+request['artifact_key']+'|hash').encode()).hexdigest()
        data={'file':{'id':'file','mimeType':'application/pdf','parents':['day'],'trashed':False,
                'appProperties':{'sppgArtifact':marker},'capabilities':{'canTrash':True}},
            'day':{'name':'2026-10-12','mimeType':'application/vnd.google-apps.folder','parents':['month']},
            'month':{'name':'2026-10','mimeType':'application/vnd.google-apps.folder','parents':[trash.drive.SITES['MAJA'][1]]}}
        files=Mock()
        files.get.side_effect=lambda **kw:Mock(execute=lambda:deepcopy(data[kw['fileId']]))
        def update(**kw):
            self.assertEqual(kw['fileId'],'file');self.assertEqual(kw['body'],{'trashed':True})
            data['file']['trashed']=True
            return Mock(execute=lambda:deepcopy(data['file']))
        files.update.side_effect=update
        service=Mock();service.files.return_value=files
        return service,files,data

    def test_valid_bgn_file_trash_readback_and_idempotence(self):
        request=self.request();service,files,data=self.drive(request)
        trash.trash_file(service,request);self.assertTrue(data['file']['trashed'])
        trash.trash_file(service,request);self.assertEqual(files.update.call_count,1)
        files.delete.assert_not_called()

    def test_refuses_wrong_marker_internal_folder_cross_site_and_missing_permission(self):
        for change in ('marker','day','root','permission','folder'):
            request=self.request();service,files,data=self.drive(request)
            if change=='marker':data['file']['appProperties']['sppgArtifact']='other'
            if change=='day':data['file']['parents']=['elsewhere']
            if change=='root':data['month']['parents']=[trash.drive.SITES['CEMPLANG'][1]]
            if change=='permission':data['file']['capabilities']['canTrash']=False
            if change=='folder':data['file']['mimeType']='application/vnd.google-apps.folder'
            with self.assertRaises(ValueError):trash.trash_file(service,request)
            files.update.assert_not_called();files.delete.assert_not_called()

    def test_readback_failure_is_not_reported_as_success(self):
        request=self.request();service,files,data=self.drive(request)
        files.update.side_effect=lambda **kw:Mock(execute=lambda:{'trashed':False})
        with self.assertRaises(ValueError):trash.trash_file(service,request)

    def test_unrecognized_or_internal_link_cannot_enqueue(self):
        cur=Mock();cur.fetchall.return_value=[]
        self.assertEqual(trash.enqueue(cur,'MAJA','server-key','https://internal/pdf','OWNER')['status'],'SKIPPED')
        self.assertEqual(cur.execute.call_count,1)
        self.assertEqual(trash.enqueue(cur,'MAJA','server-key',None,'OWNER')['status'],'SKIPPED')

    def test_google_failure_persists_retry_and_hides_provider_details(self):
        request=self.request();saved={'email':trash.drive.SITES['MAJA'][0],'folder_id':trash.drive.SITES['MAJA'][1]}
        cur=Mock();cur.fetchone.side_effect=[request,saved]
        conn=Mock();conn.cursor.return_value.__enter__=Mock(return_value=cur)
        conn.cursor.return_value.__exit__=Mock(return_value=False)
        @contextmanager
        def connection():yield conn
        with patch.object(trash,'connection',connection),patch.object(trash.drive,'service',side_effect=RuntimeError('secret-token')):
            result=trash.process('MAJA',3)
        self.assertEqual(result['status'],'FAILED');self.assertNotIn('secret-token',result['message'])
        self.assertTrue(any('update lpdh_bgn_trash_requests' in call.args[0] for call in cur.execute.call_args_list))
        conn.commit.assert_called_once()

    def test_missing_site_request_has_no_drive_side_effect(self):
        cur=Mock();cur.fetchone.return_value=None
        conn=Mock();conn.cursor.return_value.__enter__=Mock(return_value=cur);conn.cursor.return_value.__exit__=Mock(return_value=False)
        @contextmanager
        def connection():yield conn
        with patch.object(trash,'connection',connection),patch.object(trash.drive,'service') as service:
            with self.assertRaises(ValueError):trash.process('CEMPLANG',3)
        service.assert_not_called()

    def test_finish_keeps_by_default_and_returns_pending_on_db_failure(self):
        with patch.object(trash,'process',side_effect=RuntimeError('DB unavailable')) as process:
            self.assertEqual(trash.finish('MAJA',None)['status'],'KEPT');process.assert_not_called()
            self.assertEqual(trash.finish('MAJA',{'requestId':3})['status'],'PENDING')

    def test_cross_site_retry_rejected_before_any_mutation(self):
        request=SimpleNamespace(state=SimpleNamespace(sppg_role='MAJA'))
        with patch.object(trash,'process') as process:
            with self.assertRaises(HTTPException) as error:api.trash_retry(api.TrashRetryIn(site='CEMPLANG',request_id=3),request,Response())
        self.assertEqual(error.exception.status_code,403);process.assert_not_called()

    def test_maker_guard_before_enqueue_and_no_trash_if_cancel_rolls_back(self):
        row={'id':1,'site':'MAJA','document_type':'OPERASIONAL','status':'FINAL','service_date':'2026-10-12','header_payload':{},'bgn_pdf_uri':'https://bgn/file'}
        for blocked in (True,False):
            cur=Mock();cur.fetchone.side_effect=[row,{'status':'PENDING'} if blocked else None,None]
            conn=Mock();conn.cursor.return_value.__enter__=Mock(return_value=cur);conn.cursor.return_value.__exit__=Mock(return_value=False)
            @contextmanager
            def connection():yield conn
            with patch.object(fixture.api,'connection',connection),patch.object(fixture.api,'_serialize_document',return_value={'header':{}}),patch.object(fixture.api,'_sync_daily',side_effect=HTTPException(409,'locked')),patch.object(trash,'enqueue',return_value={'requestId':3}) as enqueue,patch.object(trash,'finish') as finish:
                with self.assertRaises(HTTPException):fixture.api.cancel_document(1,fixture.api.CancelDocumentIn(reason='Koreksi',trash_bgn=True),'Bearer MAJA')
                if blocked:enqueue.assert_not_called()
                else:enqueue.assert_called_once()
                finish.assert_not_called();conn.commit.assert_not_called()


if __name__=='__main__':unittest.main()
