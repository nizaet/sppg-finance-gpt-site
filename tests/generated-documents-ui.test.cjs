const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const React = require('react');
const { create, act } = require('react-test-renderer');
const esbuild = require('esbuild');
const root = path.resolve(__dirname, '..');
const output = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'sppg-documents-')), 'test.cjs');
const records = [], payloads = [], finalCalls = [], downloads = [], previews = [], cancellations = [], calendarCalls = [];
let confirm = false;
let replacement = null;
const finalOptions = [], confirmations = [];
global.window = { addEventListener() {}, removeEventListener() {}, confirm: message => { confirmations.push(message); return confirm; }, prompt: () => 'Harga keliru', open: () => { const tab = { opener: {}, location: { replace: url => previews.push(url) }, close() {} }; return tab; } };
global.__DOCUMENT_API = {
  suggestNumber: async (site, date, type) => ({ documentNumber: `001/${type}/${site}/X/2026` }),
  master: async site => ({ profiles: { KOPERASI: { issuerName: site, recipientAddress: 'Alamat' }, YAYASAN: { issuerName: 'Yayasan', recipientAddress: 'Alamat' } }, categories: ['Gas', 'Alat kebersihan', 'Lain-lain'],
    items: [{ recordKey: 'gas', itemName: 'Gas LPG', kind: 'OPERASIONAL', category: 'Gas', unit: 'tabung', unitPrice: 1000 }, { recordKey: 'sabun', itemName: 'Sabun', kind: 'OPERASIONAL', category: 'Alat kebersihan', unit: 'botol', unitPrice: 200 }],
    volunteers: [{ code: 'R1', name: 'Relawan Uji', role: 'Pengolah', dailyRate: 90000 }], recipients: [{ name: 'Guru Uji', recipientType: 'Guru', unitName: 'SD Uji' }, { name: 'Kader Uji', recipientType: 'Kader', unitName: 'Posyandu Uji' }] }),
  list: async site => ({ documents: structuredClone(records.filter(doc => doc.site === site)) }),
  get: async id => ({ document: structuredClone(records.find(doc => doc.id === id)) }),
  finalizationCheck: async id => ({ status: records.find(doc => doc.id === id).status, dailyStatus: 'DRAFT', legacyReplacement: replacement }),
  saveProfile: async (site, header) => ({ profile: header.documentProfileKey, header }),
  asset: async id => ({ id, filename: 'gambar-uji.png', mimeType: 'image/png', contentBase64: 'iVBORw0KGgo=' }),
  uploadAsset: async payload => ({ id: 17, filename: payload.filename }),
  calendar: async (site, month) => { calendarCalls.push([site, month]); return { items: [{ serviceDate: '2026-10-05', draft: 2, final: 1, cancelled: 1 }] }; },
  create: async payload => { payloads.push(payload); const document = { id: records.length + 1, site: payload.site, serviceDate: payload.service_date, documentType: payload.document_type, documentNumber: payload.document_number, status: 'DRAFT', header: payload.header_payload, items: payload.items.map(x => ({ itemName: x.item_name, category: x.category_code, quantity: x.quantity, unit: x.unit, unitPrice: x.unit_price, metadata: x.metadata })), total: payload.items.reduce((sum, x) => sum + x.quantity * x.unit_price, 0) }; records.push(document); return { document }; },
  finalize: async (id, options) => { finalCalls.push(id); finalOptions.push(options); records.find(doc => doc.id === id).status = 'FINAL'; return { syncedToDaily: true, driveUploadStatus: 'UPLOADED' }; },
  cancel: async (id, reason) => { cancellations.push([id, reason]); Object.assign(records.find(doc => doc.id === id), { status: 'CANCELLED', cancellationReason: reason }); return { status: 'CANCELLED' }; },
  archive: async () => ({ driveUploadStatus: 'UPLOADED' }),
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
  const typeSelect = () => view.root.findByProps({'aria-label':'Jenis dokumen'});
  const changeType = async value => { confirm = true; await act(async () => typeSelect().props.onChange({ target: { value } })); };
  const saveDraft = async () => {
    const input = view.root.findAllByType('label').find(x => /Nomor invoice|Nomor paket kuitansi/.test(label(x))).findByType('input');
    await act(async () => input.props.onChange({ target: { value: `DOC-${payloads.length + 1}` } }));
    await act(async () => { view.root.findAllByType('input').filter(x => String(x.props['aria-label'] || '').startsWith('Nomor kuitansi baris')).forEach((x, index) => x.props.onChange({ target: { value: `KWT-${payloads.length + 1}-${index + 1}` } })); });
    await act(async () => button('Simpan draft').props.onClick());
  };
  await changeType('OPERASIONAL');
  const addMaster = async value => {
    const select = view.root.findAllByType('select').find(x => x.findAllByType('option').some(o => o.props.value === value));
    await act(async () => select.props.onChange({ target: { value } }));
    await act(async () => button('Tambah item master').props.onClick());
  };
  await addMaster('gas'); await addMaster('sabun');
  const numberInput = () => view.root.findAllByType('label').find(x => /Nomor invoice|Nomor paket kuitansi/.test(label(x))).findByType('input');
  assert.equal(numberInput().props.value, '001/OPERASIONAL/MAJA/X/2026', 'invoice gets editable numeric-prefix suggestion');
  await act(async () => numberInput().props.onChange({ target: { value: '' } }));
  await act(async () => button('Simpan draft').props.onClick());
  assert.equal(payloads.length, 0, 'a manually cleared number still blocks saving');
  await saveDraft();
  assert.equal(payloads[0].document_number, 'DOC-1');
  assert.equal(payloads[0].items.length, 2);
  assert.deepEqual(payloads[0].items.map(x => x.category_code), ['Gas', 'Alat kebersihan']);
  await addMaster('gas');
  await saveDraft();
  assert.equal(records.length, 2, 'multiple operational invoices for the same day');
  assert.equal(button('Unduh PDF'), undefined, 'draft has no automatic download action');
  const originalTimeout = global.setTimeout;
  global.setTimeout = callback => { callback(); return 0; };
  try { await act(async () => button('Buka PDF Draft').props.onClick()); } finally { global.setTimeout = originalTimeout; }
  assert.equal(previews.length, 1); assert.ok(previews[0].startsWith('blob:'));
  assert.equal(downloads.length, 0, 'draft preview does not trigger download');
  assert.deepEqual(calendarCalls[0], ['MAJA', '2026-10']);
  confirm = false;
  await act(async () => button('Finalkan').props.onClick());
  assert.equal(finalCalls.length, 0, 'canceled confirmation does not finalize');
  confirm = true;
  await act(async () => button('Finalkan').props.onClick());
  assert.deepEqual(finalCalls, [1]); assert.equal(finalized, 1);
  await act(async () => button('Unduh PDF').props.onClick());
  assert.deepEqual(downloads[0], ['DOC-1.pdf', 'application/pdf', 'JVBERi0=']);
  confirm = false;
  await act(async () => button('Batalkan').props.onClick());
  assert.equal(cancellations.length, 0, 'cancel requires confirmation');
  confirm = true;
  await act(async () => button('Batalkan').props.onClick());
  assert.deepEqual(cancellations[0], [1, 'Harga keliru']);
  assert.equal(view.root.findAllByType('tr').some(x => label(x).includes('DOC-1')), false, 'cancelled hidden from active register');
  await act(async () => view.root.findByProps({ type: 'checkbox' }).props.onChange({ target: { checked: true } }));
  assert.equal(view.root.findAllByType('tr').some(x => label(x).includes('DOC-1') && label(x).includes('DIBATALKAN')), true, 'cancelled evidence remains inspectable');
  await changeType('UPAH_RELAWAN');
  await act(async () => button('Siapkan penerima dari master').props.onClick());
  assert.equal(view.root.findByProps({ 'aria-label': 'Jumlah' }).props.disabled, true);
  await saveDraft();
  assert.equal(payloads[2].items[0].quantity, 1); assert.equal(payloads[2].items[0].unit, 'hari'); assert.equal(payloads[2].items[0].unit_price, 90000);
  replacement = {snapshotHash:'a'.repeat(64),legacyCount:2,legacyTotal:100000,newCount:1,newTotal:90000,removedCount:1,addedCount:0};
  const wageButton = () => view.root.findAllByType('tr').find(x=>label(x).includes('DOC-3')).findAllByType('button').find(x=>label(x).includes('Finalkan'));
  confirm = false;
  await act(async()=>wageButton().props.onClick());
  assert.deepEqual(finalCalls,[1]);
  confirm = true;
  await act(async()=>wageButton().props.onClick());
  assert.deepEqual(finalCalls,[1,3]);
  assert.equal(finalOptions[1].replace_legacy_snapshot,replacement.snapshotHash);
  assert.ok(confirmations.some(message=>message.includes('GANTIKAN seluruh isian lama')&&message.includes('Isian lama disimpan sebagai riwayat')));
  replacement = null;
  await changeType('INSENTIF_GURU_KADER');
  await act(async () => button('Siapkan penerima dari master').props.onClick());
  await act(async () => { for (const input of view.root.findAllByProps({ 'aria-label': 'Harga atau nominal' })) input.props.onChange({ target: { value: '10000' } }); });
  await saveDraft();
  assert.deepEqual(payloads[3].items.map(x => [x.quantity, x.unit, x.metadata.recipientType]), [[1, 'hari', 'Guru']]);
  assert.equal(payloads[3].header_payload.paymentSnapshotVersion, 2);
  assert.equal(payloads[3].header_payload.recipientSubtype, 'Guru');
  assert.equal(view.root.findAllByType('input').some(x => String(x.props['aria-label'] || '').startsWith('Nomor kuitansi baris')), false);
  await act(async () => view.root.findByProps({ 'aria-label': 'Jenis paket insentif' }).props.onChange({ target: { value: 'Kader' } }));
  await act(async () => button('Siapkan penerima dari master').props.onClick());
  assert.equal(view.root.findByProps({ 'aria-label': 'Nama baris 1' }).props.value, 'Kader Uji', 'cadre package isolates master recipients');
  await changeType('BAHAN_BAKU');
  await act(async () => button('Tarik Final Kalkulator').props.onClick());
  await saveDraft();
  assert.equal(payloads[4].items[0].item_name, 'Beras');
  const staleFinalButton = button('Finalkan');
  records[1].status = 'CANCELLED'; records[1].cancellationReason = 'Batal dari tab lain';
  await act(async () => staleFinalButton.props.onClick());
  assert.deepEqual(finalCalls, [1,3], 'stale tab must not finalize a cancelled ID');
  assert.ok(view.root.findAllByProps({ role:'status' }).some(x => label(x).includes('sebelumnya sudah DIBATALKAN')));
  await act(async () => button('Buat ulang').props.onClick());
  const manualInput = numberInput();
  assert.notEqual(manualInput.props.value, 'DOC-1', 'replacement never reuses cancelled number');
  assert.match(manualInput.props.value, /^001\//, 'replacement receives a fresh suggestion');
  assert.equal(view.root.findAllByProps({ 'aria-label':'Nama baris 1' })[0].props.value, 'Gas LPG');
  await saveDraft();
  assert.equal(payloads[5].document_number, 'DOC-6');
  global.FileReader = class { readAsDataURL() { this.result = 'data:image/png;base64,iVBORw0KGgo='; this.onload(); } };
  await act(async () => view.root.findByProps({ 'aria-label':'Unggah Tanda tangan penerbit' }).props.onChange({ target:{ files:[{name:'ttd-uji.png',size:100}],value:'' } }));
  await act(async () => button('Simpan data kop sebagai default').props.onClick());
  assert.equal(view.root.findAllByType('img').some(x => x.props.alt === 'Tanda tangan penerbit'), true);
  await changeType('OPERASIONAL');
  assert.equal(view.root.findAllByType('img').some(x => x.props.alt === 'Tanda tangan penerbit'), true, 'saved defaults survive type change');
  await act(async () => view.update(render('CEMPLANG')));
  assert.equal(view.root.findAllByType('tr').some(x => label(x).includes('DOC-1')), false, 'register must not leak across sites');
  let resolveNumber;
  global.__DOCUMENT_API.suggestNumber = () => new Promise(resolve => { resolveNumber = resolve; });
  await changeType('OPERASIONAL');
  await act(async () => numberInput().props.onChange({ target: { value: '099/OP/MANUAL/X/2026' } }));
  await act(async () => resolveNumber({ documentNumber:'002/OP/AUTO/X/2026' }));
  assert.equal(numberInput().props.value, '099/OP/MANUAL/X/2026', 'late suggestion must not overwrite manual edit');
  await act(async () => view.unmount());
  console.log('PASS document UI: multi-item/master categories, multiple daily invoices, confirmation, real PDF download, one-day wages/incentives, final calculator import, site isolation');
})().catch(error => { console.error(error); process.exitCode = 1; });
