import React, { useEffect, useState } from "react";
import { CheckCircle2, ExternalLink, FileSearch, RefreshCw, Upload } from "lucide-react";
import { accountantApi } from "./accountantApi.js";

const money = (v) => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(Number(v || 0));
const CATEGORIES = [
  ["SEWA_MITRA", "Sewa / Insentif Mitra"], ["TOKEN_LISTRIK", "Token Listrik"],
  ["GAJI_RELAWAN", "Gaji Relawan"], ["SEWA_MOBIL", "Sewa Mobil"],
  ["UPAH", "Upah"], ["BAHAN_BAKU", "Bahan Baku"], ["OPERASIONAL_LAIN", "Operasional Lain"],
];

export default function AccountantDocumentPanel({ onChanged, reportError, reportMessage }) {
  const [site, setSite] = useState("MAJA");
  const [category, setCategory] = useState("SEWA_MITRA");
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [direct, setDirect] = useState([]);
  const [proofSite, setProofSite] = useState("MAJA");
  const [proofFile, setProofFile] = useState(null);
  const [proofPreview, setProofPreview] = useState(null);
  const [proofBusy, setProofBusy] = useState(false);

  const loadDirect = async () => {
    try { setDirect((await accountantApi.getDirectInvoices("")).items || []); }
    catch (e) { reportError(e.message || "Gagal memuat invoice langsung"); }
  };
  useEffect(() => { loadDirect(); }, []);

  const readInvoice = async () => {
    if (!file) return reportError("Pilih file invoice PDF/JPG/PNG terlebih dahulu.");
    setBusy(true); reportError(""); setPreview(null);
    try {
      const data = await accountantApi.previewInvoiceDocument({ file, site, category });
      setPreview(data);
      reportMessage("Dokumen terbaca. Periksa dan koreksi nomor, tanggal, kategori, serta nilai sebelum simpan.");
    } catch (e) { reportError(e.message || "Gagal membaca invoice"); }
    finally { setBusy(false); }
  };

  const saveInvoice = async () => {
    if (!preview?.invoiceNumber || !preview?.invoiceDate || Number(preview?.invoiceAmount || 0) <= 0) return reportError("Nomor invoice, tanggal, dan nilai wajib diisi.");
    if (!window.confirm(`Simpan invoice ${preview.invoiceNumber} sebesar ${money(preview.invoiceAmount)} dan langsung buat Maker?`)) return;
    setBusy(true); reportError("");
    try {
      const result = await accountantApi.commitInvoiceDocument({ file, preview, site, category });
      reportMessage(result.duplicate ? `Invoice ${preview.invoiceNumber} sudah pernah tercatat.` : `Invoice #${result.accountantInvoiceId} tersimpan; Maker #${result.makerId} dibuat dan menunggu Approval.`);
      setFile(null); setPreview(null); await loadDirect(); await onChanged?.();
    } catch (e) { reportError(e.message || "Gagal menyimpan invoice"); }
    finally { setBusy(false); }
  };

  const readProof = async () => {
    if (!proofFile) return reportError("Pilih file bukti approval terlebih dahulu.");
    setProofBusy(true); reportError(""); setProofPreview(null);
    try {
      const data = await accountantApi.previewApprovalEvidence({ file: proofFile, site: proofSite });
      setProofPreview(data); reportMessage(`${data.transactionCount} transaksi terbaca; ${data.willApproveCount} Maker cocok dan siap ditandai APPROVED.`);
    } catch (e) { reportError(e.message || "Gagal membaca bukti approval"); }
    finally { setProofBusy(false); }
  };

  const saveProof = async () => {
    if (!proofPreview?.willApproveCount) return reportError("Tidak ada transaksi SUCCESS yang cocok secara aman.");
    if (!window.confirm(`Tandai ${proofPreview.willApproveCount} Maker sebagai APPROVED dan tautkan satu file bukti yang sama?`)) return;
    setProofBusy(true); reportError("");
    try {
      const result = await accountantApi.commitApprovalEvidence({ file: proofFile, site: proofSite, parsedPayload: proofPreview.raw });
      reportMessage(`${result.approvedCount} Maker ditandai APPROVED. File bukti hanya diupload sekali dan linknya dipakai bersama.`);
      setProofFile(null); setProofPreview(null); await loadDirect(); await onChanged?.();
    } catch (e) { reportError(e.message || "Gagal menyimpan bukti approval"); }
    finally { setProofBusy(false); }
  };

  return <>
    <section className="ops-module">
      <div className="ops-module-header"><div><span className="ops-kicker">INVOICE LANGSUNG → MAKER</span><h3>Upload Invoice PDF / Gambar Tanpa Excel</h3><p>Untuk sewa mitra, token listrik, gaji relawan, sewa mobil, upah, dan invoice operasional lain. Sistem membaca dokumen lalu menampilkan hasil yang tetap dapat dikoreksi sebelum disimpan.</p></div></div>
      <div className="ops-form-grid">
        <label>Site<select value={site} onChange={e=>{setSite(e.target.value);setPreview(null);}}><option value="MAJA">MAJA</option><option value="CEMPLANG">CEMPLANG</option></select></label>
        <label>Kategori<select value={category} onChange={e=>{setCategory(e.target.value);setPreview(null);}}>{CATEGORIES.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
        <label>File invoice<input type="file" accept="application/pdf,image/jpeg,image/png,image/webp" onChange={e=>{setFile(e.target.files?.[0]||null);setPreview(null);}}/></label>
        <label>Aksi<button type="button" onClick={readInvoice} disabled={busy||!file}><FileSearch size={14}/> {busy?"Membaca…":"Baca Invoice"}</button></label>
      </div>
      {preview&&<div className="ops-parse-result">
        <div><FileSearch size={16}/><strong>Hasil Pembacaan — belum disimpan</strong></div>
        {!!preview.warnings?.length&&<div className="ops-notice">{preview.warnings.join(" ")}</div>}
        {category==="SEWA_MITRA"&&preview.operationalDateConfirmed===true&&<div className="ops-success">Tanggal invoice cocok dengan {preview.operationalPlanCount} perencanaan Kalkulator yang terisi.</div>}
        {category==="SEWA_MITRA"&&preview.operationalDateConfirmed===false&&<div className="ops-error">Tanggal ini belum terkonfirmasi sebagai hari operasional pada Kalkulator. Periksa tanggal sebelum simpan.</div>}
        <div className="ops-form-grid">
          <label>Nomor invoice<input value={preview.invoiceNumber||""} onChange={e=>setPreview({...preview,invoiceNumber:e.target.value})}/></label>
          <label>Tanggal invoice<input type="date" value={preview.invoiceDate||""} onChange={e=>setPreview({...preview,invoiceDate:e.target.value})}/></label>
          <label>Periode mulai<input type="date" value={preview.periodStart||""} onChange={e=>setPreview({...preview,periodStart:e.target.value||null})}/></label>
          <label>Periode selesai<input type="date" value={preview.periodEnd||""} onChange={e=>setPreview({...preview,periodEnd:e.target.value||null})}/></label>
          <label>Nilai invoice<input type="number" min="1" value={preview.invoiceAmount||""} onChange={e=>setPreview({...preview,invoiceAmount:e.target.value})}/></label>
          <label>Site<select value={site} onChange={e=>setSite(e.target.value)}><option value="MAJA">MAJA</option><option value="CEMPLANG">CEMPLANG</option></select></label>
        </div>
        {!!preview.lines?.length&&<div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Item</th><th>Qty</th><th>Satuan</th><th>Harga</th><th>Total</th></tr></thead><tbody>{preview.lines.map((x,i)=><tr key={i}><td>{x.item_name}</td><td>{x.quantity??"-"}</td><td>{x.unit||"-"}</td><td>{money(x.unit_price)}</td><td>{money(x.line_total)}</td></tr>)}</tbody></table></div>}
        <div className="ops-row-actions"><button type="button" onClick={saveInvoice} disabled={busy}><Upload size={14}/> Simpan Invoice & Buat Maker</button></div>
      </div>}
      <div className="ops-table-wrap" style={{marginTop:16}}><table className="ops-table"><thead><tr><th>Site</th><th>Kategori</th><th>Invoice</th><th>Tanggal</th><th>Nilai</th><th>Maker</th><th>Approval</th><th>File</th></tr></thead><tbody>{direct.map(x=><tr key={x.invoice_id}><td>{x.site}</td><td>{x.invoice_category}</td><td><strong>{x.invoice_number}</strong></td><td>{x.invoice_date||x.period_start||"-"}</td><td>{money(x.invoice_amount)}</td><td>{x.maker_id?`#${x.maker_id} · ${x.maker_status}`:"BELUM DIBUAT"}</td><td><strong>{x.approval_status||"PENDING"}</strong>{x.approval_evidence_uri&&<div><button type="button" onClick={()=>window.open(x.approval_evidence_uri,"_blank","noopener,noreferrer")}><ExternalLink size={13}/> Bukti</button></div>}</td><td>{x.invoice_evidence_uri&&<button type="button" onClick={()=>window.open(x.invoice_evidence_uri,"_blank","noopener,noreferrer")}><ExternalLink size={13}/> Invoice</button>}</td></tr>)}</tbody></table></div>
    </section>

    <section className="ops-module">
      <div className="ops-module-header"><div><span className="ops-kicker">BUKTI APPROVAL MASSAL</span><h3>Satu File untuk Beberapa Maker</h3><p>Sistem membaca seluruh transaksi dalam PDF/gambar, mencocokkan nomor referensi atau nilai unik, lalu menautkan satu link Drive ke semua Maker yang cocok. Transaksi Pending/Failed tidak diapprove.</p></div><button type="button" onClick={loadDirect}><RefreshCw size={14}/> Refresh</button></div>
      <div className="ops-form-grid">
        <label>Site<select value={proofSite} onChange={e=>{setProofSite(e.target.value);setProofPreview(null);}}><option value="MAJA">MAJA</option><option value="CEMPLANG">CEMPLANG</option></select></label>
        <label>File bukti approval<input type="file" accept="application/pdf,image/jpeg,image/png,image/webp" onChange={e=>{setProofFile(e.target.files?.[0]||null);setProofPreview(null);}}/></label>
        <label>Aksi<button type="button" onClick={readProof} disabled={proofBusy||!proofFile}><FileSearch size={14}/> {proofBusy?"Membaca…":"Baca Semua Transaksi"}</button></label>
      </div>
      {proofPreview&&<div className="ops-parse-result">
        <div><CheckCircle2 size={16}/><strong>{proofPreview.transactionCount} transaksi · {proofPreview.matchedCount} cocok · {proofPreview.willApproveCount} akan diapprove</strong></div>
        <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Referensi Bukti</th><th>Nilai</th><th>Status Bank</th><th>Maker Cocok</th><th>Hasil</th></tr></thead><tbody>{proofPreview.transactions.map((x,i)=><tr key={i}><td>{x.referenceNumber||"-"}</td><td>{money(x.amount)}</td><td>{x.status}</td><td>{x.matchedMakerId?`#${x.matchedMakerId} · ${x.matchedReference}`:"Tidak ditemukan"}</td><td>{x.willApprove?"APPROVE":"REVIEW / ABAIKAN"}</td></tr>)}</tbody></table></div>
        <div className="ops-row-actions"><button type="button" onClick={saveProof} disabled={proofBusy||!proofPreview.willApproveCount}><Upload size={14}/> Simpan Bukti & Approve {proofPreview.willApproveCount} Maker</button></div>
      </div>}
    </section>
  </>;
}
