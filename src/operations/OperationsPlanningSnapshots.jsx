import React, { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { operationsApi } from "./apiClient";

export default function OperationsPlanningSnapshots() {
  const [site, setSite] = useState("");
  const [items, setItems] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const load = async () => {
    setLoading(true); setError("");
    try { const data = await operationsApi.getPlanningSnapshots({ site }); setItems(data?.items || []); }
    catch (e) { setError(e.message || "Gagal mengambil planning snapshots"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [site]);
  return <section className="ops-module">
    <div className="ops-module-header"><div><span className="ops-kicker">KALKULATOR → CORE</span><h3>Planning Snapshots</h3><p>Snapshot terbaru aktif; versi lama tetap tersimpan sebagai superseded.</p></div><div className="ops-inline-controls"><select value={site} onChange={e=>setSite(e.target.value)}><option value="">Semua site</option><option value="MAJA">Maja</option><option value="CEMPLANG">Cemplang</option></select><button onClick={load} disabled={loading}><RefreshCw size={15}/> Refresh</button></div></div>
    {error && <div className="ops-error">{error}</div>}
    <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Site</th><th>Distribusi</th><th>Masak</th><th>Sumber</th><th>Versi</th><th>Item</th><th>Status</th></tr></thead><tbody>{items.map(x=><tr key={x.id}><td>{x.site}</td><td>{x.distribution_date}</td><td>{x.cooking_at || "-"}</td><td>{x.source_system}</td><td>{x.source_version || "-"}</td><td>{x.item_count}</td><td>{x.status}</td></tr>)}{!loading && items.length===0&&<tr><td colSpan="7" className="ops-empty-cell">Belum ada planning snapshot dari kalkulator.</td></tr>}</tbody></table></div>
  </section>;
}
