const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const deps = process.env.SPPG_UI_TEST_MODULES || path.join(root, 'node_modules');
const React = require(deps + '/react');
const { act, create } = require(deps + '/react-test-renderer');
const esbuild = require(deps + '/esbuild');
const temp = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'sppg-calendar-actions-'));
const output = path.join(temp, 'test.cjs');
const configs = new Map();
function loadConfig(file) {
  if (configs.has(file)) return configs.get(file);
  let code = fs.readFileSync(path.join(root, file), 'utf8');
  const env = { console, process, defineConfig: x => x, react: () => ({ name: 'react' }) };
  code = code.replace(/^import\s+(\w+)\s+from\s+["'](\.\/[^"']+)["'];?\s*$/gm, (_, name, dep) => { env[name] = loadConfig(dep.slice(2)); return ''; });
  code = code.replace(/^import .*;\s*$/gm, '').replace(/export default /g, 'result = ');
  vm.createContext(env); vm.runInContext(code, env, { filename: file });
  configs.set(file, env.result); return env.result;
}
const plugins = loadConfig('vite.po-list-independent.config.js').plugins.flat().filter(Boolean);
const ordered = [...plugins.filter(p => p.enforce === 'pre'), ...plugins.filter(p => p.enforce !== 'pre')];

const calls = [], queue = [];
let calendarRows = [], deferReceipts = true, deferDetails = true;
let revisionId = 102;
const deferred = (name, arg) => new Promise((resolve, reject) => queue.push({ name, arg, resolve, reject }));
const receipt = id => ({ purchaseOrderId: id, site: 'MAJA', status: 'SENT', remainingCount: 1, itemCount: 1, completeCount: 0, items: [{ id: id * 10, item_name: 'Barang PO ' + id, poQty: 5, remainingQty: 5, unit: 'kg' }] });
const po = (id, status = 'SENT', revision = 1) => ({ id, site: 'MAJA', po_code: id === 102 ? 'PO-101' : 'PO-' + id, vendor_code: 'HOLIL', status, revision_no: revision, distribution_date: new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta' }).format(new Date()), items: [{ id: id * 10, item_name: 'Item ' + id, po_qty: 5, unit: 'kg' }] });
global.__AUTO_API = new Proxy({}, { get: (_, name) => (arg, payload) => {
  calls.push({ name, arg, payload });
  if (name === 'getPurchaseOrders') return Promise.resolve({ items: calendarRows });
  if (name === 'getPurchaseOrder') return deferDetails ? deferred(name, arg) : Promise.resolve(po(arg, arg === revisionId ? 'DRAFT' : 'SENT', arg === revisionId ? 2 : 1));
  if (name === 'getPoReceivingConfirmation') return deferReceipts ? deferred(name, arg) : Promise.resolve(receipt(arg));
  if (name === 'confirmPoReceiving') return deferred(name, arg);
  if (name === 'revisePurchaseOrder') return Promise.resolve({ purchaseOrderId: revisionId, status: 'DRAFT', changed: false });
  return Promise.resolve({ items: [] });
} });
global.window = { confirm: () => true, addEventListener() {}, removeEventListener() {}, dispatchEvent() {}, setTimeout: fn => fn() };
global.document = { visibilityState: 'visible', addEventListener() {}, removeEventListener() {}, getElementById: () => null };
global.CustomEvent = class CustomEvent { constructor(type, options) { this.type = type; this.detail = options?.detail; } };
let view;
const textOf = node => React.Children.toArray(node.props.children).filter(x => typeof x === 'string').join('');
const button = label => view.root.findAllByType('button').find(x => textOf(x).trim() === label);
const pop = (name, arg) => { const i = queue.findIndex(x => x.name === name && x.arg === arg); assert.ok(i >= 0, `pending ${name} ${arg}`); return queue.splice(i, 1)[0]; };
(async () => {
  await esbuild.build({ stdin: { contents: `export {default as Receiver} from './src/operations/PoReceivingConfirm.jsx'; export {default as Planner} from './src/operations/OperationsPoPlanner.jsx'; export {default as Enhancements} from './src/operations/PoOpsEnhancements.jsx'; export {OperationsActiveContext} from './src/operations/useAutoRead.js'; export * from './src/operations/readCache.js';`, resolveDir: root }, bundle: true, platform: 'node', format: 'cjs', outfile: output, plugins: [{ name: 'production-and-fixtures', setup(build) {
    build.onResolve({ filter: /^react$/ }, () => ({ path: require.resolve(deps + '/react'), external: true }));
    build.onResolve({ filter: /^\.\/apiClient(?:\.js)?$/ }, () => ({ path: 'api', namespace: 'fixture' }));
    build.onLoad({ filter: /.*/, namespace: 'fixture' }, () => ({ contents: 'export const operationsApi=global.__AUTO_API;', loader: 'js' }));
    build.onLoad({ filter: /src\/.*\.(jsx|js)$/ }, args => {
      let code = fs.readFileSync(args.path, 'utf8');
      for (const plugin of ordered) { const result = plugin.transform?.(code, args.path); if (result) code = typeof result === 'string' ? result : result.code; }
      return { contents: code, loader: args.path.endsWith('.jsx') ? 'jsx' : 'js' };
    });
  } }] });

  const { Receiver, Enhancements, Planner, invalidateReads } = require(output);
  const h = React.createElement;
  await act(async () => { view = create(h(Receiver, { poId: 1, poCode: 'ONE', status: 'SENT', inline: true })); });
  await act(async () => view.update(h(Receiver, { poId: 2, poCode: 'TWO', status: 'SENT', inline: true })));
  await act(async () => pop('getPoReceivingConfirmation', 2).resolve(receipt(2)));
  await act(async () => pop('getPoReceivingConfirmation', 1).resolve(receipt(1)));
  assert.ok(JSON.stringify(view.toJSON()).includes('Barang PO 2'));
  assert.ok(!JSON.stringify(view.toJSON()).includes('Barang PO 1'));
  const confirm = button('Semua sesuai').props.onClick;
  act(() => { confirm(); confirm(); });
  assert.equal(calls.filter(c => c.name === 'confirmPoReceiving').length, 1, 'double click sends one mutation');
  await act(async () => pop('confirmPoReceiving', 2).resolve({ purchaseOrderId: 2, message: 'SAVED-TWO' }));
  await act(async () => pop('getPoReceivingConfirmation', 2).resolve({ ...receipt(2), remainingCount: 0, allReceived: true }));
  await act(async () => view.update(h(Receiver, { poId: 3, poCode: 'THREE', status: 'SENT', inline: true })));
  assert.ok(!JSON.stringify(view.toJSON()).includes('SAVED-TWO'), 'success from prior PO must reset');
  assert.ok(!JSON.stringify(view.toJSON()).includes('Barang PO 2'));
  await act(async () => pop('getPoReceivingConfirmation', 3).resolve(receipt(3)));
  act(() => view.unmount()); view = null;
  console.log('PASS receipt state reset, late response isolation and double-click protection');

  invalidateReads(); calendarRows = [po(101), po(103)];
  await act(async () => { view = create(h(Enhancements, { mode: 'calendar', activeSite: 'MAJA' })); });
  const open = id => view.root.findAllByType('button').find(x => x.props.children?.some?.(child => child?.props?.children === 'PO-' + id));
  act(() => { open(101).props.onClick(); open(103).props.onClick(); });
  await act(async () => pop('getPurchaseOrder', 103).resolve(po(103)));
  await act(async () => pop('getPoReceivingConfirmation', 103).resolve(receipt(103)));
  await act(async () => pop('getPurchaseOrder', 101).resolve(po(101)));
  assert.equal(view.root.findByType(Receiver).props.poId, 103, 'late first click cannot replace newest PO');
  act(() => { button('Semua sesuai').props.onClick(); });
  act(() => button('Tutup').props.onClick());
  act(() => { open(101).props.onClick(); });
  await act(async () => pop('getPurchaseOrder', 101).resolve(po(101)));
  await act(async () => pop('getPoReceivingConfirmation', 101).resolve(receipt(101)));
  await act(async () => pop('confirmPoReceiving', 103).resolve({ purchaseOrderId: 103, message: 'OLD-RECEIPT-SAVED' }));
  await act(async () => pop('getPoReceivingConfirmation', 103).resolve({ ...receipt(103), allReceived: true }));
  assert.equal(view.root.findByType(Receiver).props.poId, 101, 'saving old PO cannot reopen it');
  assert.ok(!JSON.stringify(view.toJSON()).includes('OLD-RECEIPT-SAVED'));
  act(() => view.unmount()); view = null;
  console.log('PASS calendar click race and save-then-open-next PO');

  invalidateReads(); deferDetails = false; deferReceipts = false; calendarRows = [po(101), po(102, 'DRAFT', 2)];
  await act(async () => { view = create(h(Planner, { fixedSite: 'MAJA' })); });
  const calendar = view.root.findAllByType(Enhancements).find(x => x.props.mode === 'calendar');
  assert.equal(typeof calendar.props.onEditPo, 'function', 'production calendar connected to the existing editor');
  const edit = calendar.props.onEditPo;
  const before = calls.filter(c => c.name === 'revisePurchaseOrder').length;
  await act(async () => { await Promise.all([edit(po(101)), edit(po(101))]); });
  assert.equal(calls.filter(c => c.name === 'revisePurchaseOrder').length, before + 1);
  const editPanel = view.root.findByProps({ id: 'po-edit-panel-MAJA' });
  assert.ok(JSON.stringify(editPanel.findAllByType('input').map(x => x.props.value)).includes('Item 102'), 'editor loads returned existing revision ID');
  await act(async () => edit(po(102, 'DRAFT', 2)));
  assert.equal(calls.filter(c => c.name === 'revisePurchaseOrder').length, before + 1, 'editing an existing draft does not create another revision');
  assert.equal(calendar.findAllByProps({ className: 'ops-calendar-po-family' }).length, 1, 'one calendar card per PO family and day');
  const draftCard = calendar.findAllByType('button').find(x => x.props.children?.some?.(child => child?.props?.children === 'PO-101'));
  await act(async () => { await draftCard.props.onClick(); });
  await act(async () => { await button('Edit Draft').props.onClick(); });
  assert.equal(calls.filter(c => c.name === 'revisePurchaseOrder').length, before + 1, 'calendar Edit Draft opens editor without cloning');
  assert.ok(view.root.findByProps({ id: 'po-edit-panel-MAJA' }));
  act(() => view.unmount()); view = null;
  console.log('PASS actual production calendar editor, existing draft reuse, double-click guard and grouped revisions');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => { if (view) act(() => view.unmount()); fs.rmSync(temp, { recursive: true, force: true }); });
