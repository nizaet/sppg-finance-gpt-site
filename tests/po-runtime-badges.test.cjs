const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const deps = process.env.SPPG_UI_TEST_MODULES || path.resolve(__dirname, '../node_modules');
const dir = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'sppg-badges-'));
let mutation = () => {}, frames = [];
class Element {
  constructor(text = '') { this.dataset = {}; this.children = []; this.text = text; this.style = { cssText: '', removeProperty(name) { delete this[name]; } }; }
  get textContent() { return this.text + this.children.map(x => x.textContent).join(''); }
  set textContent(value) { this.text = value; mutation(); }
  appendChild(child) { child.parent = this; this.children.push(child); mutation(); }
  remove() { this.parent.children = this.parent.children.filter(x => x !== this); mutation(); }
  querySelectorAll() { return this.children.filter(x => x.dataset.runtimeReceivingBadge); }
  querySelector(selector) { const type = selector.match(/="([^"]+)"/)?.[1]; return this.children.find(x => x.dataset.runtimeReceivingBadge === type) || null; }
}
const received = new Element('PO-MAJA-1'), draft = new Element('PO-MAJA-1');
received.dataset = { poId: '1', poStatus: 'RECEIVED' }; draft.dataset = { poId: '2', poStatus: 'DRAFT' };
global.document = { documentElement: { dataset: { appTheme: 'dark' } }, createElement: () => new Element(), querySelectorAll: selector => selector.includes('[data-po-actual-calendar]') ? [received, draft] : [] };
global.window = { location: { origin: 'http://fixture' }, fetch: async () => ({}), addEventListener() {}, requestAnimationFrame(fn) { frames.push(fn); } };
global.MutationObserver = class { constructor(callback) { mutation = callback; } observe() {} };
function flush() {
  let count = 0;
  while (frames.length) { assert.ok(++count < 5, 'badge mutations must settle instead of scheduling an endless frame loop'); frames.shift()(); }
  return count;
}
(async () => {
  await require(deps + '/esbuild').build({ entryPoints: [path.resolve(__dirname, '../src/runtimeUiPolish.js')], bundle: true, platform: 'node', format: 'cjs', outfile: dir + '/runtime.cjs', define: { 'import.meta.env': '{}' }, plugins: [{ name: 'session-fixture', setup(build) {
    build.onResolve({ filter: /auth\/session\.js$/ }, () => ({ path: 'auth', namespace: 'fixture' }));
    build.onLoad({ filter: /.*/, namespace: 'fixture' }, () => ({ contents: 'export const readSessionToken=()=>"";' }));
  } }] });
  require(dir + '/runtime.cjs').installRuntimeUiPolish();
  assert.equal(flush(), 2);
  assert.equal(received.children.length, 1);
  assert.equal(draft.children.length, 0, 'a received revision must not color a draft with the same PO code');
  assert.ok(received.children[0].style.cssText.includes('#b8dec9'), 'readable dark-mode status');
  mutation(); assert.equal(flush(), 1, 'unchanged badges do not create child mutations');
  received.dataset.poStatus = 'SENT'; mutation(); flush();
  assert.equal(received.children.length, 0, 'remove badge when status changes');
  console.log('PASS exact revision status and idempotent runtime badge updates');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => fs.rmSync(dir, { recursive: true, force: true }));
