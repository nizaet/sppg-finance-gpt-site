import React, { useEffect, useRef, useState } from "react";
import { CheckCircle2, PackageCheck, RefreshCw, XCircle } from "lucide-react";
import { operationsApi } from "./apiClient";
import GoodsReceiptEditor, { parseReceiptQty } from "./GoodsReceiptEditor";

const RECEIVABLE = new Set(["FINALIZED", "SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED"]);
const fmtQty = (value) => Number(value || 0).toLocaleString("id-ID", { maximumFractionDigits: 4 });

export default function PoReceivingConfirm(props) {
  return <ReceivingPanel key={props.poId} {...props} />;
}

function ReceivingPanel({ poId, poCode = "PO", status = "", onChanged, inline = false }) {
  const [open, setOpen] = useState(Boolean(inline));
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [actualQty, setActualQty] = useState({});
  const [receipts, setReceipts] = useState(null);
  const [editing, setEditing] = useState(null);
  const actualRequest = useRef(null);

  const requestVersion = useRef(0);
  const savingRef = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; ++requestVersion.current; };
  }, []);

  const canReceive = RECEIVABLE.has(String(status || "").toUpperCase());

  const load = async () => {
    if (!poId || !canReceive || savingRef.current) return;
    const version = ++requestVersion.current;
    setLoading(true);
    setError("");
    try {
      const result = await operationsApi.getPoReceivingConfirmation(poId);
      if (mounted.current && version === requestVersion.current) { setData(result); setActualQty({}); }
    } catch (err) {
      if (mounted.current && version === requestVersion.current) setError(err.message || "Gagal mengambil status penerimaan PO");
    } finally {
      if (mounted.current && version === requestVersion.current) setLoading(false);
    }
  };

  useEffect(() => {
    if (open && canReceive) load();
  }, [open, poId, canReceive]);

  const showCorrections = async () => {
    if (savingRef.current || loading) return;
    setLoading(true); setError("");
    try {
      const result = await operationsApi.getGoodsReceipts({ poId, site: data?.site, limit: 500 });
      if (mounted.current) { setReceipts(result.items || []); setEditing(null); }
    } catch (err) { if (mounted.current) setError(err.message || "Gagal mengambil penerimaan"); }
    finally { if (mounted.current) setLoading(false); }
  };

  const confirmReceipt = async (mode, itemIds = []) => {
    if (savingRef.current || loading || !data) return;
    const selected = mode === "ALL"
      ? (data?.items || []).filter((item) => !item.complete)
      : (data?.items || []).filter((item) => itemIds.includes(Number(item.id)));
    if (!selected.length) return;
    const qty = mode === "ACTUAL" ? parseReceiptQty(actualQty[itemIds[0]]) : null;
    if (mode === "ACTUAL" && (!Number.isFinite(qty) || qty <= 0)) { setError("Isi jumlah datang lebih dari 0, maksimal 4 desimal."); return; }
    const label = mode === "ALL"
      ? `semua ${selected.length} item yang masih belum diterima`
      : selected.map((item) => item.item_name).join(", ");
    const question = mode === "ACTUAL"
      ? `Catat ${label} datang ${fmtQty(qty)} ${selected[0].unit || ""}?\nJumlah ini MENAMBAH penerimaan sebelumnya (${fmtQty(selected[0].receivedQty)}). Total menjadi ${fmtQty(Number(selected[0].receivedQty || 0) + qty)}.\n${qty > selected[0].remainingQty ? "Jumlah melebihi sisa PO. Periksa kelebihan kirim.\n" : ""}Jika ingin memperbaiki jumlah lama, pilih Ubah penerimaan.`
      : `Konfirmasi ${label} pada ${poCode} datang SESUAI PO?\n\nQty penerimaan akan diisi sebesar sisa PO dan langsung masuk stok gudang.`;
    if (!window.confirm(question)) return;

    savingRef.current = true;
    ++requestVersion.current;
    setSaving(mode === "ALL" ? "ALL" : String(itemIds[0] || "ITEM"));
    setError("");
    setMessage("");
    try {
      const signature = JSON.stringify({ mode, itemIds, qty, received: selected.map(item => item.receivedQty) });
      if (actualRequest.current?.signature !== signature) actualRequest.current = { signature, id: crypto.randomUUID() };
      const result = await operationsApi.confirmPoReceiving(poId, {
        mode,
        purchase_order_item_ids: itemIds,
        request_id: actualRequest.current.id,
        ...(mode === "ACTUAL" ? {
          items: [{ purchase_order_item_id: itemIds[0], received_qty: qty, expected_received_qty: selected[0].receivedQty }],
        } : {}),
        reporter: "operations-ui",
        note: mode === "ACTUAL" ? "Input jumlah aktual barang datang" : mode === "ALL" ? "Konfirmasi semua barang sesuai PO" : "Konfirmasi item barang sesuai PO",
      });
      actualRequest.current = null;
      if (mounted.current) { setMessage(result?.message || "Penerimaan tersimpan."); setActualQty({}); setReceipts(null); }
      window.dispatchEvent(new CustomEvent("sppg:goods-receipt-saved", {
        detail: { site: data?.site, purchaseOrderId: poId, receiptId: result?.receiptId || null },
      }));
      let refreshed;
      try {
        refreshed = await operationsApi.getPoReceivingConfirmation(poId);
        if (mounted.current) setData(refreshed);
        await onChanged?.(result, refreshed);
      } catch (err) {
        if (mounted.current) {
          setData(null);
          setError(`Penerimaan sudah tersimpan. Status belum diperbarui; tekan Refresh. ${err.message || ""}`);
        }
      }
    } catch (err) {
      if (mounted.current) setError(err.message || "Gagal menyimpan penerimaan PO");
    } finally {
      savingRef.current = false;
      if (mounted.current) setSaving("");
    }
  };

  if (!canReceive) return null;

  const trigger = (
    <button type="button" onClick={() => setOpen(true)}>
      <PackageCheck size={14} /> Penerimaan
    </button>
  );

  if (!open) return trigger;

  const panel = (
    <div className="ops-module" style={{ width: inline ? "100%" : "min(820px,96vw)", maxHeight: inline ? "none" : "88vh", overflow: "auto" }}>
      <div className="ops-draft-group-head">
        <div>
          <strong>Konfirmasi Penerimaan · {poCode}</strong>
          <span>Isi jumlah aktual yang datang, atau klik “Sesuai” untuk menerima sisa PO. Salah klik dapat diperbaiki melalui “Ubah penerimaan”.</span>
        </div>
        <div className="ops-row-actions">
          <button type="button" onClick={load} disabled={loading || Boolean(saving)}><RefreshCw size={14} /> Refresh</button>
          {!inline && <button type="button" onClick={() => setOpen(false)}><XCircle size={14} /> Tutup</button>}
        </div>
      </div>

      {error && <div className="ops-error">{error}</div>}
      {message && <div className="ops-success">{message}</div>}
      {loading && <div className="ops-muted">Mengambil status penerimaan…</div>}

      {data && <>
        <div className="ops-summary-strip">
          <span>Status PO <strong>{data.status}</strong></span>
          <span>Sudah diterima <strong>{data.completeCount}/{data.itemCount}</strong></span>
          <span>Sisa item <strong>{data.remainingCount}</strong></span>
        </div>

        {data.allReceived ? (
          <div className="ops-success"><CheckCircle2 size={15} /> Semua barang PO ini sudah tercatat diterima.</div>
        ) : (
          <div className="ops-row-actions" style={{ margin: "10px 0" }}>
            <button className="ops-button-success" type="button" onClick={() => confirmReceipt("ALL")} disabled={loading || Boolean(saving) || data.remainingCount <= 0}>
              <CheckCircle2 size={14} /> {saving === "ALL" ? "Menyimpan…" : "Semua sesuai"}
            </button>
          </div>
        )}

        <div className="ops-row-actions" style={{ margin: "10px 0" }}><button type="button" onClick={showCorrections} disabled={loading || Boolean(saving)}>Ubah penerimaan</button></div>
        {receipts && <div className="ops-parse-result"><strong>Pilih penerimaan yang akan dikoreksi</strong>{receipts.length === 0 && <p>Belum ada penerimaan tersimpan.</p>}{receipts.map(receipt => <div key={receipt.id}><button type="button" disabled={Boolean(editing)} onClick={() => setEditing(receipt)}>Receipt #{receipt.id} · {new Date(receipt.received_at).toLocaleString("id-ID")} · Ubah jumlah</button></div>)}</div>}
        {editing && <GoodsReceiptEditor key={editing.id} receipt={editing} onCancel={() => setEditing(null)} onSaved={async result => { setEditing(null); setReceipts(null); setMessage(result.message + (result.invoiceReviewRequired ? ` Periksa invoice #${result.linkedInvoiceIds.join(", #")}.` : "")); await load(); await onChanged?.(result); }} />}
        <div className="ops-table-wrap">
          <table className="ops-table">
            <thead><tr><th>Barang</th><th>Qty PO</th><th>Sudah diterima</th><th>Sisa</th><th>Status</th><th>Jumlah datang kali ini</th><th>Aksi</th></tr></thead>
            <tbody>
              {(data.items || []).map((item) => (
                <tr key={item.id}>
                  <td><strong>{item.item_name}</strong></td>
                  <td>{fmtQty(item.poQty)} {item.unit || ""}</td>
                  <td>{fmtQty(item.receivedQty)} {item.unit || ""}</td>
                  <td>{fmtQty(item.remainingQty)} {item.unit || ""}</td>
                  <td>{item.complete ? <span className="ops-stock-badge ops-stock-covered">✓ Diterima</span> : <span className="ops-muted">Belum lengkap</span>}</td>
                  <td><input aria-label={`Jumlah datang ${item.item_name}`} inputMode="decimal" value={actualQty[item.id] ?? ""} onChange={e => { actualRequest.current = null; setActualQty(prev => ({ ...prev, [item.id]: e.target.value })); }} disabled={loading || Boolean(saving)} placeholder="Isi aktual" style={{ width: 105 }} /><button type="button" onClick={() => confirmReceipt("ACTUAL", [Number(item.id)])} disabled={loading || Boolean(saving) || !(parseReceiptQty(actualQty[item.id]) > 0)}>Catat datang</button></td>
                  <td>{item.complete ? "✓" : <button className="ops-button-success" type="button" onClick={() => confirmReceipt("SELECTED", [Number(item.id)])} disabled={loading || Boolean(saving)}><CheckCircle2 size={13} /> {saving === String(item.id) ? "Menyimpan…" : "Sesuai"}</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </>}
    </div>
  );

  if (inline) return panel;

  return <>
    {trigger}
    <div style={{ position: "fixed", inset: 0, zIndex: 10020, background: "rgba(0,0,0,.55)", display: "flex", alignItems: "center", justifyContent: "center", padding: 18 }} onClick={() => setOpen(false)}>
      <div onClick={(event) => event.stopPropagation()}>{panel}</div>
    </div>
  </>;
}
