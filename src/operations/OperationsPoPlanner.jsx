import React, { useEffect, useState } from "react";
import { CalendarDays, ClipboardCopy, MessageCircle, RefreshCw } from "lucide-react";
import { operationsApi } from "./apiClient";

const today = () => new Date().toISOString().slice(0, 10);
const money = (v) => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(Number(v || 0));
const qty = (v) => Number(v || 0).toLocaleString("id-ID", { maximumFractionDigits: 4 });

function poMessage(po) {
  const lines = [
    `*PO SPPG ${po.site || ""}*`,
    `Vendor: ${po.vendor_code || "-"}`,
    `Tanggal distribusi: ${po.distribution_date || "-"}`,
    `PO: ${po.po_code || "-"}${po.revision_no ? ` / Rev ${po.revision_no}` : ""}`,
    "",
  ];
  (po.items || []).forEach((item, index) => {
    lines.push(`${index + 1}. ${item.item_name} — ${qty(item.po_qty)} ${item.unit || ""}`.trim());
  });
  lines.push("", "Mohon konfirmasi pesanan di atas. Terima kasih.");
  return lines.join("\n");
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  document.body.removeChild(area);
}

export default function OperationsPoPlanner({ fixedSite = "" }) {
  const [distributionDate, setDistributionDate] = useState(today());
  const [cookingDate, setCookingDate] = useState(today());
  const [site, setSite] = useState(fixedSite || "MAJA");
  const [schedule, setSchedule] = useState([]);
  const [purchaseOrders, setPurchaseOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [actionId, setActionId] = useState(null);

  useEffect(() => {
    if (fixedSite && site !== fixedSite) setSite(fixedSite);
  }, [fixedSite, site]);

  const activeSite = fixedSite || site;

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const [scheduleData, poData] = await Promise.all([
        operationsApi.previewPoSchedule({ distributionDate, cookingDate, site: activeSite }),
        operationsApi.getPurchaseOrders({ site: activeSite, limit: 50 }),
      ]);
      setSchedule(scheduleData?.items || []);
      setPurchaseOrders(poData?.items || []);
    } catch (err) {
      setError(err.message || "Gagal mengambil jadwal/PO vendor");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [distributionDate, cookingDate, activeSite]);

  const loadPoText = async (poId) => {
    setActionId(poId);
    setError("");
    try {
      const detail = await operationsApi.getPurchaseOrder(poId);
      return poMessage(detail);
    } catch (err) {
      setError(err.message || "Gagal membuka detail PO");
      return "";
    } finally {
      setActionId(null);
    }
  };

  const copyPo = async (poId) => {
    const text = await loadPoText(poId);
    if (!text) return;
    await copyText(text);
    setMessage("Teks PO sudah disalin. Tinggal paste ke chat vendor.");
  };

  const openWhatsApp = async (poId) => {
    const text = await loadPoText(poId);
    if (!text) return;
    window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank", "noopener,noreferrer");
    setMessage("WhatsApp dibuka dengan teks PO siap diteruskan. Pilih chat vendor yang benar sebelum kirim.");
  };

  return (
    <div className="ops-domain-stack">
      <section className="ops-module">
        <div className="ops-module-header">
          <div>
            <span className="ops-kicker">JADWAL PO</span>
            <h3>Preview Waktu Pesan Vendor</h3>
            <p>Tanggal masak menjadi anchor lead time. Default masak sama dengan tanggal distribusi; ubah hanya bila siklus tertentu memang berbeda.</p>
          </div>
          <button type="button" onClick={load} disabled={loading}><RefreshCw size={15} /> Refresh</button>
        </div>

        <div className="ops-form-grid">
          <label>Site<select value={activeSite} disabled={Boolean(fixedSite)} onChange={(e) => setSite(e.target.value)}><option value="MAJA">Maja</option><option value="CEMPLANG">Cemplang</option></select></label>
          <label>Distribusi<input type="date" value={distributionDate} onChange={(e) => setDistributionDate(e.target.value)} /></label>
          <label>Masak<input type="date" value={cookingDate} onChange={(e) => setCookingDate(e.target.value)} /></label>
        </div>

        {error && <div className="ops-error">{error}</div>}
        {message && <div className="ops-success">{message}</div>}
        <div className="ops-table-wrap">
          <table className="ops-table">
            <thead><tr><th>Vendor</th><th>Kategori</th><th>Lead Time</th><th>Tanggal Pesan</th><th>Flow</th><th>Catatan</th></tr></thead>
            <tbody>
              {schedule.map((item, idx) => (
                <tr key={`${item.vendor_code}-${item.category_code}-${idx}`}>
                  <td><strong>{item.vendor_name}</strong><div className="ops-muted">{item.vendor_code}</div></td>
                  <td>{item.category_code || "-"}</td>
                  <td>{item.lead_time_days_before_cooking == null ? "Belum dikunci" : `H-${item.lead_time_days_before_cooking}`}</td>
                  <td>{item.po_date || "Perlu review"}</td>
                  <td>{item.internal_reimbursement ? "Reimbursement internal" : "Vendor / stok"}{item.intermediary_code ? ` via ${item.intermediary_code}` : ""}</td>
                  <td>{item.notes || "-"}</td>
                </tr>
              ))}
              {!loading && schedule.length === 0 && <tr><td colSpan="6" className="ops-empty-cell"><CalendarDays size={18} /> Belum ada rule aktif.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="ops-module">
        <div className="ops-module-header">
          <div>
            <span className="ops-kicker">PO TERCATAT</span>
            <h3>Purchase Order Aktual</h3>
            <p>Qty PO tetap terpisah dari planning, receiving, invoice, dan actual usage. Copy/WhatsApp hanya menyiapkan teks; sistem tidak menganggap PO sudah terkirim sebelum ada status/evidence.</p>
          </div>
        </div>
        <div className="ops-table-wrap">
          <table className="ops-table">
            <thead><tr><th>Distribusi</th><th>PO</th><th>Vendor</th><th>Revisi</th><th>Item</th><th>Total PO</th><th>Status</th><th>Aksi Manual</th></tr></thead>
            <tbody>
              {purchaseOrders.map((po) => (
                <tr key={po.id}>
                  <td>{po.distribution_date || "-"}</td>
                  <td><strong>{po.po_code}</strong><div className="ops-muted">{po.sent_at ? `Sent: ${po.sent_at}` : "Belum ada bukti kirim"}</div></td>
                  <td>{po.vendor_code}</td>
                  <td>{po.revision_no}</td>
                  <td>{po.item_count}</td>
                  <td>{money(po.po_total)}</td>
                  <td>{po.status}</td>
                  <td>
                    <div className="ops-row-actions">
                      <button type="button" onClick={() => copyPo(po.id)} disabled={actionId === po.id}><ClipboardCopy size={14} /> Copy PO</button>
                      <button type="button" onClick={() => openWhatsApp(po.id)} disabled={actionId === po.id}><MessageCircle size={14} /> WhatsApp</button>
                    </div>
                  </td>
                </tr>
              ))}
              {!loading && purchaseOrders.length === 0 && <tr><td colSpan="8" className="ops-empty-cell">Belum ada PO tercatat untuk site ini.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
