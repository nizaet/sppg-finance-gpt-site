const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const React = require('react');
const { create, act } = require('react-test-renderer');
const esbuild = require('esbuild');
const root = path.resolve(__dirname, '..');
const output = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'sppg-documents-')), 'test.cjs');
const records = [], payloads = [], finalCalls = [], downloads = [];
let confirm = false;
global.window = { confirm: () => confirm };
global.__DOCUMENT_API = {
  master: async site => ({ profiles: { KOPERASI: { issuerName: site, recipientAddress: 'Alamat' }, YAYASAN: { issuerName: 'Yayasan', recipientAddress: 'Alamat' } }, categories: ['Gas', 'Alat kebersihan', 'Lain-lain'],
    items: [{ recordKey: 'gas', itemName: 'Gas LPG', kind: 'OPERASIONAL', category: 'Gas', unit: 'tabung', unitPrice: 1000 }, { recordKey: 'sabun', itemName: 'Sabun', kind: 'OPERASIONAL', category: 'Alat kebersihan', unit: 'botol', unitPrice: 200 }],
    volunteers: [{ code: 'R1', name: 'Relawan Uji', role: 'Pengolah', dailyRate: 90000 }], recipients: [{ name: 'Guru Uji', recipientType: 'Guru', unitName: 'SD Uji' }, { name: 'Kader Uji', recipientType: 'Kader', unitName: 'Posyandu Uji' }] }),
  list: async site => ({ documents: records.filter(doc => doc.site === site) }),
  create: async payload => { payloads.push(payload); const document = { id: records.length + 1, site: payload.site, documentType: payload.document_type, documentNumber: `DOC-${records.length + 1}`, status: 'DRAFT', header: payload.header_payload, items: payload.items.map(x => ({ itemName: x.item_name, category: x.category_code, quantity: x.quantity, unit: x.unit, unitPrice: x.unit_price, metadata: x.metadata })), total: payload.items.reduce((sum, x) => sum + x.quantity * x.unit_price, 0) }; records.push(document); return { document }; },
  finalize: async id => { finalCalls.push(id); records.find(doc => doc.id === id).status = 'FINAL'; return { syncedToDaily: true }; },
  pdf: async id => ({ filename: `DOC-${id}.pdf`, mimeType: 'application/pdf', contentBase64: 'JVBERi0=' }),
};
global.__LPDH_API = { getFinalPlan: async () => ({ plan: { payload: { shoppingListJSON: { shoppingList: [{ item: 'Beras', jumlah: 2, satuan: 'kg', harga_satuan: 15000 }] } } } }) };
global.__DOWNLOAD = (...args) => downloads.push(args);

(async () => {
  await esbuild.build({ entryPoints: [path.join(root, 'src/documents/DocumentWorkspace.jsx')], outfile: output, bundle: true, platform: 'node', format: 'cjs', plugins: [{ name: 'isolated-fixtures', setup(build) {
    build.onResolve({ filter: /^react$/ }, () => ({ path: require.resolve('react'), external: true }));
    build.onResolve({ filter: /documentApi\.js$/ }, () => ({ path: 'api', namespace: 'fixture' }));
    build.onResolve({ filter: /lpdhApi\.js$/ }, () => ({ path: 'lpdh', namespace: 'fixture' }));
    build.onLoad({ filter: /.*/, namespace: 'fixture' }, args => ({ contents: args.path === 'api' ? 'export const documentApi=global.__DOCUMENT_API;' : 'export const lpdhApi=global.__LPDH_API; export const downloadBase64=global.__DOWNLOAD;', loader: 'js' }));
    build.onLoad({ filter: /\.css$/ }, () => ({ contents: '', loader: 'js' }));
  } }] });
  const Workspace = require(output).default;
  let view, finalized = 0;
  const render = site => React.createElement(Workspace, { site, serviceDate: '2026-10-05', onFinalized: () => finalized++ });
  await act(async () => { view = create(render('MAJA')); });
  const label = node => node.children.map(x => typeof x === 'string' ? x : label(x)).join('');
  const button = text => view.root.findAllByType('button').find(x => label(x).includes(text));
  const typeSelect = () => view.root.findAllByType('select').find(x => x.findAllByType('option').some(o => o.props.value === 'OPERASIONAL'));
  const changeType = async value => { confirm = true; await act(async () => typeSelect().props.onChange({ target: { value } })); };
  await changeType('OPERASIONAL');
  const addMaster = async value => {
    const select = view.root.findAllByType('select').find(x => x.findAllByType('option').some(o => o.props.value === value));
    await act(async () => select.props.onChange({ target: { value } }));
    await act(async () => button('Tambah item master').props.onClick());
  };
  await addMaster('gas'); await addMaster('sabun');
  await act(async () => button('Buat nomor & simpan draft').props.onClick());
  assert.equal(payloads[0].items.length, 2);
  assert.deepEqual(payloads[0].items.map(x => x.category_code), ['Gas', 'Alat kebersihan']);
  await addMaster('gas');
  await act(async () => button('Buat nomor & simpan draft').props.onClick());
  assert.equal(records.length, 2, 'multiple operational invoices for the same day');
  confirm = false;
  await act(async () => button('Finalkan').props.onClick());
  assert.equal(finalCalls.length, 0, 'canceled confirmation does not finalize');
  confirm = true;
  await act(async () => button('Finalkan').props.onClick());
  assert.deepEqual(finalCalls, [1]); assert.equal(finalized, 1);
  await act(async () => button('Unduh PDF').props.onClick());
  assert.deepEqual(downloads[0], ['DOC-1.pdf', 'application/pdf', 'JVBERi0=']);
  await changeType('UPAH_RELAWAN');
  await act(async () => button('Siapkan penerima dari master').props.onClick());
  assert.equal(view.root.findByProps({ 'aria-label': 'Jumlah' }).props.disabled, true);
  await act(async () => button('Buat nomor & simpan draft').props.onClick());
  assert.equal(payloads[2].items[0].quantity, 1); assert.equal(payloads[2].items[0].unit, 'hari'); assert.equal(payloads[2].items[0].unit_price, 90000);
  await changeType('INSENTIF_GURU_KADER');
  await act(async () => button('Siapkan penerima dari master').props.onClick());
  await act(async () => { for (const input of view.root.findAllByProps({ 'aria-label': 'Harga atau nominal' })) input.props.onChange({ target: { value: '10000' } }); });
  await act(async () => button('Buat nomor & simpan draft').props.onClick());
  assert.deepEqual(payloads[3].items.map(x => [x.quantity, x.unit, x.metadata.recipientType]), [[1, 'hari', 'Guru'], [1, 'hari', 'Kader']]);
  await changeType('BAHAN_BAKU');
  await act(async () => button('Tarik Final Kalkulator').props.onClick());
  await act(async () => button('Buat nomor & simpan draft').props.onClick());
  assert.equal(payloads[4].items[0].item_name, 'Beras');
  await act(async () => view.update(render('CEMPLANG')));
  assert.equal(view.root.findAllByType('tr').some(x => label(x).includes('DOC-1')), false, 'register must not leak across sites');
  await act(async () => view.unmount());
  console.log('PASS document UI: multi-item/master categories, multiple daily invoices, confirmation, real PDF download, one-day wages/incentives, final calculator import, site isolation');
})().catch(error => { console.error(error); process.exitCode = 1; });
