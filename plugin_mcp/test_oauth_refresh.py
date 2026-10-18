import hashlib,json,time,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from plugin_mcp import oauth_refresh as refresh
from plugin_mcp import oauth_server as oauth

class Store:
    def __init__(self): self.rows={};self.row=None
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def cursor(self):return self
    def commit(self):pass
    def execute(self,sql,params=None):
        sql=' '.join(sql.lower().split());self.row=None
        if sql.startswith('select *'):
            row=self.rows.get(params[0]);self.row=dict(row) if row else None
        elif sql.startswith('insert into'):
            keys=['token_hash','family_id','client_id','resource','audience','subject','scope','expires_at']
            row=dict(zip(keys,params));row.update(consumed_at=None,revoked_at=None)
            self.rows[row['token_hash']]=row
        elif 'set consumed_at=' in sql:self.rows[params[0]]['consumed_at']=datetime.now(timezone.utc)
        elif 'set revoked_at=' in sql:
            for row in self.rows.values():
                if row['family_id']==params[0]:row['revoked_at']=datetime.now(timezone.utc)
    def fetchone(self):return self.row

class RefreshStoreTests(unittest.TestCase):
    def setUp(self):
        self.store=Store()
        self.p1=patch('plugin_mcp.oauth_refresh.database_ready',return_value=True);self.p1.start()
        self.p2=patch('plugin_mcp.oauth_refresh.connection',return_value=self.store);self.p2.start()
        self.addCleanup(self.p1.stop);self.addCleanup(self.p2.stop)
    def mint(self,client='clientA'):
        return refresh.create_refresh(client,'https://mcp.test/mcp','aud','SPPG_OWNER','sppg:read')
    def rotate(self,token,**overrides):
        args={'client_id':'clientA','resource':'https://mcp.test/mcp','audience':'aud','scope':'sppg:read','allowed_subjects':{'SPPG_OWNER'}};args.update(overrides)
        return refresh.rotate_refresh(token,**args)
    def test_hash_only_and_rotation_keeps_absolute_expiry(self):
        token=self.mint();old=self.store.rows[refresh._hash(token)]
        new=self.rotate(token)['refresh_token']
        self.assertNotEqual(new,token);self.assertNotIn(token,str(self.store.rows))
        self.assertIsNotNone(old['consumed_at'])
        self.assertEqual(self.store.rows[refresh._hash(new)]['expires_at'],old['expires_at'])
    def test_replay_revokes_family_but_not_another_device_session(self):
        old=self.mint();other=self.mint();new=self.rotate(old)['refresh_token']
        with self.assertRaises(ValueError):self.rotate(old)
        with self.assertRaises(ValueError):self.rotate(new)
        self.assertTrue(self.rotate(other)['refresh_token'])
    def test_client_resource_audience_scope_subject_binding_fail_closed(self):
        for kwargs in [{'client_id':'attacker'},{'resource':'https://other.test/mcp'},{'audience':'other'},{'scope':'sppg:write'},{'allowed_subjects':{'OTHER'}}]:
            token=self.mint()
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):self.rotate(token,**kwargs)
            self.assertIsNone(self.store.rows[refresh._hash(token)]['consumed_at'])
    def test_expired_and_unknown_sessions_rejected(self):
        token=self.mint();self.store.rows[refresh._hash(token)]['expires_at']=datetime.now(timezone.utc)-timedelta(seconds=1)
        for value in [token,'unknown','']:
            with self.subTest(value=value),self.assertRaises(ValueError):self.rotate(value)
    def test_unavailable_store_cannot_mint_or_rotate(self):
        with patch('plugin_mcp.oauth_refresh.database_ready',return_value=False):
            with self.assertRaises(RuntimeError):self.mint()
            with self.assertRaises(RuntimeError):self.rotate('no-token')

class Form:
    def __init__(self,data):self.data=data
    async def form(self):return self.data

class RefreshEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_client_refresh_rotates_without_login_and_no_scope_expansion(self):
        with patch.dict('os.environ',{'SPPG_OAUTH_ALLOWED_SUBJECTS':'SPPG_OWNER'}),patch('plugin_mcp.oauth_server.rotate_refresh',return_value={'subject':'SPPG_OWNER','scope':'sppg:read','refresh_token':'new-refresh'}) as rotate,patch('plugin_mcp.oauth_server.issue_access_token',return_value='access'):
            result=await oauth.token(Form({'grant_type':'refresh_token','client_id':oauth.DCR_CLIENT_ID,'refresh_token':'old-refresh'}),'https://auth.test','aud','https://mcp.test/mcp')
        body=json.loads(result.body);self.assertEqual(body['expires_in'],3600);self.assertEqual(body['refresh_token'],'new-refresh')
        self.assertEqual(rotate.call_count,1)
        self.assertIn('no-store',result.headers['cache-control'])
    async def test_invalid_scope_or_client_never_reaches_store(self):
        for data in [{'client_id':'other'},{'client_id':oauth.DCR_CLIENT_ID,'scope':'sppg:write'},{'client_id':oauth.DCR_CLIENT_ID,'resource':'https://attacker.test'}]:
            with patch('plugin_mcp.oauth_server.rotate_refresh') as rotate:
                result=await oauth.token(Form({'grant_type':'refresh_token','refresh_token':'value',**data}),'https://auth.test','aud','https://mcp.test/mcp')
            self.assertEqual(result.status_code,400);rotate.assert_not_called()
    async def test_code_exchange_returns_refresh_only_after_valid_pkce(self):
        verifier='v'*64;code='test-code';key=hashlib.sha256(code.encode('ascii')).hexdigest()
        record={'iat':int(time.time()),'client_id':oauth.DCR_CLIENT_ID,'redirect_uri':oauth.CHATGPT_STABLE_REDIRECT,'resource':'https://mcp.test/mcp','challenge':oauth._b64(hashlib.sha256(verifier.encode('ascii')).digest())}
        with patch.dict(oauth._CODES,{key:record},clear=True),patch('plugin_mcp.oauth_server.create_refresh',return_value='refresh') as create,patch('plugin_mcp.oauth_server.issue_access_token',return_value='access'):
            result=await oauth.token(Form({'grant_type':'authorization_code','code':code,'client_id':oauth.DCR_CLIENT_ID,'redirect_uri':oauth.CHATGPT_STABLE_REDIRECT,'resource':'https://mcp.test/mcp','code_verifier':verifier}),'https://auth.test','aud','https://mcp.test/mcp')
        self.assertEqual(result.status_code,200);self.assertEqual(json.loads(result.body)['refresh_token'],'refresh');create.assert_called_once()
    async def test_refresh_store_failure_returns_no_access_token(self):
        with patch('plugin_mcp.oauth_server.rotate_refresh',side_effect=RuntimeError('DB down')):
            result=await oauth.token(Form({'grant_type':'refresh_token','client_id':oauth.DCR_CLIENT_ID,'refresh_token':'value'}),'https://auth.test','aud','https://mcp.test/mcp')
        self.assertEqual(result.status_code,503);self.assertNotIn('access_token',json.loads(result.body))

if __name__=='__main__':unittest.main()
