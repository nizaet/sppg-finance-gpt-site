"""Execute the served calculator bootstrap with deterministic Firebase doubles."""
import json
import subprocess
import unittest

from backend.calculator_pages import calculator_html


class CalculatorFirebaseRuntimeTests(unittest.TestCase):
    def test_bootstrap_isolation_claims_and_permission_errors(self):
        pages = {}
        for unit in ("maja", "cemplang"):
            html = calculator_html(unit, "OWNER")
            self.assertIn("getAuth, initializeAuth, inMemoryPersistence,", html)
            # Includes both auth entry points, not just initial page loading.
            self.assertNotIn("if (!auth) auth = getAuth(app);", html)
            start = html.index("        async function initializeFirebaseAndLoadData() {")
            end = html.index("        function setupAllListeners() {", start)
            auth_start = html.index("        async function authWithFirebase() {")
            auth_end = html.index("        function enableUI() {", auth_start)
            pages[unit] = html[start:end] + html[auth_start:auth_end]

        script = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const pages = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
function page(unit, options = {}) {
    const logs = [], reads = [], instances = [];
    const ctx = {
        app: null, db: null, auth: null, userId: null,
        firebaseConfig: {apiKey: 'test', projectId: 'sppg-finance-gpt'},
        firebaseConnection: {source: 'embedded'},
        appId: unit === 'maja' ? 'sppg-maja-gpt-site' : 'sppg-cemplang2-gpt-site',
        window: {__legacyUnitId: unit, __firestoreDatabaseId: unit === 'maja' ? '(default)' : 'cemplang2'},
        inMemoryPersistence: {type: 'NONE'},
        initializeApp: (config, name) => ({config, name}),
        initializeAuth: (app, config) => {
            assert.equal(app.name, `sppg-calculator-${unit}`);
            assert.equal(config.persistence.type, 'NONE');
            const auth = {app, currentUser: null}; instances.push(auth); return auth;
        },
        getAuth: () => {throw Error('Shared persistent Auth must not be used');},
        getFirestore: (app, database = '(default)') => ({app, database}),
        getInitialFirebaseAuthToken: async () => 'test-token',
        signInWithCustomToken: async (auth) => {
            if (options.gate) await options.gate;
            const user = {uid: `sppg-owner-${unit}`, getIdTokenResult: async () => ({claims: {
                sppg_site: options.site || unit.toUpperCase(), sppg_role: options.role || 'OWNER'
            }})};
            auth.currentUser = user; return {user};
        },
        logActivity: (message) => logs.push(message), console: {error() {}},
        setLogLevel() {}, setupAllListeners() {},
        enableUI: () => {ctx.ready = true;}, clearPlanForm() {},
        initChatWidget() {}, initMenuInspiration() {}, initAdminSettings() {},
        generateMenuCaptionBtn: {}, handlePrintMenuDisplay() {},
        printSOPBtn: {}, handlePrintSOP() {}, recheckSOPBtn: null,
        printPOBtn: {}, handlePrintPO() {}, printNutritionBtn: {}, handlePrintNutrition() {},
    };
    for (const name of ['Recipes', 'MasterPriceList', 'CustomGramasi', 'SavedPlans', 'BumbuList']) {
        ctx[`load${name}`] = async () => {
            assert.equal(ctx.auth.currentUser.uid, `sppg-owner-${unit}`);
            assert.equal(ctx.db.database, ctx.window.__firestoreDatabaseId);
            reads.push(name);
            if (name === options.fail) throw Object.assign(Error('Missing or insufficient permissions.'), {code: 'permission-denied'});
        };
    }
    vm.createContext(ctx); vm.runInContext(pages[unit], ctx);
    return {ctx, logs, reads, instances, run: () => ctx.initializeFirebaseAndLoadData()};
}
(async () => {
    // Two kitchens may initialize at the same time and must keep their own user.
    const maja = page('maja'), cemplang = page('cemplang');
    await Promise.all([maja.run(), cemplang.run()]);
    assert.equal(maja.ctx.ready, true); assert.equal(cemplang.ctx.ready, true);
    assert.equal(maja.reads.length, 5); assert.equal(cemplang.reads.length, 5);
    assert.notEqual(maja.ctx.auth.app.name, cemplang.ctx.auth.app.name);
    assert.equal(maja.ctx.auth.currentUser.uid, 'sppg-owner-maja');

    let release;
    const waiting = page('maja', {gate: new Promise(resolve => {release = resolve;})});
    const running = waiting.run(); await Promise.resolve();
    assert.equal(waiting.reads.length, 0);
    release(); await running; assert.equal(waiting.ctx.ready, true);

    for (const options of [{site: 'CEMPLANG'}, {role: 'CEMPLANG'}]) {
        const denied = page('maja', options); await denied.run();
        assert.equal(denied.reads.length, 0); assert.equal(denied.ctx.ready, undefined);
        assert.ok(denied.logs.some(log => log.includes('ERROR Kritis')));
    }
    const denied = page('maja', {fail: 'SavedPlans'}); await denied.run();
    assert.equal(denied.ctx.ready, undefined);
    assert.ok(denied.logs.some(log => log.includes('sppg-finance-gpt/(default)/artifacts/sppg-maja-gpt-site/public/data/dailyPlans [permission-denied]')));
    assert.ok(!denied.logs.some(log => log.includes('Semua data awal berhasil')));
    assert.ok(!denied.logs.some(log => log.includes('Aplikasi siap')));
    process.stdout.write('calculator runtime regression passed\n');
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
        result = subprocess.run(
            ["node", "-e", script], input=json.dumps(pages), text=True,
            capture_output=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
