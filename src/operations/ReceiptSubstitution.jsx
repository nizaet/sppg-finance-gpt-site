import React, { useEffect, useRef, useState } from 'react';
import { operationsApi } from './apiClient';
import { parseReceiptQty } from './GoodsReceiptEditor';

export default function ReceiptSubstitution({ poId, site, item, onSaved, onCancel }) {
  const [masters, setMasters] = useState([]);
  const [form, setForm] = useState({ replacement_item_code: '', replaces_qty: String(item.remainingQty), received_qty: '', vendor_cost_price: '', reason: '', received_at_local: new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0,16) });
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const key = useRef(crypto.randomUUID());
  const pending = useRef(false);
  useEffect(() => { let live = true; operationsApi.getInventoryItems().then(x => { if (live) setMasters(x.items || []); }).catch(e => { if (live) setError(e.message); }); return () => { live = false; }; }, []);
  const change = (name, value) => { setPreview(null); key.current = crypto.randomUUID(); setForm(x => ({ ...x, [name]: value })); };
  const submit = async commit => {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError('');
    try {
      const body = preview?.normalizedPayload || { replacement_item_code: form.replacement_item_code, reason: form.reason, site, purchase_order_item_id: item.id, expected_fulfilled_qty: item.receivedQty, request_id: key.current, received_at: new Date(form.received_at_local).toISOString(), replaces_qty: parseReceiptQty(form.replaces_qty), received_qty: parseReceiptQty(form.received_qty), vendor_cost_price: parseReceiptQty(form.vendor_cost_price) };
      if (!form.vendor_cost_price.trim() || !form.replacement_item_code || !form.reason.trim()) throw new Error('Isi barang pengganti, harga aktual, dan alasan.');
      const result = await operationsApi.receiveSubstitution(poId, { ...body, commit });
      if (commit) { await onSaved(result); } else { setPreview(result); }
    } catch (e) { setError(e.message || 'Penggantian gagal diproses'); }
    finally { pending.current = false; setBusy(false); }
  };
  return <div className="ops-parse-result"><strong>Ganti barang: {item.item_name}</strong><p>Jumlah asli yang diganti menutup sisa PO. Jumlah datang masuk stok sebagai barang pengganti.</p>
    <label>Barang pengganti <select value={form.replacement_item_code} disabled={busy} onChange={e => change('replacement_item_code', e.target.value)}><option value="">Pilih master barang</option>{masters.filter(m => m.active !== false && m.base_unit).map(m => <option key={m.code} value={m.code}>{m.canonical_name} ({m.base_unit})</option>)}</select></label>
    {[['replaces_qty', `Jumlah ${item.item_name} yang diganti (${item.unit})`], ['received_qty', 'Jumlah pengganti datang (satuan master)'], ['vendor_cost_price', 'Harga aktual per satuan (Rp)']].map(([name, label]) => <label key={name}>{label} <input aria-label={label} inputMode="decimal" value={form[name]} disabled={busy} onChange={e => change(name, e.target.value)} /></label>)}
    <label>Waktu penerimaan <input type="datetime-local" value={form.received_at_local} disabled={busy} onChange={e => change('received_at_local', e.target.value)} /></label>
    <label>Alasan <input aria-label="Alasan penggantian" value={form.reason} disabled={busy} onChange={e => change('reason', e.target.value)} /></label>
    {error && <div className="ops-error">{error}</div>}
    {preview && <div className="ops-notice">{preview.originalItem} {Number(preview.replacesQty)} {preview.originalUnit} diganti {preview.replacementItem} {Number(preview.receivedQty)} {preview.unit}. Harga Rp{Number(preview.vendorCostPrice).toLocaleString('id-ID')}; nilai Rp{Number(preview.actualValue).toLocaleString('id-ID')}. Sisa barang asli: {Number(preview.remainingOriginalQty)} {preview.originalUnit}. Belum tersimpan. Tagihan dibuat terpisah dari penerimaan ini.</div>}
    <div className="ops-row-actions"><button disabled={busy} onClick={() => submit(Boolean(preview))}>{busy ? 'Memproses…' : preview ? 'Konfirmasi penggantian & penerimaan' : 'Periksa penggantian'}</button><button disabled={busy} onClick={onCancel}>Batal</button></div>
  </div>;
}
