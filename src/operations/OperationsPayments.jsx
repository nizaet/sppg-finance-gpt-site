import React, { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { operationsApi } from "./apiClient";

const money = (v) => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(Number(v || 0));

export default function OperationsPayments() {
  const [site, setSite] = useState("");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await operationsApi.getVendorPayments({ site });
      setItems(data?.items || []);
    } catch (err) {
      setError(err.message || "Gagal mengambil pembayaran vendor");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [site]);

  return (
    <section className="ops-module">
      <div className="ops-module-header">
        <div>
          <span className="ops-kicker">PAYABLE / PAYMENT</span>
          <h3>Pembayaran Vendor</h3>
          <p>Invoice, potongan reject, netto payable, dan status pembayaran tetap terpisah.</p>
        </div>
        <div className="ops-inline-controls">
          <select value={site} onChange={(e) => setSite(e.target.value)}><option value="">Semua site</option><option value="MAJA">Maja</option><option value="CEMPLANG">Cemplang</option></select>
          <button type="button" onClick={load} disabled={loading}><RefreshCw size={15} /> Refresh</button>
        </div>
      </div>
      {error && <div className="ops-error">{error}</div>}
      <div className="ops-table-wrap">
        <table className="ops-table">
          <thead><tr><th>Vendor</th><th>Site</th><th>Invoice</th><th>Bruto</th><th>Reject</th><th>Netto</th><th>Dibayar</th><th>Status</th></tr></thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td><strong>{item.vendor_code}</strong></td><td>{item.site || "-"}</td><td>{item.invoice_number || "-"}</td>
                <td>{money(item.gross_amount)}</td><td>{money(item.reject_deduction)}</td><td>{money(item.net_amount || item.amount)}</td><td>{money(item.amount)}</td><td>{item.payment_status}</td>
              </tr>
            ))}
            {!loading && items.length === 0 && <tr><td colSpan="8" className="ops-empty-cell">Belum ada pembayaran vendor di PostgreSQL.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}
