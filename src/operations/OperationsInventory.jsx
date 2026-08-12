import React, { useEffect, useMemo, useState } from "react";
import { RefreshCw, Search } from "lucide-react";
import { operationsApi } from "./apiClient";

const qty = (value) => Number(value || 0).toLocaleString("id-ID", { maximumFractionDigits: 4 });

export default function OperationsInventory() {
  const [site, setSite] = useState("MAJA");
  const [search, setSearch] = useState("");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await operationsApi.getInventoryBalances({ site, search });
      setItems(data?.items || []);
    } catch (err) {
      setError(err.message || "Gagal mengambil saldo gudang");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [site]);

  const negativeCount = useMemo(() => items.filter((x) => Number(x.balance || 0) < 0).length, [items]);

  return (
    <section className="ops-module">
      <div className="ops-module-header">
        <div>
          <span className="ops-kicker">INVENTORY LEDGER</span>
          <h3>Gudang</h3>
          <p>Saldo dihitung dari movement masuk/keluar. Transfer internal Koperasi tetap movement stok, bukan transaksi biaya baru.</p>
        </div>
        <div className="ops-inline-controls">
          <select value={site} onChange={(e) => setSite(e.target.value)}><option value="MAJA">Maja</option><option value="CEMPLANG">Cemplang</option></select>
          <input value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load()} placeholder="Cari barang" />
          <button type="button" onClick={load} disabled={loading}><Search size={15} /> Cari</button>
          <button type="button" onClick={() => { setSearch(""); setTimeout(load, 0); }} disabled={loading}><RefreshCw size={15} /> Refresh</button>
        </div>
      </div>
      {error && <div className="ops-error">{error}</div>}
      <div className="ops-summary-strip">
        <span>Item <strong>{items.length}</strong></span>
        <span>Saldo negatif <strong>{negativeCount}</strong></span>
      </div>
      <div className="ops-table-wrap">
        <table className="ops-table">
          <thead><tr><th>Barang</th><th>Saldo</th><th>Unit</th><th>Pergerakan Terakhir</th><th>Status</th></tr></thead>
          <tbody>
            {items.map((item, idx) => {
              const balance = Number(item.balance || 0);
              return (
                <tr key={`${item.item_name}-${item.unit}-${idx}`}>
                  <td><strong>{item.item_name}</strong></td>
                  <td>{qty(balance)}</td>
                  <td>{item.unit || "-"}</td>
                  <td>{item.last_movement_at || "-"}</td>
                  <td>{balance < 0 ? "⚠ Saldo negatif" : balance === 0 ? "Kosong" : "Tersedia"}</td>
                </tr>
              );
            })}
            {!loading && items.length === 0 && <tr><td colSpan="5" className="ops-empty-cell">Belum ada movement stok untuk site/filter ini.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}
