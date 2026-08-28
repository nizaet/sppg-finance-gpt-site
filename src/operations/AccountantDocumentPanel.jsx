import React, { useState } from "react";
import { CheckCircle2, FileSearch, Upload } from "lucide-react";
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
  const [invoiceProgress, setInvoiceProgress] = useState(null);
  const [proofSite, setProofSite] = useState("MAJA");
  const [proofFile, setProofFile] = useState(null);
  const [proofPreview, setProofPreview] = useState(null);
  const [proofBusy, setProofBusy] = useState(false);
  const [proofProgress, setProofProgress] = useState(null);

  const readInvoice = async () => {
    if (!file) return reportError("Pilih file invoice PDF/JPG/PNG terlebih dahulu.");
    const progressTimer = startReadProgress(setInvoiceProgress);
    setBusy(true); reportError(""); setPreview(null);
    try {
      const data = await accountantApi.previewInvoiceDocument({
        file, site, category,
        onReadProgress: ({ loaded, total }) => total && setInvoiceProgress({
          percent: Math.max(8, Math.min(35, Math.round((loaded / total) * 35))),
          label: "Membaca file dari perangkat…",
        }),
      });
      setPreview(data);
      reportMessage("Dokumen terbaca. Periksa dan koreksi nomor, tanggal, kategori, serta nilai sebelum simpan.");
    } catch (e) { reportError(e.message || "Gagal membaca invoice"); }
    finally {
      window.clearInterval(progressTimer);
      setInvoiceProgress({ percent: 100, label: "Pembacaan selesai." });
      window.setTimeout(() => setInvoiceProgress(null), 900);
      setBusy(false);
    }
  };

  const saveInvoice = async () => {
    const effectiveInvoiceDate = preview?.invoiceDate || preview?.periodEnd || preview?.periodStart;
    if (!preview?.invoiceNumber || !effectiveInvoiceDate || Number(preview?.invoiceAmount || 0) <= 0) return reportError("Nomor invoice, tanggal/periode, dan nilai wajib diisi.");
    const readyPreview = { ...preview, invoiceDate: effectiveInvoiceDate };
    if (!window.confirm(`Simpan invoice ${preview.invoiceNumber} sebesar ${money(preview.invoiceAmount)}? Maker belum dibuat sampai tombol Buat Maker diklik pada Kalender Invoice.`)) return;
    setBusy(true); reportError("");
    try {
      const result = await accountantApi.commitInvoiceDocument({ file, preview: readyPreview, site, category });
      reportMessage(result.duplicate ? `Invoice ${preview.invoiceNumber} sudah pernah tercatat.` : `Invoice #${result.accountantInvoiceId} tersimpan. Maker belum dibuat; buka invoice pada kalender lalu klik Buat Maker.`);
      setFile(null); setPreview(null); await onChanged?.();
    } catch (e) { reportError(e.message || "Gagal menyimpan invoice"); }
    finally { setBusy(false); }
  };

  const readProof = async () => {
    if (!proofFile) return reportError("Pilih file bukti approval terlebih dahulu.");
    const progressTimer = startReadProgress(setProofProgress);
    setProofBusy(true); reportError(""); setProofPreview(null);
    try {
      const data = await accountantApi.previewApprovalEvidence({
        file: proofFile, site: proofSite,
        onReadProgress: ({ loaded, total }) => total && setProofProgress({
          percent: Math.max(8, Math.min(35, Math.round((loaded / total) * 35))),
          label: "Membaca file dari perangkat…",
        }),
      });
      setProofPreview(data); reportMessage(`${data.transactionCount} transaksi terbaca; ${data.willApproveCount} Maker cocok dan siap ditandai PAID.`);
    } catch (e) { reportError(e.message || "Gagal membaca bukti approval"); }
    finally {
      window.clearInterval(progressTimer);
      setProofProgress({ percent: 100, label: "Pembacaan selesai." });
      window.setTimeout(() => setProofProgress(null), 900);
      setProofBusy(false);
    }
  };

  const saveProof = async () => {
    if (!proofPreview?.willApproveCount) return reportError("Tidak ada transaksi SUCCESS yang cocok secara aman.");
    if (!window.confirm(`Tandai ${proofPreview.willApproveCount} Maker sebagai PAID dan tautkan satu file bukti yang sama?`)) return;
    setProofBusy(true); reportError("");
    try {
      const result = await accountantApi.commitApprovalEvidence({ file: proofFile, site: proofSite, parsedPayload: proofPreview.raw });
      const ledger = result.accountantLedgerSync;
      const syncInfo = ledger
        ? ` ${ledger.synced || 0} pemasukan disinkronkan ke Akuntan ${proofSite} sejak ${ledger.fromDate || "2026-08-24"}.`
        : "";
      reportMessage(`${result.paidCount || result.approvedCount} Maker ditandai PAID. File bukti hanya diupload sekali dan linknya dipakai bersama.${syncInfo}`);
      setProofFile(null); setProofPreview(null); await onChanged?.();
    } catch (e) { reportError(e.message || "Gagal menyimpan bukti approval"); }
    finally { setProofBusy(false); }
  };

  return <>
    <section className="ops-module">
      <div className="ops-module-header"><div><span className="ops-kicker">UPLOAD INVOICE LANGSUNG</span><h3>Upload Invoice PDF / Gambar Tanpa Excel</h3><p>Dokumen disimpan sebagai invoice terlebih dahulu. Maker hanya dibuat setelah Anda membukanya pada Kalender Invoice dan menekan Buat Maker.</p></div></div>
      <div className="ops-form-grid">
        <label>Site<select value={site} onChange={e=>{setSite(e.target.value);setPreview(null);}}><option value="MAJA">MAJA</option><option value="CEMPLANG">CEMPLANG</option></select></label>
        <label>Kategori<select value={category} onChange={e=>{setCategory(e.target.value);setPreview(null);}}>{CATEGORIES.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
        <label>File invoice<input type="file" accept="application/pdf,image/jpeg,image/png,image/webp" onChange={e=>{setFile(e.target.files?.[0]||null);setPreview(null);}}/></label>
        <label>Aksi<button type="button" onClick={readInvoice} disabled={busy||!file}><FileSearch size={14}/> {busy?"Membaca…":"Baca Invoice"}</button></label>
      </div>
      {invoiceProgress&&<ReadProgress progress={invoiceProgress}/>}
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
        <div className="ops-row-actions"><button type="button" onClick={saveInvoice} disabled={busy}><Upload size={14}/> Simpan Invoice</button></div>
      </div>}
    </section>

    <section className="ops-module">
      <div className="ops-module-header"><div><span className="ops-kicker">BUKTI APPROVAL MASSAL</span><h3>Satu File untuk Beberapa Maker</h3><p>Sistem membaca seluruh transaksi dalam PDF/gambar, mencocokkan nomor referensi atau nilai unik, lalu menautkan satu link Drive ke semua Maker yang cocok. Transaksi Pending/Failed tidak diapprove.</p></div></div>
      <div className="ops-form-grid">
        <label>Site<select value={proofSite} onChange={e=>{setProofSite(e.target.value);setProofPreview(null);}}><option value="MAJA">MAJA</option><option value="CEMPLANG">CEMPLANG</option></select></label>
        <label>File bukti approval<input type="file" accept="application/pdf,image/jpeg,image/png,image/webp" onChange={e=>{const picked=e.currentTarget.files?.[0]||null;setProofFile(picked);setProofPreview(null);}} onInput={e=>{const picked=e.currentTarget.files?.[0]||null;setProofFile(picked);setProofPreview(null);}}/>{proofFile&&<small className="ops-file-ready">✓ File siap dibaca</small>}</label>
        <div className="ops-action-field"><span>Aksi</span><button type="button" onClick={e=>{e.preventDefault();readProof();}} disabled={proofBusy} aria-disabled={proofBusy}><FileSearch size={14}/> {proofBusy?"Membaca…":"Baca Semua Transaksi"}</button>{!proofFile&&<small className="ops-file-hint">Pilih file terlebih dahulu.</small>}</div>
      </div>
      {proofProgress&&<ReadProgress progress={proofProgress}/>}
      {proofPreview&&<div className="ops-parse-result">
        <div><CheckCircle2 size={16}/><strong>{proofPreview.transactionCount} transaksi · {proofPreview.matchedCount} cocok · {proofPreview.willApproveCount} akan menjadi PAID</strong></div>
        <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Referensi Bukti</th><th>Nilai</th><th>Status Bank</th><th>Maker Cocok</th><th>Hasil</th></tr></thead><tbody>{proofPreview.transactions.map((x,i)=><tr key={i}><td>{x.referenceNumber||"-"}</td><td>{money(x.amount)}</td><td>{x.status}</td><td>{x.matchedMakerId?`#${x.matchedMakerId} · ${x.matchedReference}`:"Tidak ditemukan"}</td><td>{x.willApprove?"APPROVE":"REVIEW / ABAIKAN"}</td></tr>)}</tbody></table></div>
        <div className="ops-row-actions"><button type="button" onClick={saveProof} disabled={proofBusy||!proofPreview.willApproveCount}><Upload size={14}/> Simpan Bukti & Tandai PAID {proofPreview.willApproveCount} Maker</button></div>
      </div>}
    </section>
  </>;
}
