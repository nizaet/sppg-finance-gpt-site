import React, { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { operationsApi } from "./apiClient";

export default function OperationsVendorMaster({ fixedSite = "" }) {
  const [site, setSite] = useState(fixedSite || "");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (fixedSite && site !== fixedSite) setSite(fixedSite);
  }, [fixedSite, site]);

  const activeSite = fixedSite || site;

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await operationsApi.getReferenceVendors(activeSite);
      setItems(data?.items || []);
    } catch (err) {
      setError(err.message || "Gagal mengambil master vendor");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [activeSite]);

  return (
    <section className="ops-module">
      <div className="ops-module-header">
        <div>
          <span className="ops-kicker">MASTER VERSIONED</span>
          <h3>Vendor & Lead Time</h3>
          <p>Rule aktif ditampilkan berdasarkan effective date. Histori transaksi tidak ditimpa.</p>
        </div>
        <div className="ops-inline-controls">
          <select value={activeSite} disabled={Boolean(fixedSite)} onChange={(e) => setSite(e.target.value)}><option value="">Semua site</option><option value="MAJA">Maja</option><option value="CEMPLANG">Cemplang</option></select>
          <button type="button" onClick={load} disabled={loading}><RefreshCw size={15} /> Refresh</button>
        </div>
      </div>
      {error && <div className="ops-error">{error}</div>}
      <div className="ops-table-wrap">
        <table className="ops-table">
          <thead><tr><th>Vendor</th><th>Site</th><th>Kategori</th><th>Lead Time</th><th>Payment Term</th><th>Via</th><th>Reimbursement</th></tr></thead>
          <tbody>
            {items.map((item, idx) => (
              <tr key={`${item.code}-${item.site_code}-${item.category_code}-${idx}`}>
                <td><strong>{item.name}</strong><div className="ops-muted">{item.code}</div></td>
                <td>{item.site_code || "Global / belum spesifik"}</td>
                <td>{item.category_code || (item.metadata?.categories || []).join(", ") || "-"}</td>
                <td>{item.lead_time_days_before_cooking == null ? "Belum dikunci" : `H-${item.lead_time_days_before_cooking}`}</td>
                <td>{item.payment_term_code || "Belum dikunci"}</td>
                <td>{item.intermediary_code || "-"}</td>
                <td>{item.internal_reimbursement ? "Ya" : "Tidak"}</td>
              </tr>
            ))}
            {!loading && items.length === 0 && <tr><td colSpan="7" className="ops-empty-cell">Belum ada vendor aktif.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}
