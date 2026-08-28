import React, { useEffect, useMemo, useRef, useState } from "react";
import { ClipboardCopy, Download, ExternalLink, FileCheck2, FileSpreadsheet, MessageCircle, RefreshCw, Send, Stamp, Trash2, Upload, CheckCircle2 } from "lucide-react";
import { operationsApi } from "./apiClient";
import { accountantApi } from "./accountantApi.js";
import AccountantDocumentPanel from "./AccountantDocumentPanel.jsx";
import AccountantUnifiedCalendar from "./AccountantUnifiedCalendar.jsx";

const ACCOUNTANT_UNIFIED_CALENDAR_NATIVE = true;

const money = (v) => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(Number(v || 0));
const excelFilenameForDate = (value) => {
  const date = String(value || "").trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return "";
  return `${date.slice(8, 10)}-${date.slice(5, 7)}-${date.slice(0, 4)}.xlsx`;
};

async function copyText(text) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  const area = document.createElement("textarea");
  area.value = text; area.style.position = "fixed"; area.style.opacity = "0";
  document.body.appendChild(area); area.select(); document.execCommand("copy"); area.remove();
}

function planningLabel(row) {
  if (row?.source_plan_name) return row.source_plan_name;
  if (row?.source_planning_snapshot_id) return `Snapshot #${row.source_planning_snapshot_id}`;
  return row?.source_distribution_date || "-";
}

function accountantMessage(row) {
  return [
    `*SPPG ${row.site || "-"} — DATA AKUNTAN*`,
    `Akuntan: ${row.accountant_code || "-"}`,
    `Perencanaan: ${planningLabel(row)}`,
    `Status pengiriman: ${row.submission_status || "-"}`,
    `Tanggal kirim: ${row.sent_at || "-"}`,
    row.excel_evidence_uri ? `File Excel: ${row.excel_evidence_uri}` : "File Excel: link Drive belum tersedia",
    row.invoice_number ? `Invoice diterima: ${row.invoice_number} — ${money(row.invoice_amount)}` : "Invoice balasan: belum diterima",
    row.invoice_evidence_uri ? `File invoice: ${row.invoice_evidence_uri}` : null,
  ].filter(Boolean).join("\n");
}

function generatedExcelMessage(preview) {
  return [
    `*SPPG ${preview.site} — EXCEL AKUNTAN*`,
    `Akuntan: ${preview.accountantCode}`,
    `Tanggal distribusi: ${preview.distributionDate}`,
    preview.planName ? `Perencanaan: ${preview.planName}` : null,
    `File: ${preview.filename}`,
    `Item: ${preview.itemCount}`,
    `Grand Total Estimasi: ${money(preview.grandTotal)}`,
    preview.paguBgn == null ? null : `Pagu BGN: ${money(preview.paguBgn)}`,
    preview.paguMinusEstimate == null ? null : `Selisih Pagu - Estimasi: ${money(preview.paguMinusEstimate)}`,
    preview.driveUri ? `Link Excel: ${preview.driveUri}` : "Link Excel: belum tersedia",
  ].filter(Boolean).join("\n");
}

function pendingApprovalMessage(rows) {
  const pending = rows.filter((x) => String(x.approval_status || "PENDING").toUpperCase() !== "APPROVED");
  const lines = ["*REKAP PENDING APPROVAL BGN*", ""];
  pending.forEach((x, index) => lines.push(`${index + 1}. ${x.site} — ${x.reference_number || `Maker #${x.maker_id}`} — ${money(x.maker_amount)} — Approver: ${x.approver_code || "belum ditetapkan"} — Status: ${x.approval_status || "BELUM DIMINTA"}`));
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
  const [saving,setSaving]=useState("");
  const [excelSite,setExcelSite]=useState("MAJA");
  const [excelDate,setExcelDate]=useState(new Date().toISOString().slice(0,10));
  const [planOptions,setPlanOptions]=useState([]);
  const [selectedPlanId,setSelectedPlanId]=useState("");
  const [planBusy,setPlanBusy]=useState(false);
  const [planningError,setPlanningError]=useState("");
  const [excelPreview,setExcelPreview]=useState(null);
  const [excelBusy,setExcelBusy]=useState(false);
  const [invoiceFiles,setInvoiceFiles]=useState({});
  const [customFilename,setCustomFilename]=useState(()=>excelFilenameForDate(new Date().toISOString().slice(0,10)));
  const [calendarRefresh,setCalendarRefresh]=useState({ version: 0, site: "", invoiceDate: "" });
  const pendingExcelRef=useRef(null);

  const load=async(focus = null)=>{
    setLoading(true); setError("");
    try{
      // Excel/Invoice and BGN are separate lanes. A temporary BGN failure must
      // not make the ready Excel list look unavailable or block a new Excel.
      const [accountantResult,bgnResult]=await Promise.allSettled([operationsApi.getAccountantFlow(site),operationsApi.getBgnFlow(site)]);
      if(accountantResult.status==="fulfilled") setAccountant(accountantResult.value?.items||[]);
      if(bgnResult.status==="fulfilled") setBgn(bgnResult.value?.items||[]);
      if(accountantResult.status==="rejected") throw accountantResult.reason;
      if(bgnResult.status==="rejected") setMessage("Daftar Excel tetap dimuat. Riwayat Maker/BGN sedang tidak tersedia; silakan refresh lagi nanti.");
      setCalendarRefresh((value)=>({
        version: value.version + 1,
        site: focus?.site || "",
        invoiceDate: focus?.invoiceDate || "",
      }));
    }catch(e){setError(e.message||"Gagal mengambil daftar Excel akuntan");}
    finally{setLoading(false);}
  };
  useEffect(()=>{load();},[site]);

  const loadPlanningOptions = async () => {
    setPlanBusy(true); setPlanningError(""); setExcelPreview(null);
    try {
      const data = await accountantApi.getPlanningOptions({ site: excelSite, distributionDate: excelDate });
      const options = data?.items || [];
      setPlanOptions(options);
      setSelectedPlanId((current) => options.some((row) => row.documentId === current) ? current : options.length === 1 ? options[0].documentId : "");
      if (!options.length) setMessage(`Tidak ada perencanaan Kalkulator ${excelSite} untuk ${excelDate}.`);
      else if (options.length > 1) setMessage(`${options.length} perencanaan ditemukan. Pilih satu; Excel tidak menggabungkan perencanaan.`);
      else setMessage(`1 perencanaan ditemukan: ${options[0].planName}.`);
    } catch (e) {
      setPlanOptions([]); setSelectedPlanId("");
      const raw = String(e?.message || "");
      const failedDate = raw.match(/distributionDate[\\\"':]+(\d{4}-\d{2}-\d{2})/)?.[1] || excelDate;
      setPlanningError(`Perencanaan Kalkulator ${excelSite} tanggal ${failedDate} belum ditemukan. Fitur Invoice dan BGN tetap dapat digunakan.`);
    }
    finally { setPlanBusy(false); }
  };
  useEffect(()=>{ loadPlanningOptions(); },[excelSite,excelDate]);
  useEffect(()=>{ setCustomFilename(excelFilenameForDate(excelDate)); },[excelDate]);

  const pendingBgn = useMemo(() => bgn.filter((x) => String(x.approval_status || "PENDING").toUpperCase() !== "APPROVED"), [bgn]);
  const makerByInvoice = useMemo(() => {
    const map = new Map();
    bgn.forEach((x) => { if (x.accountant_invoice_id != null && !map.has(String(x.accountant_invoice_id))) map.set(String(x.accountant_invoice_id), x); });
    return map;
  }, [bgn]);
  const excelArgs = () => ({ site: excelSite, distributionDate: excelDate, calculatorDocumentId: selectedPlanId, customFilename });

  const previewExcel = async () => {
    if (!selectedPlanId) return setError(planOptions.length > 1 ? "Pilih salah satu perencanaan terlebih dahulu." : "Perencanaan belum tersedia.");
    setExcelBusy(true); setError(""); setMessage(""); setExcelPreview(null);
    try { setExcelPreview(await accountantApi.generateSelectedPlanExcel(excelArgs(), false)); }
    catch (e) { setError(e.message || "Gagal preview Excel akuntan"); }
    finally { setExcelBusy(false); }
  };

  const createExcel = async () => {
    if (!excelPreview || !selectedPlanId) return;
    if (!window.confirm(`Buat ulang Excel dari kondisi TERBARU perencanaan “${excelPreview.planName || selectedPlanId}” dan arsipkan ke Google Drive?`)) return;
    setExcelBusy(true); setError(""); setMessage("");
    try {
      const data = await accountantApi.generateSelectedPlanExcel(excelArgs(), true);
      setExcelPreview(data);
      setMessage(data.replacedPreviousExcel ? "Excel lama diganti dengan Excel baru dari perencanaan terbaru." : "Excel dibuat dan masuk Drive. Excel sekarang muncul di daftar Menunggu Invoice.");
      await load();
      window.setTimeout(() => pendingExcelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
    } catch (e) { setError(e.message || "Gagal membuat Excel akuntan"); }
    finally { setExcelBusy(false); }
  };

  const downloadExcel = async () => {
    if (!excelPreview?.downloadUrl) return;
    setExcelBusy(true); setError("");
    try {
      const file = await accountantApi.downloadSelectedPlanExcel({ downloadUrl: excelPreview.downloadUrl, filename: excelPreview.filename });
      const objectUrl = URL.createObjectURL(file.blob);
      const anchor = document.createElement("a"); anchor.href = objectUrl; anchor.download = file.filename; document.body.appendChild(anchor); anchor.click(); anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000); setMessage(`Excel ${file.filename} berhasil diunduh.`);
    } catch (e) { setError(e.message || "Gagal download Excel akuntan"); }
    finally { setExcelBusy(false); }
  };

  const markSent = async (row) => {
    if (!row.excel_evidence_uri && !row.generated_filename) return;
    if (!window.confirm(`Tandai Excel submission #${row.submission_id} benar-benar sudah dikirim ke ${row.accountant_code}?`)) return;
    setSaving(`sent-${row.submission_id}`); setError("");
    try { await operationsApi.markAccountantSubmissionSent(row.submission_id); setMessage(`Submission #${row.submission_id} ditandai SENT.`); await load(); }
    catch (e) { setError(e.message || "Gagal menandai Excel terkirim"); }
    finally { setSaving(""); }
  };

  const deleteFlow = async (row) => {
    const maker = row.invoice_id != null ? makerByInvoice.get(String(row.invoice_id)) : null;
    const detail = [`Excel submission #${row.submission_id}`, row.invoice_id ? `Invoice #${row.invoice_id}` : null, maker ? `Maker #${maker.maker_id} + approval pending` : null].filter(Boolean).join(" → ");
    if (!window.confirm(`HAPUS ALUR YANG SALAH?\n\n${detail}\n\nFile Excel/Invoice di Drive juga akan dicoba dihapus. Perencanaan Kalkulator, PO, receiving, stok dan transaksi keuangan TIDAK dihapus.`)) return;
    setSaving(`delete-${row.submission_id}`); setError(""); setMessage("");
    try {
      const result = await accountantApi.deleteSubmissionCascade(row.submission_id);
      setMessage(`Alur salah dihapus. Excel #${row.submission_id}, ${result.deletedInvoiceIds?.length||0} invoice, ${result.deletedMakerIds?.length||0} maker.`);
      await load();
      if (row.source_calculator_document_id === selectedPlanId) await previewExcel();
    } catch (e) { setError(e.message || "Gagal menghapus alur akuntan"); }
    finally { setSaving(""); }
  };

  const recordInvoice = async (row) => {
    if (row.invoice_id) return;
    const invoiceNumber = window.prompt(`Nomor invoice dari ${row.accountant_code} untuk ${row.site}:`, ""); if (invoiceNumber === null) return;
    const amountRaw = window.prompt("Nilai invoice (angka tanpa Rp):", ""); if (amountRaw === null) return;
    const amount = Number(String(amountRaw).replace(/[^0-9.-]/g, "")); if (!Number.isFinite(amount) || amount <= 0) return setError("Nilai invoice harus lebih dari 0.");
    if (!window.confirm(`Catat invoice ${invoiceNumber || "tanpa nomor"} sebesar ${money(amount)} untuk ${row.site}?`)) return;
    setSaving(`invoice-${row.submission_id}`); setError("");
    try { await operationsApi.createAccountantInvoice({ accountant_submission_id: row.submission_id, invoice_number: invoiceNumber.trim() || null, invoice_amount: amount, invoice_evidence_uri: null, received_at: null }); setMessage("Invoice akuntan tercatat."); await load(); }
    catch (e) { setError(e.message || "Gagal mencatat invoice akuntan"); }
    finally { setSaving(""); }
  };

  const uploadInvoice = async (row) => {
    const file = invoiceFiles[row.submission_id]; if (!file) return setError("Pilih file invoice PDF/JPG/PNG terlebih dahulu.");
    setSaving(`upload-invoice-${row.submission_id}`); setError("");
    try {
      const parsed = await accountantApi.previewInvoiceDocument({ file, site: row.site, category: "BAHAN_BAKU", submissionId: row.submission_id });
      const invoiceNumber = window.prompt("Nomor invoice (hasil baca dokumen, boleh dikoreksi):", parsed.invoiceNumber || row.invoice_number || ""); if (invoiceNumber === null) return;
      const invoiceDate = window.prompt("Tanggal invoice YYYY-MM-DD (hasil baca dokumen, boleh dikoreksi):", parsed.invoiceDate || row.source_distribution_date || ""); if (invoiceDate === null) return;
      const amountRaw = window.prompt("Nilai invoice (hasil baca dokumen, boleh dikoreksi):", parsed.invoiceAmount ? String(parsed.invoiceAmount) : (row.invoice_amount ? String(row.invoice_amount) : "")); if (amountRaw === null) return;
      const amount = Number(String(amountRaw).replace(/[^0-9.-]/g, "")); if (!Number.isFinite(amount) || amount <= 0) return setError("Nilai invoice harus lebih dari 0.");
      const corrected = { ...parsed, invoiceNumber: invoiceNumber.trim(), invoiceDate: invoiceDate.trim(), invoiceAmount: amount };
      if (!corrected.invoiceNumber || !/^\d{4}-\d{2}-\d{2}$/.test(corrected.invoiceDate)) return setError("Nomor dan tanggal invoice wajib valid.");
      if (!window.confirm(`Simpan invoice ${corrected.invoiceNumber} sebesar ${money(amount)} dan arsipkan di Drive? Maker dibuat terpisah setelah tombol Buat Maker diklik.`)) return;
      const result = await accountantApi.commitInvoiceDocument({ file, preview: corrected, site: row.site, category: "BAHAN_BAKU", submissionId: row.submission_id });
      setInvoiceFiles((current) => ({ ...current, [row.submission_id]: null }));
      setMessage(`${result.excelAutomaticallyMarkedSent ? "Excel otomatis ditandai SENT karena invoice sudah diterima. " : ""}Invoice #${result.accountantInvoiceId} tersimpan. Maker belum dibuat; klik invoice pada kalender lalu pilih Buat Maker.`); await load();
    }
    catch (e) { setError(e.message || "Gagal upload invoice akuntan"); }
    finally { setSaving(""); }
  };

  const createMakerAndApproval = async (row) => {
    if (!row.invoice_id || Number(row.invoice_amount || 0) <= 0) return;
    if (makerByInvoice.has(String(row.invoice_id))) return setError("Maker untuk invoice ini sudah ada.");
    if (!window.confirm(`Buat Maker BGN dari invoice ${row.invoice_number || `#${row.invoice_id}`} sebesar ${money(row.invoice_amount)}?`)) return;
    setSaving(`maker-${row.invoice_id}`); setError("");
    try { const result = await accountantApi.createMakerFromInvoice(row.invoice_id); setMessage(`Maker #${result.makerId} dibuat. Approval ${result.approvalStatus || "PENDING"} diarahkan ke ${result.approverCode || "approver site"}.`); await load(); }
    catch (e) { setError(e.message || "Gagal membuat maker/approval"); }
    finally { setSaving(""); }
  };

  const approveMaker = async (row) => {
    if (String(row.approval_status||"").toUpperCase()==="APPROVED") return;
    if (!window.confirm(`Konfirmasi Maker #${row.maker_id} (${row.reference_number||"tanpa referensi"}) SUDAH APPROVE?`)) return;
    setSaving(`approve-${row.maker_id}`); setError("");
    try { await accountantApi.confirmMakerApproved(row.maker_id, true); setMessage(`Maker #${row.maker_id} ditandai APPROVED.`); await load(); }
    catch (e) { setError(e.message || "Gagal konfirmasi approval Maker"); }
    finally { setSaving(""); }
  };

  const cancelMakerApproval = async (row) => {
    if (String(row.approval_status||"").toUpperCase()!=="APPROVED") return;
    if (Boolean(row.receipt_id)||String(row.maker_status||"").toUpperCase()==="PAID") return setError("Approval tidak bisa dibatalkan karena Maker sudah PAID.");
    if (!window.confirm(`Batalkan status APPROVED Maker #${row.maker_id}? Maker akan kembali ke PENDING.`)) return;
    setSaving(`cancel-approve-${row.maker_id}`); setError("");
    try { await accountantApi.cancelMakerApproval(row.maker_id); setMessage(`Approval Maker #${row.maker_id} dibatalkan dan kembali PENDING.`); await load(); }
    catch (e) { setError(e.message || "Gagal membatalkan approval Maker"); }
    finally { setSaving(""); }
  };

  const cancelMaker = async (row) => {
    const makerId = row?.maker_id;
    if (!makerId) return;
    const linked = makerByInvoice.get(String(row.invoice_id));
    const approvalStatus = String(linked?.approval_status || row?.approval_status || "PENDING").toUpperCase();
    const makerStatus = String(linked?.maker_status || row?.maker_status || "").toUpperCase();
    if (approvalStatus === "APPROVED") return setError("Maker sudah APPROVED. Batalkan approval terlebih dahulu sebelum membatalkan Maker.");
    if (makerStatus === "PAID" || linked?.receipt_id) return setError("Maker tidak dapat dibatalkan karena sudah PAID.");
    if (!window.confirm(`Batalkan Maker #${makerId}? Approval pending ikut dihapus, tetapi invoice dan Excel Akuntan tetap tersimpan.`)) return;
    setSaving(`cancel-maker-${makerId}`); setError("");
    try { await accountantApi.cancelMaker(makerId); setMessage(`Maker #${makerId} dibatalkan. Invoice tetap tersimpan dan dapat dibuatkan Maker lagi setelah dikoreksi.`); await load(); }
    catch (e) { setError(e.message || "Gagal membatalkan Maker"); }
    finally { setSaving(""); }
  };

  return <div className="ops-domain-stack">
    {error&&<div className="ops-error">{error}</div>}{message&&<div className="ops-success">{message}</div>}
    <AccountantDocumentPanel onChanged={load} reportError={setError} reportMessage={setMessage}/>
    <AccountantUnifiedCalendar refreshToken={calendarRefresh} onChanged={load} reportError={setError} reportMessage={setMessage}/>
    <section className="ops-module">
      <div className="ops-module-header"><div><span className="ops-kicker">KALKULATOR → EXCEL AKUNTAN</span><h3>Excel Belanja per Perencanaan</h3><p>Preview dan pembuatan Excel selalu membaca ulang dokumen perencanaan terbaru. File lama tidak boleh dipakai diam-diam setelah perencanaan berubah.</p></div></div>
      {planningError&&<div className="ops-notice">{planningError}</div>}
      <div className="ops-form-grid">
        <label>Site<select value={excelSite} onChange={e=>{setExcelSite(e.target.value);setExcelPreview(null);setSelectedPlanId("");}}><option value="MAJA">Maja → Tiara</option><option value="CEMPLANG">Cemplang → Uya</option></select></label>
        <label>Tanggal Distribusi<input type="date" value={excelDate} onChange={e=>{setExcelDate(e.target.value);setExcelPreview(null);setSelectedPlanId("");}}/></label>
        <label>Perencanaan<select value={selectedPlanId} onChange={e=>{setSelectedPlanId(e.target.value);setExcelPreview(null);}} disabled={planBusy||!planOptions.length}><option value="">{planBusy?"Menarik perencanaan…":planOptions.length>1?`Pilih 1 dari ${planOptions.length} perencanaan`:"Pilih perencanaan"}</option>{planOptions.map(row=><option key={row.documentId} value={row.documentId}>{row.planName} · {row.itemCount} item · {row.updatedAt ? String(row.updatedAt).replace("T"," ").slice(0,16) : "-"}</option>)}</select></label>
        <label>Nama file Excel<input value={customFilename} onChange={e=>{setCustomFilename(e.target.value);setExcelPreview(null);}} placeholder="dd-mm-yyyy.xlsx"/><span className="ops-muted">Otomatis dari tanggal distribusi; boleh dikoreksi bila diperlukan.</span></label>
        <label>Aksi<div className="ops-row-actions"><button type="button" onClick={loadPlanningOptions} disabled={planBusy}><RefreshCw size={14}/> {planBusy?"Menarik…":"Tarik Ulang Perencanaan"}</button><button type="button" onClick={previewExcel} disabled={excelBusy||!selectedPlanId}><FileSpreadsheet size={14}/> {excelBusy?"Memproses...":"Preview Terbaru"}</button></div></label>
      </div>
      {planOptions.length>1&&<div className="ops-notice"><strong>{planOptions.length} perencanaan pada {excelDate}.</strong> Pilih satu. Data tidak digabung.</div>}
      {excelPreview&&<div className="ops-parse-result">
        <div><FileSpreadsheet size={16}/><strong>Preview Excel Akuntan</strong></div>
        {excelPreview.sourceChangedSinceLastExcel&&<div className="ops-error"><strong>Perencanaan berubah.</strong> Excel lama tidak lagi dianggap sumber terbaru. Buat ulang dari preview ini.</div>}
        <div className="ops-summary-strip"><span>Akuntan <strong>{excelPreview.accountantCode}</strong></span><span>Perencanaan <strong>{excelPreview.planName||"-"}</strong></span><span>Item <strong>{excelPreview.itemCount}</strong></span><span>Grand Total <strong>{money(excelPreview.grandTotal)}</strong></span>{excelPreview.paguBgn!=null&&<span>Pagu BGN <strong>{money(excelPreview.paguBgn)}</strong></span>}<span>Status <strong>{excelPreview.status||"PREVIEW"}</strong></span></div>
        <div className="ops-muted">Sumber Kalkulator: {excelPreview.sourceUpdatedAt||"-"} · Document ID: {excelPreview.calculatorDocumentId}</div>
        <div className="ops-muted">File: {excelPreview.filename}</div>
        <div className="ops-row-actions">
          <button type="button" onClick={createExcel} disabled={excelBusy}><FileSpreadsheet size={14}/> {excelPreview.existingSubmissionId?"Buat / Ganti Excel dari Data Terbaru":"Buat Excel & Arsip Drive"}</button>
          {excelPreview.driveUri&&<button type="button" onClick={()=>window.open(excelPreview.driveUri,"_blank","noopener,noreferrer")}><ExternalLink size={14}/> Buka Excel Drive</button>}
          {excelPreview.downloadUrl&&<button type="button" onClick={downloadExcel} disabled={excelBusy}><Download size={14}/> Download Preview Terbaru</button>}
          <button type="button" onClick={async()=>{await copyText(generatedExcelMessage(excelPreview));setMessage("Pesan Excel akuntan sudah disalin.");}}><ClipboardCopy size={14}/> Copy Pesan</button>
          <button type="button" onClick={()=>window.open(`https://wa.me/?text=${encodeURIComponent(generatedExcelMessage(excelPreview))}`,"_blank","noopener,noreferrer")}><MessageCircle size={14}/> WhatsApp</button>
        </div>
      </div>}
    </section>

    <section className="ops-module" ref={pendingExcelRef}>
      <div className="ops-module-header"><div><span className="ops-kicker">EXCEL MENUNGGU INVOICE</span><h3>Excel yang Belum Dibalas Akuntan</h3><p>Excel yang berhasil diarsipkan langsung tampil di sini bersama link Drive. Upload invoice dari baris yang sama; tombol Maker baru aktif setelah invoice tersimpan.</p></div></div>
      {error&&<div className="ops-error">{error}</div>}{message&&<div className="ops-success">{message}</div>}
      <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Site</th><th>Perencanaan</th><th>Akuntan</th><th>Excel</th><th>Status</th><th>Invoice</th><th>File Invoice</th><th>Maker</th><th>Aksi</th></tr></thead><tbody>{accountant.filter((x)=>!x.invoice_id).map(x=>{
        const linkedMaker = x.invoice_id != null ? makerByInvoice.get(String(x.invoice_id)) : null;
        const existingMaker = x.maker_id
          ? { ...linkedMaker, maker_id: x.maker_id, maker_status: x.maker_status || linkedMaker?.maker_status }
          : linkedMaker;
        const sent = String(x.submission_status||"").toUpperCase()==="SENT";
        const excelReady = Boolean(x.excel_evidence_uri) && String(x.drive_upload_status||"").toUpperCase() !== "FAILED";
        const makerState = existingMaker ? (String(existingMaker.receipt_id || existingMaker.maker_status || "").toUpperCase()==="PAID" ? "paid" : String(existingMaker.approval_status || "").toUpperCase()==="APPROVED" || String(existingMaker.maker_status || "").toUpperCase()==="APPROVED" ? "approved" : "pending") : "";
        const makerLabel = makerState === "paid" ? "PAID" : makerState === "approved" ? "APPROVED" : "PENDING";
        return <tr className={makerState ? `ops-accountant-row-${makerState}` : ""} key={`${x.submission_id}-${x.invoice_id||0}`}><td>{x.site}</td><td><strong>{planningLabel(x)}</strong><div className="ops-muted">{x.source_distribution_date||"-"}{x.source_calculator_document_id?` · ${x.source_calculator_document_id}`:""}</div></td><td>{x.accountant_code}</td><td>{x.excel_evidence_uri?<button type="button" onClick={()=>window.open(x.excel_evidence_uri,"_blank","noopener,noreferrer")}><ExternalLink size={14}/> Buka Excel</button>:<span className="ops-muted">{x.generated_filename||"Belum ada file"}<br/>{x.drive_upload_status||""}</span>}</td><td><strong>{sent ? "SENT" : excelReady ? "BELUM DITANDAI TERKIRIM" : (x.submission_status||"-")}</strong><div className="ops-muted">{sent ? (x.sent_at||"-") : excelReady ? "Upload invoice akan otomatis menandai SENT" : (x.drive_upload_status||"Belum ada file")}</div></td><td>{x.invoice_id?<><strong>{x.invoice_number||`#${x.invoice_id}`}</strong><div>{money(x.invoice_amount)}</div></>:"-"}</td><td>{x.invoice_evidence_uri?<button type="button" onClick={()=>window.open(x.invoice_evidence_uri,"_blank","noopener,noreferrer")}><ExternalLink size={14}/> Buka Invoice</button>:excelReady?<div><input type="file" accept="application/pdf,image/jpeg,image/png,image/webp" onChange={e=>setInvoiceFiles(current=>({...current,[x.submission_id]:e.target.files?.[0]||null}))}/><div className="ops-muted">Invoice diterima = Excel otomatis dianggap terkirim.</div></div>:<span className="ops-muted">Excel belum berhasil diarsipkan</span>}</td><td>{existingMaker?<span className={`ops-maker-chip ${makerState}`}>✓ Maker #{existingMaker.maker_id}<small>{makerLabel}</small></span>:"-"}</td><td><div className="ops-row-actions">
          <button type="button" onClick={async()=>{await copyText(accountantMessage(x));setMessage("Pesan akuntan sudah disalin.");}}><ClipboardCopy size={14}/> Copy</button>
          <button type="button" onClick={()=>window.open(`https://wa.me/?text=${encodeURIComponent(accountantMessage(x))}`,"_blank","noopener,noreferrer")}><MessageCircle size={14}/> WhatsApp</button>
          {!sent&&(x.excel_evidence_uri||x.generated_filename)&&<button type="button" onClick={()=>markSent(x)} disabled={saving===`sent-${x.submission_id}`}><Send size={14}/> Tandai Terkirim</button>}
          {excelReady&&!x.invoice_id&&<button type="button" onClick={()=>recordInvoice(x)} disabled={saving===`invoice-${x.submission_id}`}><FileCheck2 size={14}/> Catat Invoice</button>}
          {excelReady&&!x.invoice_evidence_uri&&<button type="button" onClick={()=>uploadInvoice(x)} disabled={saving===`upload-invoice-${x.submission_id}`||!invoiceFiles[x.submission_id]} title={sent?"Upload invoice bahan baku":"Upload invoice dan tandai Excel sebagai SENT"}><Upload size={14}/> {sent?"Upload Invoice":"Upload Invoice + SENT"}</button>}
          {x.invoice_id&&Number(x.invoice_amount||0)>0&&<button type="button" className={existingMaker ? "ops-maker-created-button" : ""} onClick={()=>!existingMaker&&createMakerAndApproval(x)} disabled={Boolean(existingMaker)||saving===`maker-${x.invoice_id}`}><Stamp size={14}/> {existingMaker ? `Maker #${existingMaker.maker_id} dibuat` : "Buat Maker"}</button>}
          {existingMaker&&makerState==="pending"&&<button type="button" className="danger" onClick={()=>cancelMaker({ ...x, ...existingMaker })} disabled={saving===`cancel-maker-${existingMaker.maker_id}`}><Trash2 size={14}/> Batalkan Maker</button>}
          <button type="button" className="danger" onClick={()=>deleteFlow(x)} disabled={saving===`delete-${x.submission_id}`} title="Hapus alur yang salah"><Trash2 size={14}/> Hapus Alur</button>
        </div></td></tr>;
      })}{!loading&&!accountant.some((x)=>!x.invoice_id)&&<tr><td colSpan="9" className="ops-empty-cell">Semua submission pada filter ini sudah memiliki invoice atau belum ada submission.</td></tr>}</tbody></table></div>
    </section>

    <details className="ops-module">
      <summary className="ops-module-header" style={{cursor:"pointer"}}><div><span className="ops-kicker">BGN</span><h3>Riwayat Maker / Approval / Paid</h3><p>Pengelolaan harian dilakukan pada Kalender / List agar semua kategori ada dalam satu tempat.</p></div></summary><div className="ops-row-actions" style={{margin:"0 0 12px"}}><button type="button" onClick={async()=>{await copyText(pendingApprovalMessage(bgn));setMessage("Rekap pending approval sudah disalin.");}}><ClipboardCopy size={14}/> Copy Pending ({pendingBgn.length})</button><button type="button" onClick={()=>window.open(`https://wa.me/?text=${encodeURIComponent(pendingApprovalMessage(bgn))}`,"_blank","noopener,noreferrer")}><MessageCircle size={14}/> WhatsApp Pending</button></div>
      <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Site</th><th>Maker</th><th>Invoice</th><th>Referensi</th><th>Nilai</th><th>Maker Status</th><th>Approver</th><th>Approval</th><th>Approved</th><th>Pembayaran</th><th>Bukti</th><th>Aksi</th></tr></thead><tbody>{bgn.map(x=>{
        const approved=String(x.approval_status||"").toUpperCase()==="APPROVED";
        const paid=Boolean(x.receipt_id)||String(x.maker_status||"").toUpperCase()==="PAID";
        return <tr className={paid ? "ops-accountant-row-paid" : ""} key={x.maker_id}><td>{x.site}</td><td>#{x.maker_id}</td><td>{x.accountant_invoice_id?`#${x.accountant_invoice_id}`:"-"}</td><td>{x.reference_number||"-"}</td><td>{money(x.maker_amount)}</td><td><strong>{paid ? "PAID" : x.maker_status}</strong></td><td>{x.approver_code||"-"}</td><td>{approved?<strong>APPROVED</strong>:(x.approval_status||"PENDING")}</td><td>{x.approved_at||"-"}</td><td>{paid?<><strong>PAID</strong><div className="ops-muted">{x.payment_received_at||x.approved_at||""}</div></>:"PENDING APPROVAL"}</td><td>{x.payment_evidence_uri?<button type="button" onClick={()=>window.open(x.payment_evidence_uri,"_blank","noopener,noreferrer")}><ExternalLink size={14}/> Buka Bukti</button>:paid?<span className="ops-muted">Tanpa file</span>:<span className="ops-muted">Opsional di kalender</span>}</td><td><div className="ops-row-actions">
          {!approved&&<button type="button" onClick={()=>approveMaker(x)} disabled={saving===`approve-${x.maker_id}`}><CheckCircle2 size={14}/> Sudah Approve</button>}
          {approved&&!paid&&<button type="button" className="danger" onClick={()=>cancelMakerApproval(x)} disabled={saving===`cancel-approve-${x.maker_id}`}><Trash2 size={14}/> Batal Approve</button>}
          {paid&&<span className="ops-success" style={{padding:"4px 8px"}}>✓ Selesai</span>}
        </div></td></tr>;
      })}{!loading&&bgn.length===0&&<tr><td colSpan="12" className="ops-empty-cell">Belum ada maker BGN.</td></tr>}</tbody></table></div>
    </details>
  </div>;
}
