import React, { useEffect, useState } from "react";
import { CalendarDays, RefreshCw } from "lucide-react";
import { operationsApi } from "./apiClient";

const today = () => new Date().toISOString().slice(0, 10);
const money = (v) => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(Number(v || 0));

export default function OperationsPoPlanner() {
  const [distributionDate, setDistributionDate] = useState(today());
  const [cookingDate, setCookingDate] = useState(today());
  const [site, setSite] = useState("MAJA");
  const [schedule, setSchedule] = useState([]);
  const [purchaseOrders, setPurchaseOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const [scheduleData, poData] = await Promise.all([
        operationsApi.previewPoSchedule({ distributionDate, cookingDate, site }),
        operationsApi.getPurchaseOrders({ site, limit: 50 }),
      ]);
      setSchedule(scheduleData?.items || []);
      setPurchaseOrders(poData?.items || []);
    } catch (err) {
      setError(err.message || "Gagal mengambil jadwal/PO vendor");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [distributionDate, cookingDate, site]);

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
          <label>Site<select value={site} onChange={(e) => setSite(e.target.value)}><option value="MAJA">Maja</option><option value="CEMPLANG">Cemplang</option></select></label>
          <label>Distribusi<input type="date" value={distributionDate} onChange={(e) => setDistributionDate(e.target.value)} /></label>
          <label>Masak<input type="date" value={cookingDate} onChange={(e) => setCookingDate(e.target.value)} /></label>
        </div>

        {error && <div className="ops-error">{error}</div>}
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
            <p>Ini record PO yang sudah ada. Qty PO tetap layer terpisah dari planning, receiving, invoice, dan actual usage.</p>
          </div>
        </div>
        <div className="ops-table-wrap">
          <table className="ops-table">
            <thead><tr><th>Distribusi</th><th>PO</th><th>Vendor</th><th>Revisi</th><th>Item</th><th>Total PO</th><th>Status</th><th>Dikirim</th></tr></thead>
            <tbody>
              {purchaseOrders.map((po) => (
                <tr key={po.id}>
                  <td>{po.distribution_date || "-"}</td>
                  <td><strong>{po.po_code}</strong></td>
                  <td>{po.vendor_code}</td>
                  <td>{po.revision_no}</td>
                  <td>{po.item_count}</td>
                  <td>{money(po.po_total)}</td>
                  <td>{po.status}</td>
                  <td>{po.sent_at || "-"}</td>
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
