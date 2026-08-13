import React, { useEffect, useMemo, useState } from "react";
import { ClipboardCopy, ExternalLink, MessageCircle, RefreshCw } from "lucide-react";
import { operationsApi } from "./apiClient";

const money = (v) => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(Number(v || 0));

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

function accountantMessage(row) {
  return [
    `*SPPG ${row.site || "-"} — DATA AKUNTAN*`,
    `Akuntan: ${row.accountant_code || "-"}`,
    `Status pengiriman: ${row.submission_status || "-"}`,
    `Tanggal kirim: ${row.sent_at || "-"}`,
    row.excel_evidence_uri ? `File Excel: ${row.excel_evidence_uri}` : "File Excel: belum ada link tersimpan",
    row.invoice_number ? `Invoice diterima: ${row.invoice_number} — ${money(row.invoice_amount)}` : "Invoice balasan: belum diterima",
  ].join("\n");
}

function pendingApprovalMessage(rows) {
  const pending = rows.filter((x) => String(x.approval_status || "PENDING").toUpperCase() !== "APPROVED");
  const lines = ["*REKAP PENDING APPROVAL BGN*", ""];
  pending.forEach((x, index) => {
    lines.push(`${index + 1}. ${x.site} — ${x.reference_number || `Maker #${x.maker_id}`} — ${money(x.maker_amount)} — Approver: ${x.approver_code || "belum ditetapkan"} — Status: ${x.approval_status || "BELUM DIMINTA"}`);
  });
  if (!pending.length) lines.push("Tidak ada approval pending.");
  return lines.join("\n");
}

export default function OperationsAccountantBgn(){
  const [site,setSite]=useState("");
  const [accountant,setAccountant]=useState([]);
  const [bgn,setBgn]=useState([]);
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(false);
  const [message,setMessage]=useState("");

  const load=async()=>{
    setLoading(true); setError("");
    try{
      const [a,b]=await Promise.all([operationsApi.getAccountantFlow(site),operationsApi.getBgnFlow(site)]);
      setAccountant(a?.items||[]); setBgn(b?.items||[]);
    }catch(e){setError(e.message||"Gagal mengambil alur akuntan/BGN");}
    finally{setLoading(false);}
  };
  useEffect(()=>{load();},[site]);

  const pendingBgn = useMemo(
    () => bgn.filter((x) => String(x.approval_status || "PENDING").toUpperCase() !== "APPROVED"),
    [bgn],
  );

  const copyAccountant = async (row) => {
    await copyText(accountantMessage(row));
    setMessage("Pesan akuntan sudah disalin.");
  };
  const waAccountant = (row) => {
    window.open(`https://wa.me/?text=${encodeURIComponent(accountantMessage(row))}`, "_blank", "noopener,noreferrer");
    setMessage("WhatsApp dibuka. Pilih Tiara/Uya yang sesuai sebelum kirim.");
  };
  const copyPending = async () => {
    await copyText(pendingApprovalMessage(bgn));
    setMessage("Rekap pending approval sudah disalin.");
  };
  const waPending = () => {
    window.open(`https://wa.me/?text=${encodeURIComponent(pendingApprovalMessage(bgn))}`, "_blank", "noopener,noreferrer");
    setMessage("WhatsApp dibuka dengan rekap pending approval. Pilih Embun/Malik sesuai site sebelum kirim.");
  };

  return <div className="ops-domain-stack">
    <section className="ops-module">
      <div className="ops-module-header">
        <div><span className="ops-kicker">ACCOUNTANT</span><h3>Excel & Invoice Akuntan</h3><p>Maja → Tiara · Cemplang → Uya. Pengiriman WhatsApp masih manual; tombol hanya menyiapkan pesan/link dan tidak menganggap file sudah terkirim.</p></div>
        <div className="ops-inline-controls"><select value={site} onChange={e=>setSite(e.target.value)}><option value="">Semua site</option><option value="MAJA">Maja</option><option value="CEMPLANG">Cemplang</option></select><button onClick={load} disabled={loading}><RefreshCw size={15}/> Refresh</button></div>
      </div>
      {error&&<div className="ops-error">{error}</div>}
      {message&&<div className="ops-success">{message}</div>}
      <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Site</th><th>Akuntan</th><th>Excel Sent</th><th>Status</th><th>Invoice</th><th>Nilai</th><th>Diterima</th><th>Aksi Manual</th></tr></thead><tbody>{accountant.map(x=><tr key={`${x.submission_id}-${x.invoice_id||0}`}><td>{x.site}</td><td>{x.accountant_code}</td><td>{x.sent_at||"-"}</td><td>{x.submission_status}</td><td>{x.invoice_number||"-"}</td><td>{money(x.invoice_amount)}</td><td>{x.received_at||"-"}</td><td><div className="ops-row-actions">{x.excel_evidence_uri&&<button type="button" onClick={()=>window.open(x.excel_evidence_uri,"_blank","noopener,noreferrer")}><ExternalLink size={14}/> Buka Excel</button>}<button type="button" onClick={()=>copyAccountant(x)}><ClipboardCopy size={14}/> Copy Pesan</button><button type="button" onClick={()=>waAccountant(x)}><MessageCircle size={14}/> WhatsApp</button></div></td></tr>)}{!loading&&accountant.length===0&&<tr><td colSpan="8" className="ops-empty-cell">Belum ada submission akuntan.</td></tr>}</tbody></table></div>
    </section>

    <section className="ops-module">
      <div className="ops-module-header">
        <div><span className="ops-kicker">BGN</span><h3>Maker & Pending Approval</h3><p>Maker, daftar approval, dan approval confirmed adalah state terpisah. Rekap dapat dicopy atau dibuka di WhatsApp tanpa mengubah status approval.</p></div>
        <div className="ops-row-actions"><button type="button" onClick={copyPending}><ClipboardCopy size={14}/> Copy Pending ({pendingBgn.length})</button><button type="button" onClick={waPending}><MessageCircle size={14}/> WhatsApp Pending</button></div>
      </div>
      <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Site</th><th>Maker</th><th>Referensi</th><th>Nilai</th><th>Maker Status</th><th>Approver</th><th>Approval</th><th>Approved</th></tr></thead><tbody>{bgn.map(x=><tr key={x.maker_id}><td>{x.site}</td><td>#{x.maker_id}</td><td>{x.reference_number||"-"}</td><td>{money(x.maker_amount)}</td><td>{x.maker_status}</td><td>{x.approver_code||"-"}</td><td>{x.approval_status||"Belum diminta"}</td><td>{x.approved_at||"-"}</td></tr>)}{!loading&&bgn.length===0&&<tr><td colSpan="8" className="ops-empty-cell">Belum ada maker BGN.</td></tr>}</tbody></table></div>
    </section>
  </div>;
}
