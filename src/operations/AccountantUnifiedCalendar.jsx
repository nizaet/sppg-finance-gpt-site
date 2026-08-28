import React, { useEffect, useMemo, useState } from "react";
import { CalendarDays, CheckCircle2, ChevronLeft, ChevronRight, Copy, ExternalLink, FileSearch, List, RefreshCw, Stamp, Trash2, Upload, X } from "lucide-react";
import { accountantApi } from "./accountantApi.js";

const money = (value) => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(Number(value || 0));
const dateKey = (value) => /^\d{4}-\d{2}-\d{2}/.test(String(value || "")) ? String(value).slice(0, 10) : "";
const initialMonth = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
};
const shiftMonth = (value, delta) => {
  const [year, month] = value.split("-").map(Number);
  const next = new Date(year, month - 1 + delta, 1);
  return `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}`;
};
const monthTitle = (value) => {
  const [year, month] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("id-ID", { month: "long", year: "numeric" }).format(new Date(year, month - 1, 1));
};
const monthCells = (value) => {
  const [year, month] = value.split("-").map(Number);
  const first = new Date(year, month - 1, 1);
  const count = new Date(year, month, 0).getDate();
  const cells = Array((first.getDay() + 6) % 7).fill(null);
  for (let day = 1; day <= count; day += 1) cells.push(`${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`);
  while (cells.length % 7) cells.push(null);
  return cells;
};

function stateOf(row) {
  if (row.receipt_id || String(row.maker_status || "").toUpperCase() === "PAID") return "PAID";
  if (String(row.approval_status || "").toUpperCase() === "APPROVED") return "APPROVED";
  if (row.maker_id) return "PENDING";
  return "INVOICE";
}

const STATUS = {
  INVOICE: { label: "INVOICE · BELUM MAKER", bg: "#eff6ff", border: "#93c5fd", color: "#1d4ed8" },
  PENDING: { label: "MAKER · PENDING APPROVAL", bg: "#fff7ed", border: "#fdba74", color: "#9a3412" },
  APPROVED: { label: "APPROVED", bg: "#ecfdf5", border: "#6ee7b7", color: "#047857" },
  PAID: { label: "PAID", bg: "#dcfce7", border: "#4ade80", color: "#166534" },
};

export default function AccountantUnifiedCalendar({ refreshToken = 0, onChanged, reportError, reportMessage }) {
  const [items, setItems] = useState([]);
  const [month, setMonth] = useState(initialMonth);
  const [site, setSite] = useState("");
  const [category, setCategory] = useState("");
  const [viewMode, setViewMode] = useState("calendar");
  const [selectedId, setSelectedId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [proofFile, setProofFile] = useState(null);
  const [proofPreview, setProofPreview] = useState(null);

  const selected = items.find((row) => String(row.invoice_id) === String(selectedId)) || null;
  const refreshVersion = typeof refreshToken === "object" ? refreshToken.version : refreshToken;
  const copyToClipboard = async (value, label) => {
    const text = String(value ?? "");
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      reportMessage(`${label} disalin: ${text}`);
    } catch {
      const node = document.createElement("textarea");
      node.value = text; document.body.appendChild(node); node.select();
      document.execCommand("copy"); node.remove();
      reportMessage(`${label} disalin: ${text}`);
    }
  };
  const load = async () => {
    setBusy(true);
    try {
      const data = await accountantApi.getAllInvoices(site);
      setItems(data?.items || []);
    } catch (error) { reportError(error.message || "Gagal memuat kalender invoice"); }
    finally { setBusy(false); }
  };
  useEffect(() => {
    const focusedSite = typeof refreshToken === "object" ? refreshToken.site : "";
    const focusedDate = typeof refreshToken === "object" ? refreshToken.invoiceDate : "";
    if (focusedSite) setSite(focusedSite);
    if (/^\d{4}-\d{2}-\d{2}$/.test(String(focusedDate || ""))) {
      setMonth(focusedDate.slice(0, 7));
      setViewMode("list");
    }
  }, [refreshVersion]);
  useEffect(() => { load(); }, [site, refreshVersion]);

  const categories = useMemo(() => [...new Set(items.map((row) => String(row.invoice_category || "OPERASIONAL_LAIN")).filter(Boolean))].sort(), [items]);
  const visibleItems = useMemo(() => items.filter((row) => !category || String(row.invoice_category || "OPERASIONAL_LAIN") === category), [items, category]);
  const grouped = useMemo(() => visibleItems.reduce((map, row) => {
    const key = dateKey(row.invoice_date);
    if (key) (map[key] ||= []).push(row);
    return map;
  }, {}), [visibleItems]);
  const cells = useMemo(() => monthCells(month), [month]);
  const counts = useMemo(() => visibleItems.reduce((result, row) => {
    result[stateOf(row)] += 1;
    return result;
  }, { INVOICE: 0, PENDING: 0, APPROVED: 0, PAID: 0 }), [visibleItems]);

  const afterAction = async (message) => {
    reportMessage(message);
    setProofFile(null); setProofPreview(null);
    await load(); await onChanged?.();
  };
  const createMaker = async () => {
    if (!selected || !window.confirm(`Buat Maker dari invoice ${selected.invoice_number} sebesar ${money(selected.invoice_amount)}?`)) return;
    setBusy(true); reportError("");
    try {
      const result = await accountantApi.createMakerFromInvoice(selected.invoice_id);
      await afterAction(result.duplicate ? `Maker #${result.makerId} untuk invoice ini sudah ada.` : `Maker #${result.makerId} dibuat dan menunggu approval / pembayaran.`);
    } catch (error) { reportError(error.message || "Gagal membuat Maker"); }
    finally { setBusy(false); }
  };
  const approveWithoutEvidence = async () => {
    if (!selected?.maker_id || !window.confirm(`Tandai Maker #${selected.maker_id} sebagai APPROVED tanpa bukti file?`)) return;
    setBusy(true); reportError("");
    try { await accountantApi.confirmMakerApproved(selected.maker_id); await afterAction(`Maker #${selected.maker_id} ditandai APPROVED dan PAID.`); }
    catch (error) { reportError(error.message || "Gagal mengubah status approval"); }
    finally { setBusy(false); }
  };
  const cancelApproval = async () => {
    if (!selected?.maker_id || !window.confirm(`Batalkan APPROVED Maker #${selected.maker_id} dan kembalikan ke PENDING?`)) return;
    setBusy(true); reportError("");
    try { await accountantApi.cancelMakerApproval(selected.maker_id); await afterAction(`Approval Maker #${selected.maker_id} dibatalkan.`); }
    catch (error) { reportError(error.message || "Gagal membatalkan approval"); }
    finally { setBusy(false); }
  };
  const cancelMaker = async () => {
    if (!selected?.maker_id || !window.confirm(`Batalkan Maker #${selected.maker_id}? Invoice tetap tersimpan dan dapat dibuat ulang.`)) return;
    setBusy(true); reportError("");
    try { await accountantApi.cancelMaker(selected.maker_id); await afterAction(`Maker #${selected.maker_id} dibatalkan. Invoice tetap tersimpan.`); setSelectedId(selected.invoice_id); }
    catch (error) { reportError(error.message || "Gagal membatalkan Maker"); }
    finally { setBusy(false); }
  };
  const readProof = async () => {
    if (!proofFile) return reportError("Pilih file bukti approval terlebih dahulu.");
    setBusy(true); reportError(""); setProofPreview(null);
    try { setProofPreview(await accountantApi.previewApprovalEvidence({ file: proofFile, site: selected?.site || null })); }
    catch (error) { reportError(error.message || "Gagal membaca bukti approval"); }
    finally { setBusy(false); }
  };
  const saveProof = async () => {
    if (!proofPreview?.willApproveCount) return reportError("Tidak ada transaksi SUCCESS yang cocok dengan Maker.");
    if (!window.confirm(`File ini akan menandai ${proofPreview.willApproveCount} Maker sebagai APPROVED. Lanjutkan?`)) return;
    setBusy(true); reportError("");
    try {
      const result = await accountantApi.commitApprovalEvidence({ file: proofFile, site: selected?.site || null, parsedPayload: proofPreview.raw });
      await afterAction(`${result.paidCount || result.approvedCount} Maker ditandai APPROVED dan PAID; satu link bukti dipakai pada semua transaksi yang cocok.`);
    } catch (error) { reportError(error.message || "Gagal menyimpan bukti approval"); }
    finally { setBusy(false); }
  };


  const deleteInvoice = async () => {
    if (!selected || selected.accountant_submission_id != null) return;
    if (!window.confirm(`Hapus invoice ${selected.invoice_number || `#${selected.invoice_id}`} yang salah? File Drive dan Maker yang masih PENDING ikut dihapus. Data PAID tidak dapat dihapus.`)) return;
    setBusy(true); reportError("");
    try {
      const result = await accountantApi.deleteInvoice(selected.invoice_id);
      await afterAction(`Invoice #${selected.invoice_id} dihapus${result.deletedMakerIds?.length ? `; ${result.deletedMakerIds.length} Maker pending ikut dihapus` : ""}.`);
      setSelectedId(null);
    } catch (error) { reportError(error.message || "Gagal menghapus invoice"); }
    finally { setBusy(false); }
  };
  return <section className="ops-module">
    <div className="ops-module-header">
      <div><span className="ops-kicker">KALENDER INVOICE & BGN TERPADU</span><h3>Invoice → Maker → Approval / Paid</h3><p>Semua invoice bahan baku dan operasional tampil pada tanggal invoice. Pada alur BGN, approval berarti transaksi PAID.</p></div>
      <div className="ops-inline-controls"><select aria-label="Filter site" value={site} onChange={(event)=>setSite(event.target.value)}><option value="">Semua site</option><option value="MAJA">MAJA</option><option value="CEMPLANG">CEMPLANG</option></select><select aria-label="Filter kategori" value={category} onChange={(event)=>setCategory(event.target.value)}><option value="">Semua kategori</option>{categories.map((value)=><option key={value} value={value}>{value.replaceAll("_"," ")}</option>)}</select><button type="button" className={viewMode === "list" ? "ops-toggle-active" : ""} onClick={()=>setViewMode("list")}><List size={14}/> List</button><button type="button" className={viewMode === "calendar" ? "ops-toggle-active" : ""} onClick={()=>setViewMode("calendar")}><CalendarDays size={14}/> Kalender</button><button type="button" onClick={load} disabled={busy}><RefreshCw size={14}/> Refresh</button></div>
    </div>
    <div className="ops-summary-strip" style={{ marginBottom: 12 }}>{Object.entries(STATUS).map(([key, meta])=><span key={key} style={{ background: meta.bg, border: `1px solid ${meta.border}` }}>{meta.label} <strong>{counts[key]}</strong></span>)}</div>
    {viewMode === "calendar" && <><div className="ops-row-actions" style={{ justifyContent: "space-between", marginBottom: 10 }}><button type="button" onClick={()=>setMonth(shiftMonth(month,-1))}><ChevronLeft size={15}/> Bulan lalu</button><strong style={{ fontSize: 18, textTransform: "capitalize" }}><CalendarDays size={17} style={{ verticalAlign: "-3px", marginRight: 6 }}/>{monthTitle(month)}</strong><button type="button" onClick={()=>setMonth(shiftMonth(month,1))}>Bulan berikut <ChevronRight size={15}/></button></div>
    <div style={{ overflowX: "auto" }}><div style={{ minWidth: 980 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7,minmax(0,1fr))", gap: 6, marginBottom: 6 }}>{["Sen","Sel","Rab","Kam","Jum","Sab","Min"].map(day=><div key={day} style={{ fontWeight: 800, textAlign: "center", padding: 6 }}>{day}</div>)}</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7,minmax(0,1fr))", gap: 6 }}>{cells.map((day,index)=><div key={day||`blank-${index}`} style={{ minHeight: 150, border: "1px solid #d8e1ec", borderRadius: 10, padding: 7, background: day ? "#fff" : "#f8fafc" }}>
        {day&&<><div style={{ fontWeight: 800, marginBottom: 6 }}>{Number(day.slice(-2))}</div>{(grouped[day]||[]).map(row=>{const state=stateOf(row);const meta=STATUS[state];return <button type="button" key={row.invoice_id} onClick={()=>{setSelectedId(row.invoice_id);setProofFile(null);setProofPreview(null);}} style={{ display: "block", width: "100%", textAlign: "left", marginBottom: 6, padding: 7, borderRadius: 8, border: `1px solid ${meta.border}`, background: meta.bg, color: "#1e293b", cursor: "pointer" }}><strong>{row.site} · {row.invoice_number||`Invoice #${row.invoice_id}`}</strong>{row.invoice_number_conflict&&<div style={{ color:"#b45309", fontWeight:800 }}>⚠ Nomor invoice sama</div>}<div>{String(row.invoice_category||"LAIN").replaceAll("_"," ")}</div><div>{money(row.invoice_amount)}</div><div style={{ color: meta.color, fontWeight: 800, marginTop: 2 }}>{meta.label}</div></button>})}</>}
      </div>)}</div>
    </div></div></>}
    {viewMode === "list" && <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Tanggal</th><th>Site</th><th>Kategori</th><th>Invoice</th><th>Nilai</th><th>Status</th><th>Maker</th><th>File</th><th>Aksi</th></tr></thead><tbody>{visibleItems.map((row)=>{const status=stateOf(row);const meta=STATUS[status];return <tr key={row.invoice_id} style={{ background: meta.bg }}><td>{dateKey(row.invoice_date)||"-"}</td><td><strong>{row.site}</strong></td><td>{String(row.invoice_category||"OPERASIONAL_LAIN").replaceAll("_"," ")}</td><td><strong>{row.invoice_number||`#${row.invoice_id}`}</strong>{row.invoice_number_conflict&&<div style={{ color:"#b45309", fontSize:11, fontWeight:800 }}>⚠ Nomor sama</div>}</td><td>{money(row.invoice_amount)}</td><td><span style={{ display:"inline-block", padding:"4px 7px", borderRadius:7, color:meta.color, border:`1px solid ${meta.border}`, fontWeight:800 }}>{meta.label}</span></td><td>{row.maker_id ? `#${row.maker_id} · ${status}` : "Belum dibuat"}</td><td>{row.invoice_evidence_uri?<button type="button" onClick={()=>window.open(row.invoice_evidence_uri,"_blank","noopener,noreferrer")}><ExternalLink size={14}/> Invoice</button>:"-"}</td><td><button type="button" onClick={()=>{setSelectedId(row.invoice_id);setProofFile(null);setProofPreview(null);}}>Kelola</button></td></tr>;})}{!busy&&!visibleItems.length&&<tr><td colSpan="9" className="ops-empty-cell">Tidak ada invoice untuk filter ini.</td></tr>}</tbody></table></div>}

    {selected&&<div role="presentation" onMouseDown={(event)=>{if(event.target===event.currentTarget)setSelectedId(null);}} style={{ position:"fixed", inset:0, background:"rgba(15,23,42,.48)", zIndex:1000, display:"grid", placeItems:"center", padding:18 }}><div role="dialog" aria-modal="true" style={{ width:"min(680px,96vw)", maxHeight:"90vh", overflowY:"auto", background:"#fff", borderRadius:16, boxShadow:"0 24px 70px rgba(15,23,42,.3)", padding:20 }}>
      <div className="ops-module-header"><div><span className="ops-kicker">DETAIL INVOICE</span><h3>{selected.invoice_number||`Invoice #${selected.invoice_id}`}</h3></div><button type="button" onClick={()=>setSelectedId(null)} aria-label="Tutup"><X size={18}/></button></div>
      <div className="ops-summary-strip"><span>Site <strong>{selected.site}</strong></span><span>Tanggal invoice <strong>{dateKey(selected.invoice_date)||"-"}</strong></span><span>Kategori <strong>{String(selected.invoice_category||"-").replaceAll("_"," ")}</strong></span><span>Nomor <strong>{selected.invoice_number||`#${selected.invoice_id}`}</strong><button type="button" title="Salin nomor invoice" aria-label="Salin nomor invoice" onClick={()=>copyToClipboard(selected.invoice_number||`#${selected.invoice_id}`, "Nomor invoice")} style={{ marginLeft:6, padding:"2px 5px" }}><Copy size={13}/></button></span><span>Nilai <strong>{money(selected.invoice_amount)}</strong><button type="button" title="Salin nilai tanpa titik" aria-label="Salin nilai tanpa titik" onClick={()=>copyToClipboard(Math.round(Number(selected.invoice_amount||0)), "Nilai invoice")} style={{ marginLeft:6, padding:"2px 5px" }}><Copy size={13}/></button></span></div>
      {selected.invoice_number_conflict&&<div className="ops-notice"><strong>⚠ Nomor invoice sama.</strong> Dokumen ini tetap tersimpan terpisah; periksa kedua invoice sebelum membuat Maker.</div>}
      <div style={{ margin:"14px 0", padding:12, borderRadius:10, background:STATUS[stateOf(selected)].bg, border:`1px solid ${STATUS[stateOf(selected)].border}` }}><strong style={{ color:STATUS[stateOf(selected)].color }}>{STATUS[stateOf(selected)].label}</strong>{selected.maker_id&&<div>Maker #{selected.maker_id} · {selected.maker_status||"CREATED"}</div>}</div>
      <div className="ops-row-actions">
        {selected.invoice_evidence_uri&&<button type="button" onClick={()=>window.open(selected.invoice_evidence_uri,"_blank","noopener,noreferrer")}><ExternalLink size={14}/> Buka Invoice</button>}
        {selected.approval_evidence_uri&&<button type="button" onClick={()=>window.open(selected.approval_evidence_uri,"_blank","noopener,noreferrer")}><ExternalLink size={14}/> Buka Bukti Approval</button>}
        {selected.accountant_submission_id == null && stateOf(selected)!=="PAID"&&<button type="button" className="danger" onClick={deleteInvoice} disabled={busy}><Trash2 size={14}/> Hapus Invoice</button>}
      </div>
      {selected.accountant_submission_id != null&&<p className="ops-muted">Invoice ini terhubung ke Excel Akuntan. Jika seluruh alurnya salah, hapus dari tombol <strong>Hapus Alur</strong> pada baris Excel.</p>}
      {!selected.maker_id&&<div style={{ marginTop:14 }}><p>Invoice sudah tersimpan, tetapi belum masuk daftar Maker.</p><button type="button" onClick={createMaker} disabled={busy}><Stamp size={14}/> Buat Maker</button></div>}
      {selected.maker_id&&stateOf(selected)==="PENDING"&&<div style={{ marginTop:14 }}><h4>Approval / Paid Maker</h4><div className="ops-row-actions"><button type="button" onClick={approveWithoutEvidence} disabled={busy}><CheckCircle2 size={14}/> Approve = PAID tanpa bukti</button><button type="button" className="danger" onClick={cancelMaker} disabled={busy}><Trash2 size={14}/> Batalkan Maker</button></div><div className="ops-form-grid" style={{ marginTop:10 }}><label>Bukti approval PDF / gambar<input type="file" accept="application/pdf,image/jpeg,image/png,image/webp" onChange={(event)=>{setProofFile(event.target.files?.[0]||null);setProofPreview(null);}}/></label><label>Aksi<button type="button" onClick={readProof} disabled={busy||!proofFile}><FileSearch size={14}/> Baca Bukti</button></label></div>{proofPreview&&<div className="ops-parse-result"><strong>{proofPreview.transactionCount} transaksi · {proofPreview.matchedCount} cocok · {proofPreview.willApproveCount} akan menjadi PAID</strong><p>Satu file dapat menandai beberapa Maker yang cocok sebagai APPROVED dan PAID; file hanya disimpan sekali dan setiap item memakai link yang sama.</p><button type="button" onClick={saveProof} disabled={busy||!proofPreview.willApproveCount}><Upload size={14}/> Simpan Bukti & Tandai PAID</button></div>}</div>}
      {stateOf(selected)==="APPROVED"&&<div className="ops-row-actions" style={{ marginTop:14 }}><button type="button" className="danger" onClick={cancelApproval} disabled={busy}>Batal Approve</button></div>}
      {stateOf(selected)==="PAID"&&<div className="ops-success" style={{ marginTop:14 }}>Alur selesai: Maker sudah APPROVED dan pembayaran sudah diterima.</div>}
    </div></div>}
  </section>;
}
