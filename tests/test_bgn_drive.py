"""Isolated security contracts: no live OAuth, Drive or financial changes."""
import json
import os
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode, urlparse, parse_qs
import test_generated_document_api
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Response
from starlette.requests import Request
from backend import bgn_drive as drive, bgn_drive_api as api


class Database:
    def __init__(self,saved=None):self.saved=saved;self.calls=[];self.commits=0
    @contextmanager
    def connection(self):yield self
    @contextmanager
    def cursor(self):yield self
    def execute(self,sql,args=()):self.calls.append((sql,args))
    def fetchone(self):
        if self.calls[-1][0].startswith('delete from lpdh_bgn_drive_oauth_states'):
            saved=self.saved;self.saved=None;return saved
        return self.saved
    def commit(self):self.commits+=1


def callback_request(cookie=True):
    headers=[(b'cookie',b'sppg_bgn_oauth_browser=test-browser')] if cookie else []
    return Request({'type':'http','method':'GET','path':'/v1/lpdh/bgn-drive/oauth/callback',
        'query_string':urlencode({'state':'test-state','code':'synthetic-code'}).encode(),'headers':headers})


class BgnDriveTests(unittest.TestCase):
    def test_site_authorization_and_fixed_destinations(self):
        request=SimpleNamespace(state=SimpleNamespace(sppg_role='MAJA'))
        api.authorized(request,'MAJA')
        with self.assertRaises(HTTPException):api.authorized(request,'CEMPLANG')
        with self.assertRaises(HTTPException):api.authorized(request,'OTHER')
        self.assertNotEqual(drive.SITES['MAJA'][1],drive.SITES['CEMPLANG'][1])

    def test_identity_scope_email_verified_and_refresh_token_required(self):
        tokens={'access_token':'synthetic','scope':drive.DRIVE_SCOPE,'refresh_token':'secret-test'}
        with patch.object(drive,'json_request',return_value={'email':drive.SITES['MAJA'][0],'email_verified':True}):
            self.assertEqual(drive.validate_identity('MAJA',tokens),drive.SITES['MAJA'][0])
            with self.assertRaises(ValueError):drive.validate_identity('CEMPLANG',tokens)
            with self.assertRaises(ValueError):drive.validate_identity('MAJA',{**tokens,'scope':'openid email'})
            with self.assertRaises(ValueError):drive.validate_identity('MAJA',{**tokens,'refresh_token':''})
        with patch.object(drive,'json_request',return_value={'email':drive.SITES['MAJA'][0],'email_verified':False}):
            with self.assertRaises(ValueError):drive.validate_identity('MAJA',tokens)

    def test_token_encryption_roundtrip_and_wrong_key_rejected(self):
        with patch.dict(os.environ,{'SPPG_BGN_DRIVE_TOKEN_KEY':Fernet.generate_key().decode()}):
            encrypted=drive.cipher().encrypt(b'synthetic-refresh-token')
            self.assertNotIn(b'synthetic-refresh-token',encrypted)
            self.assertEqual(drive.cipher().decrypt(encrypted),b'synthetic-refresh-token')
        with patch.dict(os.environ,{'SPPG_BGN_DRIVE_TOKEN_KEY':Fernet.generate_key().decode()}):
            with self.assertRaises(InvalidToken):drive.cipher().decrypt(encrypted)

    def test_start_browser_cookie_pkce_and_single_use_state(self):
        db=Database();response=Response();request=SimpleNamespace(state=SimpleNamespace(sppg_role='MAJA'))
        with patch.object(api,'connection',db.connection),patch.object(drive,'configured',return_value=True),patch.object(drive,'client',return_value=('123-client','hidden')):
            result=api.start(api.SiteIn(site='MAJA'),request,response)
        params=parse_qs(urlparse(result['authorizationUrl']).query)
        self.assertEqual(params['redirect_uri'],[drive.CALLBACK]);self.assertEqual(params['code_challenge_method'],['S256'])
        self.assertNotIn('hidden',result['authorizationUrl'])
        cookies=response.headers['set-cookie'];self.assertIn('HttpOnly',cookies);self.assertIn('Secure',cookies);self.assertIn('SameSite=lax',cookies)
        state_write=[args for sql,args in db.calls if sql.startswith('insert into lpdh_bgn_drive_oauth_states')][0]
        self.assertEqual(state_write[0],drive.digest(params['state'][0]))
        self.assertNotEqual(state_write[0],params['state'][0])

    def test_callback_missing_cookie_never_exchanges_code(self):
        request=callback_request(False)
        with patch.object(drive,'exchange') as exchange:
            result=api.callback(request)
        exchange.assert_not_called();self.assertNotIn('synthetic-code',result.body.decode());self.assertEqual(request.scope['query_string'],b'')

    def test_callback_consumed_once_and_only_ciphertext_saved(self):
        db=Database({'site':'MAJA','verifier':'synthetic-verifier'})
        tokens={'access_token':'short-lived','refresh_token':'secret-test','scope':drive.DRIVE_SCOPE}
        with patch.dict(os.environ,{'SPPG_BGN_DRIVE_TOKEN_KEY':Fernet.generate_key().decode()}),patch.object(api,'connection',db.connection),patch.object(drive,'exchange',return_value=tokens) as exchange,patch.object(drive,'validate_identity',return_value=drive.SITES['MAJA'][0]):
            result=api.callback(callback_request());again=api.callback(callback_request())
            self.assertIn('tersambung',result.body.decode());self.assertIn('gagal',again.body.decode())
            exchange.assert_called_once()
            writes=[args for sql,args in db.calls if sql.startswith('insert into lpdh_bgn_drive_connections')]
            self.assertEqual(len(writes),1);self.assertNotIn('secret-test',writes[0][2]);self.assertNotIn('short-lived',result.body.decode())
            connection_sql=next(sql for sql,args in db.calls if sql.startswith('insert into lpdh_bgn_drive_connections'))
            self.assertIn('lpdh_bgn_drive_connections.email=excluded.email',connection_sql)
            self.assertIn('then lpdh_bgn_drive_connections.folder_id else null end',connection_sql)
            self.assertNotIn('folder_id=null',connection_sql)
            sql=db.calls[0][0];self.assertIn('browser_hash=%s',sql);self.assertIn('expires_at>now()',sql)

    def test_folder_selection_cannot_cross_sites(self):
        api_mock=SimpleNamespace(files=lambda:None)
        with self.assertRaises(ValueError):drive.validate_folder(api_mock,'MAJA',drive.SITES['CEMPLANG'][1])

    def test_assigned_folder_still_requires_google_permission_before_save(self):
        request=SimpleNamespace(state=SimpleNamespace(sppg_role='MAJA'))
        payload=api.FolderIn(site='MAJA',folder_id=drive.SITES['MAJA'][1])
        db=Database({'email':drive.SITES['MAJA'][0]})
        with patch.object(api,'connection',db.connection),patch.object(drive,'service',return_value='fake-service'),patch.object(drive,'validate_folder',side_effect=ValueError('not authorized')):
            with self.assertRaises(HTTPException) as error:api.folder(payload,request)
            self.assertEqual(error.exception.status_code,403)
            self.assertEqual(db.commits,0)
            self.assertFalse(any(sql.startswith('update ') for sql,args in db.calls))
        with patch.object(api,'connection',db.connection),patch.object(drive,'service',return_value='fake-service'),patch.object(drive,'validate_folder') as validate:
            self.assertTrue(api.folder(payload,request)['folderReady'])
            validate.assert_called_once_with('fake-service','MAJA',drive.SITES['MAJA'][1])
            self.assertEqual(db.commits,1)
        payload.folder_id=drive.SITES['CEMPLANG'][1]
        with self.assertRaises(HTTPException) as error:api.folder(payload,request)
        self.assertEqual(error.exception.status_code,422)

    def test_disconnected_upload_fails_without_internal_fallback(self):
        db=Database()
        with patch.object(drive,'service') as service:
            with self.assertRaises(ValueError):drive.upload(db,'MAJA','2026-10-07','test-artifact','test.pdf',b'pdf','application/pdf')
            service.assert_not_called()

    def test_live_check_verifies_folder_without_uploading_or_mutating(self):
        db=Database({'email':drive.SITES['MAJA'][0],'folder_id':drive.SITES['MAJA'][1]})
        current={'configured':True,'connected':True,'folderReady':True}
        with patch.object(api,'status',return_value=current),patch.object(api,'connection',db.connection),patch.object(drive,'service',return_value='fake-service'),patch.object(drive,'validate_folder') as validate,patch.object(drive,'upload') as upload:
            result=api.check(api.SiteIn(site='MAJA'),SimpleNamespace(),Response())
            self.assertTrue(result['folderReady']);self.assertIn('Pemeriksaan berhasil',result['detail']);self.assertIn('checkedAt',result)
            validate.assert_called_once_with('fake-service','MAJA',drive.SITES['MAJA'][1]);upload.assert_not_called()
            self.assertFalse(any(sql.startswith(('update ','insert ','delete ')) for sql,args in db.calls))

    def test_live_check_does_not_report_ready_after_provider_failure(self):
        db=Database({'email':drive.SITES['CEMPLANG'][0],'folder_id':drive.SITES['CEMPLANG'][1]})
        with patch.object(api,'status',return_value={'configured':True,'connected':True,'folderReady':True}),patch.object(api,'connection',db.connection),patch.object(drive,'service',side_effect=ValueError('synthetic-private-token')):
            result=api.check(api.SiteIn(site='CEMPLANG'),SimpleNamespace(),Response())
            self.assertFalse(result['folderReady']);self.assertIn('belum berhasil',result['detail']);self.assertNotIn('synthetic-private-token',result['detail'])

    def test_live_check_unselected_folder_checks_google_account(self):
        db=Database({'email':drive.SITES['MAJA'][0],'folder_id':None})
        with patch.object(api,'status',return_value={'configured':True,'connected':True,'folderReady':False}),patch.object(api,'connection',db.connection),patch.object(drive,'access_token',return_value='private-token') as token:
            result=api.check(api.SiteIn(site='MAJA'),SimpleNamespace(),Response())
            token.assert_called_once();self.assertFalse(result['folderReady']);self.assertIn('Folder belum dipilih',result['detail']);self.assertNotIn('private-token',json.dumps(result))


if __name__=='__main__':unittest.main()

