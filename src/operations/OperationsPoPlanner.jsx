import React, { useEffect, useState } from "react";
import { CalendarDays, RefreshCw } from "lucide-react";
import { operationsApi } from "./apiClient";

const today = () => new Date().toISOString().slice(0, 10);
const addDays = (dateStr, days) => {
  const d = new Date(`${dateStr}T00:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
};

export default function OperationsPoPlanner() {
  const [distributionDate, setDistributionDate] = useState(today());
  const [cookingDate, setCookingDate] = useState(addDays(today(), -1));
  const [site, setSite] = useState("MAJA");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await operationsApi.previewPoSchedule({ distributionDate, cookingDate, site });
      setItems(data?.items || []);
    } catch (err) {
      setError(err.message || "Gagal menghitung jadwal PO");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [distributionDate, cookingDate, site]);

  return (
    <section className="ops-module">
      <div className="ops-module-header">
        <div>
          <span className="ops-kicker">PO BERBASIS WAKTU MASAK</span>
          <h3>Kalender / Preview PO</h3>
          <p>Tanggal masak adalah anchor. Lead time vendor dihitung mundur dari tanggal masak.</p>
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
          <thead><tr><th>Vendor</th><th>Kategori</th><th>Lead Time</th><th>Tanggal PO</th><th>Flow</th><th>Catatan</th></tr></thead>
          <tbody>
            {items.map((item, idx) => (
              <tr key={`${item.vendor_code}-${item.category_code}-${idx}`}>
                <td><strong>{item.vendor_name}</strong><div className="ops-muted">{item.vendor_code}</div></td>
                <td>{item.category_code || "-"}</td>
                <td>{item.lead_time_days_before_cooking == null ? "Belum dikunci" : `H-${item.lead_time_days_before_cooking}`}</td>
                <td>{item.po_date || "Perlu review"}</td>
                <td>{item.internal_reimbursement ? "Reimbursement internal" : "Vendor / stok"}{item.intermediary_code ? ` via ${item.intermediary_code}` : ""}</td>
                <td>{item.notes || "-"}</td>
              </tr>
            ))}
            {!loading && items.length === 0 && <tr><td colSpan="6" className="ops-empty-cell"><CalendarDays size={18} /> Belum ada rule aktif.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}
