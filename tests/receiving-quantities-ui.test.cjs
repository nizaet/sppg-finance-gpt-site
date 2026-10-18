const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const React = require(root + '/node_modules/react');
const { act, create } = require(root + '/node_modules/react-test-renderer');
const esbuild = require(root + '/node_modules/esbuild');
const output = path.join(fs.mkdtempSync('/tmp/sppg-receipt-ui-'), 'test.cjs');
const calls = [], questions = [];
let approval = true, resolveSave;
const receipt = { id: 1, purchase_order_id: 10, site: 'MAJA', vendor_code: 'HOLIL', items: [{ receipt_item_id: 11, po_item_name: 'Wortel', received_qty: '10.0000', rejected_qty: '0', unit: 'kg', updated_at: '2026-10-18T02:35:00Z' }] };
const data = { purchaseOrderId: 10, site: 'MAJA', status: 'RECEIVED', allReceived: true, remainingCount: 0, items: [{ id: 101, item_name: 'Wortel', poQty: 10, receivedQty: 10, remainingQty: 0, complete: true, unit: 'kg' }] };
global.__RECEIPT_API = {
  getPoReceivingConfirmation: async () => data,
  getGoodsReceipts: async () => ({ items: [receipt] }),
  confirmPoReceiving: async (id, payload) => { calls.push({ name: 'receive', id, payload }); return { message: 'Tersimpan' }; },
  correctGoodsReceipt: (id, payload) => { calls.push({ name: 'correct', id, payload }); return new Promise(resolve => { resolveSave = resolve; }); },
};
global.window = { confirm: text => { questions.push(text); return approval; }, dispatchEvent() {} };
global.CustomEvent = class {};
const h = React.createElement;
let view;
const textOf = node => React.Children.toArray(node.props.children).filter(x => typeof x === 'string').join('');
const button = label => view.root.findAllByType('button').find(node => textOf(node).trim() === label);
const input = label => view.root.findAllByType('input').find(node => node.props['aria-label'] === label);
(async () => {
  await esbuild.build({ stdin: { contents: "export {default as Receiver} from './src/operations/PoReceivingConfirm.jsx'; export {default as Editor,parseReceiptQty} from './src/operations/GoodsReceiptEditor.jsx';", resolveDir: root }, bundle: true, platform: 'node', format: 'cjs', outfile: output, plugins: [{ name: 'fixtures', setup(build) {
    build.onResolve({ filter: /^react$/ }, () => ({ path: require.resolve(root + '/node_modules/react'), external: true }));
    build.onResolve({ filter: /^\.\/apiClient$/ }, () => ({ path: 'api', namespace: 'fixture' }));
    build.onLoad({ filter: /.*/, namespace: 'fixture' }, () => ({ contents: 'export const operationsApi=global.__RECEIPT_API;', loader: 'js' }));
  } }] });
  const { Receiver, Editor, parseReceiptQty } = require(output);
  assert.equal(parseReceiptQty('5,04'), 5.04);
  for (const value of ['', '-1', 'NaN', 'Infinity', '1.00001', '1,2,3']) assert.ok(Number.isNaN(parseReceiptQty(value)), value);
  await act(async () => { view = create(h(Receiver, { poId: 10, status: 'RECEIVED', inline: true })); });
  assert.ok(button('Ubah penerimaan'), 'correction remains available after complete receipt');
  await act(async () => input('Jumlah datang Wortel').props.onChange({ target: { value: '2,5' } }));
  approval = false;
  await act(async () => button('Catat datang').props.onClick());
  assert.equal(calls.length, 0, 'cancel does not save');
  approval = true;
  await act(async () => button('Catat datang').props.onClick());
  assert.equal(calls[0].payload.mode, 'ACTUAL');
  assert.equal(calls[0].payload.items[0].received_qty, 2.5);
  assert.equal(calls[0].payload.items[0].expected_received_qty, 10);
  assert.ok(questions.at(-1).includes('melebihi sisa PO'));
  assert.ok(questions.at(-1).includes('12,5'));
  await act(async () => view.unmount());
  let saved = false;
  await act(async () => { view = create(h(Editor, { receipt, onSaved: () => { saved = true; } })); });
  await act(async () => input('Jumlah datang Wortel').props.onChange({ target: { value: '8,5' } }));
  await act(async () => input('Reject Wortel').props.onChange({ target: { value: '9' } }));
  const reason = view.root.findAllByType('input').find(node => node.props.placeholder?.includes('terlanjur'));
  await act(async () => reason.props.onChange({ target: { value: 'Terlanjur klik semua sesuai' } }));
  assert.equal(button('Simpan koreksi').props.disabled, true, 'reject cannot exceed arrival');
  await act(async () => input('Reject Wortel').props.onChange({ target: { value: '1' } }));
  const save = button('Simpan koreksi').props.onClick;
  act(() => { save(); save(); });
  assert.equal(calls.filter(call => call.name === 'correct').length, 1, 'double click is one save');
  const line = calls.at(-1).payload.items[0];
  assert.equal(line.received_qty, 8.5); assert.equal(line.rejected_qty, 1);
  assert.equal(line.expected_received_qty, 10); assert.equal(line.expected_updated_at, receipt.items[0].updated_at);
  assert.equal(receipt.items[0].received_qty, '10.0000', 'editing preserves source snapshot');
  await act(async () => resolveSave({ saved: true }));
  assert.ok(saved);
  await act(async () => input('Jumlah datang Wortel').props.onChange({ target: { value: '0' } }));
  await act(async () => input('Reject Wortel').props.onChange({ target: { value: '0' } }));
  assert.equal(button('Simpan koreksi').props.disabled, false, 'zero can undo mistaken arrival');
  await act(async () => view.unmount());
  console.log('PASS actual quantity, decimal comma, cancel, overdelivery review, correction after complete, reject validation, double click, source snapshot and zero correction');
})().catch(error => { console.error(error); process.exitCode = 1; });
