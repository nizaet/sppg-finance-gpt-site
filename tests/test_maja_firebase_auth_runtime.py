import subprocess
import unittest
from pathlib import Path


class MajaFirebaseAuthRuntimeTests(unittest.TestCase):
    def test_owner_signin_precedes_ledger_access(self):
        source = (Path(__file__).resolve().parents[1] / "src/auth/maja-firebase.js").read_text()
        script = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const code = require('node:fs').readFileSync(0, 'utf8')
  .replace(/^import .*;$/gm, '').replace('export async function', 'async function');
function scenario(options = {}) {
  const calls = [];
  const app = {name: '[DEFAULT]'};
  const ctx = {
    readSessionToken: () => options.noSession ? '' : 'railway-session',
    authApi: {firebaseMajaToken: async token => {
      assert.equal(token, 'railway-session'); calls.push('token');
      return options.noToken ? {} : {token: 'custom-token'};
    }},
    getApps: () => options.existing ? [app] : [{name: 'unrelated-app'}],
    getApp: () => {calls.push('reuse'); return app;},
    initializeApp: () => {calls.push('init'); return app;},
    inMemoryPersistence: {type: 'NONE'},
    initializeAuth: (input, config) => {
      assert.equal(input, app); assert.equal(config.persistence.type, 'NONE');
      calls.push('isolated-auth'); return {app};
    },
    signInWithCustomToken: async (auth, token) => {
      assert.equal(token, 'custom-token'); calls.push('signin');
      if (options.gate) await options.gate;
      if (options.noUser) return {};
      return {user: {getIdTokenResult: async force => {
        assert.equal(force, true); calls.push('claims');
        return {claims: options.claims || {sppg_site: 'MAJA', sppg_role: 'OWNER'}};
      }}};
    },
  };
  vm.createContext(ctx); vm.runInContext(code, ctx);
  return {calls, run: () => ctx.authenticateMajaFirebase({projectId: 'test'})};
}
(async () => {
  for (const existing of [true, false]) {
    const test = scenario({existing}); await test.run();
    assert.deepEqual(test.calls, ['token', existing ? 'reuse' : 'init', 'isolated-auth', 'signin', 'claims']);
  }
  for (const options of [{noSession:true}, {noToken:true}, {noUser:true},
    {claims:{sppg_site:'CEMPLANG',sppg_role:'OWNER'}},
    {claims:{sppg_site:'MAJA',sppg_role:'MAJA'}}, {claims:{}}]) {
    const test = scenario(options); await assert.rejects(test.run());
    if (options.noSession || options.noToken) assert.ok(!test.calls.includes('signin'));
  }
  let release, ready = false;
  const test = scenario({gate: new Promise(resolve => {release = resolve;})});
  const promise = test.run().then(() => {ready = true;});
  await Promise.resolve(); await Promise.resolve();
  assert.equal(ready, false); assert.ok(!test.calls.includes('claims'));
  release(); await promise; assert.equal(ready, true);
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
        result = subprocess.run(["node", "-e", script], input=source, text=True,
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
