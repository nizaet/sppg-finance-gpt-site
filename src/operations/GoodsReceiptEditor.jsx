import React, { useRef, useState } from "react";
import { operationsApi } from "./apiClient";

export function parseReceiptQty(value) {
  const raw = String(value ?? "").trim();
  if (!/^\d+(?:[.,]\d{1,4})?$/.test(raw)) return NaN;
  return Number(raw.replace(",", "."));
}
const fmt = value => Number(value || 0).toLocaleString("id-ID", { maximumFractionDigits: 4 });

export default function GoodsReceiptEditor({ receipt, onSaved, onCancel }) {
  const [lines, setLines] = useState(() => (receipt.items || []).map(item => ({ ...item, received: String(item.received_qty ?? 0), rejected: String(item.rejected_qty ?? 0) })));
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const busy = useRef(false);
  const requestId = useRef(crypto.randomUUID());
  const change = (id, field, value) => { requestId.current = crypto.randomUUID(); setLines(current => current.map(line => line.receipt_item_id === id ? { ...line, [field]: value } : line)); };
  const changed = lines.filter(line => parseReceiptQty(line.received) !== Number(line.received_qty) || parseReceiptQty(line.rejected) !== Number(line.rejected_qty || 0));
  const valid = lines.every(line => Number.isFinite(parseReceiptQty(line.received)) && Number.isFinite(parseReceiptQty(line.rejected)) && parseReceiptQty(line.rejected) <= parseReceiptQty(line.received));
  const save = async () => {
    if (busy.current || !valid || !changed.length || reason.trim().length < 3) return;
    const summary = changed.map(line => `${line.replacement_item_name || line.po_item_name || line.reported_item_name}: datang ${fmt(line.received_qty)} → ${fmt(parseReceiptQty(line.received))}; reject ${fmt(line.rejected_qty)} → ${fmt(parseReceiptQty(line.rejected))} ${line.unit || ""}`).join("\n");
    if (!window.confirm(`Simpan koreksi Receipt #${receipt.id}?\n${summary}\n\nStok disesuaikan sebesar selisih pada tanggal penerimaan asli. SO yang lebih baru tetap menjadi acuan. Invoice dan pembayaran tidak ikut berubah; periksa ulang jika sudah ada tagihan.\n\nAlasan: ${reason.trim()}`)) return;
    busy.current = true; setSaving(true); setError("");
    try {
      const result = await operationsApi.correctGoodsReceipt(receipt.id, {
        site: receipt.site, request_id: requestId.current, reason: reason.trim(),
        items: changed.map(line => ({ receipt_item_id: line.receipt_item_id, received_qty: parseReceiptQty(line.received), rejected_qty: parseReceiptQty(line.rejected), expected_received_qty: Number(line.received_qty), expected_rejected_qty: Number(line.rejected_qty || 0), expected_updated_at: line.updated_at || null })),
      });
      await onSaved?.(result);
      window.dispatchEvent(new CustomEvent("sppg:goods-receipt-saved", { detail: { site: receipt.site, purchaseOrderId: receipt.purchase_order_id, receiptId: receipt.id } }));
    } catch (err) { setError(err.message || "Koreksi gagal disimpan"); }
    finally { busy.current = false; setSaving(false); }
  };
  return <div className="ops-parse-result">
    <strong>Ubah penerimaan · Receipt #{receipt.id} · {receipt.vendor_code}</strong>
    <p>Isi jumlah datang dan reject yang benar untuk penerimaan ini. Gunakan 0 jika sebelumnya terlanjur ditandai datang. Jumlah PO tetap.</p>
    <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Barang</th><th>Sebelumnya</th><th>Jumlah datang</th><th>Reject</th><th>Diterima bersih</th></tr></thead><tbody>{lines.map(line => <tr key={line.receipt_item_id}>
      <td>{line.replacement_item_name || line.po_item_name || line.reported_item_name} ({line.unit})</td><td>{fmt(line.received_qty)} · reject {fmt(line.rejected_qty)}</td>
      <td><input aria-label={`Jumlah datang ${line.replacement_item_name || line.po_item_name || line.reported_item_name}`} inputMode="decimal" value={line.received} disabled={saving} onChange={e => change(line.receipt_item_id, "received", e.target.value)} style={{ width: 110 }} /></td>
      <td><input aria-label={`Reject ${line.replacement_item_name || line.po_item_name || line.reported_item_name}`} inputMode="decimal" value={line.rejected} disabled={saving} onChange={e => change(line.receipt_item_id, "rejected", e.target.value)} style={{ width: 100 }} /></td>
      <td>{Number.isFinite(parseReceiptQty(line.received)) && Number.isFinite(parseReceiptQty(line.rejected)) ? fmt(parseReceiptQty(line.received) - parseReceiptQty(line.rejected)) : "—"}</td>
    </tr>)}</tbody></table></div>
    <label>Alasan koreksi<input value={reason} onChange={e => { requestId.current = crypto.randomUUID(); setReason(e.target.value); }} disabled={saving} placeholder="Contoh: terlanjur klik sesuai, aktual hanya 8 kg" maxLength={1000} /></label>
    {!valid && <div className="ops-error">Isi jumlah 0 atau lebih, maksimal 4 desimal. Reject tidak boleh melebihi jumlah datang.</div>}
    {error && <div className="ops-error">{error}</div>}
    <div className="ops-row-actions"><button type="button" onClick={save} disabled={saving || !valid || !changed.length || reason.trim().length < 3}>{saving ? "Menyimpan…" : "Simpan koreksi"}</button><button type="button" onClick={onCancel} disabled={saving}>Batal</button></div>
  </div>;
}
