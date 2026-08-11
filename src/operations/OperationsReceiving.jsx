import React, { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { operationsApi } from "./apiClient";

export default function OperationsReceiving(){
  const [site,setSite]=useState(""); const [items,setItems]=useState([]); const [loading,setLoading]=useState(false); const [error,setError]=useState("");
  const load=async()=>{setLoading(true);setError("");try{const d=await operationsApi.getGoodsReceipts({site});setItems(d?.items||[]);}catch(e){setError(e.message||"Gagal mengambil penerimaan");}finally{setLoading(false);}};
  useEffect(()=>{load();},[site]);
  return <section className="ops-module"><div className="ops-module-header"><div><span className="ops-kicker">RECEIVING / REJECT</span><h3>Penerimaan Barang</h3><p>Received qty, rejected qty, dan accepted qty tidak mengubah PO awal.</p></div><div className="ops-inline-controls"><select value={site} onChange={e=>setSite(e.target.value)}><option value="">Semua site</option><option value="MAJA">Maja</option><option value="CEMPLANG">Cemplang</option></select><button onClick={load} disabled={loading}><RefreshCw size={15}/> Refresh</button></div></div>{error&&<div className="ops-error">{error}</div>}<div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Waktu</th><th>PO</th><th>Vendor</th><th>Site</th><th>Item</th><th>Diterima</th><th>Reject</th></tr></thead><tbody>{items.map(x=><tr key={x.id}><td>{x.received_at||"-"}</td><td>{x.po_code||"-"}</td><td>{x.vendor_code}</td><td>{x.site}</td><td>{x.item_count}</td><td>{x.received_qty_total}</td><td>{x.rejected_qty_total}</td></tr>)}{!loading&&items.length===0&&<tr><td colSpan="7" className="ops-empty-cell">Belum ada penerimaan di PostgreSQL.</td></tr>}</tbody></table></div></section>;
}
