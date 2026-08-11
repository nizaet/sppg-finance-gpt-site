import React, { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { operationsApi } from "./apiClient";

export default function OperationsAudit(){
  const [items,setItems]=useState([]); const [loading,setLoading]=useState(false); const [error,setError]=useState("");
  const load=async()=>{setLoading(true);setError("");try{const d=await operationsApi.getAuditLog(300);setItems(d?.items||[]);}catch(e){setError(e.message||"Gagal mengambil audit log");}finally{setLoading(false);}};
  useEffect(()=>{load();},[]);
  return <section className="ops-module"><div className="ops-module-header"><div><span className="ops-kicker">APPEND-ONLY TRACE</span><h3>Audit Trail</h3><p>Keputusan review dan tindakan workflow dilacak bersama source event.</p></div><button onClick={load} disabled={loading}><RefreshCw size={15}/> Refresh</button></div>{error&&<div className="ops-error">{error}</div>}<div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Waktu</th><th>Aksi</th><th>Aktor</th><th>Event</th><th>Site</th><th>Vendor</th><th>Source</th></tr></thead><tbody>{items.map(x=><tr key={x.id}><td>{x.created_at}</td><td>{x.action}</td><td>{x.actor||"-"}</td><td>{x.event_type||"-"}</td><td>{x.site||"-"}</td><td>{x.vendor_code||"-"}</td><td className="ops-source-cell">{x.raw_text||JSON.stringify(x.details||{})}</td></tr>)}{!loading&&items.length===0&&<tr><td colSpan="7" className="ops-empty-cell">Audit log masih kosong.</td></tr>}</tbody></table></div></section>;
}
