import React, { useEffect, useRef, useState } from "react";
import { CheckCircle2, PackageCheck, RefreshCw, XCircle } from "lucide-react";
import { operationsApi } from "./apiClient";

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
      if (mounted.current && version === requestVersion.current) setData(result);
    } catch (err) {
      if (mounted.current && version === requestVersion.current) setError(err.message || "Gagal mengambil status penerimaan PO");
    } finally {
      if (mounted.current && version === requestVersion.current) setLoading(false);
    }
  };

  useEffect(() => {
    if (open && canReceive) load();
  }, [open, poId, canReceive]);

  const confirmReceipt = async (mode, itemIds = []) => {
    if (savingRef.current || loading || !data) return;
    const selected = mode === "ALL"
      ? (data?.items || []).filter((item) => !item.complete)
      : (data?.items || []).filter((item) => itemIds.includes(Number(item.id)));
    if (!selected.length) return;
    const label = mode === "ALL"
      ? `semua ${selected.length} item yang masih belum diterima`
      : selected.map((item) => item.item_name).join(", ");
    if (!window.confirm(`Konfirmasi ${label} pada ${poCode} datang SESUAI PO?\n\nQty penerimaan akan diisi sebesar sisa PO dan langsung masuk stok gudang.`)) return;

    savingRef.current = true;
    ++requestVersion.current;
    setSaving(mode === "ALL" ? "ALL" : String(itemIds[0] || "ITEM"));
    setError("");
    setMessage("");
    try {
      const result = await operationsApi.confirmPoReceiving(poId, {
        mode,
        purchase_order_item_ids: itemIds,
        reporter: "operations-ui",
        note: mode === "ALL" ? "Konfirmasi semua barang sesuai PO" : "Konfirmasi item barang sesuai PO",
      });
      if (mounted.current) setMessage(result?.message || "Penerimaan tersimpan.");
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
          <span>Klik “Sesuai” per barang, atau “Semua sesuai” untuk menerima seluruh sisa item PO sekaligus.</span>
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

        <div className="ops-table-wrap">
          <table className="ops-table">
            <thead><tr><th>Barang</th><th>Qty PO</th><th>Sudah diterima</th><th>Sisa</th><th>Status</th><th>Aksi</th></tr></thead>
            <tbody>
              {(data.items || []).map((item) => (
                <tr key={item.id}>
                  <td><strong>{item.item_name}</strong></td>
                  <td>{fmtQty(item.poQty)} {item.unit || ""}</td>
                  <td>{fmtQty(item.receivedQty)} {item.unit || ""}</td>
                  <td>{fmtQty(item.remainingQty)} {item.unit || ""}</td>
                  <td>{item.complete ? <span className="ops-stock-badge ops-stock-covered">✓ Diterima</span> : <span className="ops-muted">Belum lengkap</span>}</td>
                  <td>{item.complete ? "-" : <button className="ops-button-success" type="button" onClick={() => confirmReceipt("SELECTED", [Number(item.id)])} disabled={loading || Boolean(saving)}><CheckCircle2 size={13} /> {saving === String(item.id) ? "Menyimpan…" : "Sesuai"}</button>}</td>
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
