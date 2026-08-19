import React, { useEffect, useMemo, useState } from "react";
import { ClipboardCopy, Download, ExternalLink, FileCheck2, FileSpreadsheet, MessageCircle, RefreshCw, Send, Stamp, Upload } from "lucide-react";
import { operationsApi } from "./apiClient";
import { accountantApi, absoluteAccountantUrl } from "./accountantApi.js";

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
  const [saving,setSaving]=useState("");

  const [excelSite,setExcelSite]=useState("MAJA");
  const [excelDate,setExcelDate]=useState(new Date().toISOString().slice(0,10));
  const [planOptions,setPlanOptions]=useState([]);
  const [selectedPlanId,setSelectedPlanId]=useState("");
  const [planBusy,setPlanBusy]=useState(false);
  const [excelPreview,setExcelPreview]=useState(null);
  const [excelBusy,setExcelBusy]=useState(false);
  const [invoiceFiles,setInvoiceFiles]=useState({});

  const load=async()=>{
    setLoading(true); setError("");
    try{
      const [a,b]=await Promise.all([operationsApi.getAccountantFlow(site),operationsApi.getBgnFlow(site)]);
      setAccountant(a?.items||[]); setBgn(b?.items||[]);
    }catch(e){setError(e.message||"Gagal mengambil alur akuntan/BGN");}
    finally{setLoading(false);}
  };
  useEffect(()=>{load();},[site]);

  const loadPlanningOptions = async () => {
    setPlanBusy(true); setError(""); setExcelPreview(null);
    try {
      const data = await accountantApi.getPlanningOptions({ site: excelSite, distributionDate: excelDate });
      const options = data?.items || [];
      setPlanOptions(options);
      setSelectedPlanId((current) => {
        if (options.some((row) => row.documentId === current)) return current;
        return options.length === 1 ? options[0].documentId : "";
      });
      if (!options.length) setMessage(`Tidak ada perencanaan Kalkulator ${excelSite} untuk ${excelDate}.`);
      else if (options.length > 1) setMessage(`${options.length} perencanaan ditemukan. Pilih satu; Excel tidak akan menggabungkan perencanaan.`);
      else setMessage(`1 perencanaan ditemukan: ${options[0].planName}.`);
    } catch (e) {
      setPlanOptions([]); setSelectedPlanId("");
      setError(e.message || "Gagal menarik daftar perencanaan Kalkulator");
    } finally {
      setPlanBusy(false);
    }
  };

  useEffect(()=>{ loadPlanningOptions(); },[excelSite,excelDate]);

  const pendingBgn = useMemo(
    () => bgn.filter((x) => String(x.approval_status || "PENDING").toUpperCase() !== "APPROVED"),
    [bgn],
  );

  const makerByInvoice = useMemo(() => {
    const map = new Map();
    bgn.forEach((x) => {
      if (x.accountant_invoice_id != null && !map.has(String(x.accountant_invoice_id))) map.set(String(x.accountant_invoice_id), x);
    });
    return map;
  }, [bgn]);

  const previewExcel = async () => {
    if (!selectedPlanId) {
      setError(planOptions.length > 1 ? "Pilih salah satu perencanaan terlebih dahulu." : "Perencanaan belum tersedia.");
      return;
    }
    setExcelBusy(true); setError(""); setMessage(""); setExcelPreview(null);
    try {
      const data = await accountantApi.generateSelectedPlanExcel({
        site: excelSite,
        distributionDate: excelDate,
        calculatorDocumentId: selectedPlanId,
      }, false);
      setExcelPreview(data);
    } catch (e) {
      setError(e.message || "Gagal preview Excel akuntan");
    } finally {
      setExcelBusy(false);
    }
  };

  const createExcel = async () => {
    if (!excelPreview || !selectedPlanId) return;
    const confirmed = window.confirm(
      `Buat file ${excelPreview.filename} dari perencanaan “${excelPreview.planName || selectedPlanId}” dan arsipkan ke Google Drive?\n\nHanya perencanaan ini yang ditarik; perencanaan lain di tanggal yang sama tidak digabung.`
    );
    if (!confirmed) return;
    setExcelBusy(true); setError(""); setMessage("");
    try {
      const data = await accountantApi.generateSelectedPlanExcel({
        site: excelSite,
        distributionDate: excelDate,
        calculatorDocumentId: selectedPlanId,
      }, true);
      setExcelPreview(data);
      if (data.driveUri) {
        setMessage(data.duplicate ? "Excel perencanaan ini sudah ada; file Drive yang sama ditampilkan." : "Excel dibuat dan masuk ke folder Drive akuntan. Status READY sampai benar-benar dikirim.");
      } else {
        setMessage("Excel sudah siap tetapi upload Drive gagal. File tetap bisa diunduh dan upload dapat dicoba lagi.");
      }
      await load();
    } catch (e) {
      setError(e.message || "Gagal membuat Excel akuntan");
    } finally {
      setExcelBusy(false);
    }
  };

  const copyGeneratedExcel = async () => {
    if (!excelPreview) return;
    await copyText(generatedExcelMessage(excelPreview));
    setMessage("Pesan Excel akuntan sudah disalin.");
  };

  const waGeneratedExcel = () => {
    if (!excelPreview) return;
    window.open(`https://wa.me/?text=${encodeURIComponent(generatedExcelMessage(excelPreview))}`, "_blank", "noopener,noreferrer");
    setMessage(`WhatsApp dibuka. Pilih ${excelPreview.accountantCode} yang benar sebelum kirim.`);
  };

  const markSent = async (row) => {
    if (!row.excel_evidence_uri && !row.generated_filename) return;
    if (!window.confirm(`Tandai Excel submission #${row.submission_id} benar-benar sudah dikirim ke ${row.accountant_code}?`)) return;
    setSaving(`sent-${row.submission_id}`); setError(""); setMessage("");
    try {
      await operationsApi.markAccountantSubmissionSent(row.submission_id);
      setMessage(`Submission #${row.submission_id} ditandai SENT.`);
      await load();
    } catch (e) {
      setError(e.message || "Gagal menandai Excel terkirim");
    } finally {
      setSaving("");
    }
  };

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
    setMessage("WhatsApp dibuka dengan rekap pending approval.");
  };

  const recordInvoice = async (row) => {
    if (row.invoice_id) return;
    const invoiceNumber = window.prompt(`Nomor invoice dari ${row.accountant_code} untuk ${row.site}:`, "");
    if (invoiceNumber === null) return;
    const amountRaw = window.prompt("Nilai invoice (angka tanpa Rp):", "");
    if (amountRaw === null) return;
    const amount = Number(String(amountRaw).replace(/[^0-9.-]/g, ""));
    if (!Number.isFinite(amount) || amount <= 0) {
      setError("Nilai invoice harus lebih dari 0.");
      return;
    }
    if (!window.confirm(`Catat invoice ${invoiceNumber || "tanpa nomor"} sebesar ${money(amount)} untuk ${row.site}?`)) return;

    setSaving(`invoice-${row.submission_id}`); setError(""); setMessage("");
    try {
      await operationsApi.createAccountantInvoice({
        accountant_submission_id: row.submission_id,
        invoice_number: invoiceNumber.trim() || null,
        invoice_amount: amount,
        invoice_evidence_uri: null,
        received_at: null,
      });
      setMessage("Invoice akuntan tercatat. File invoice masih bisa diunggah setelahnya.");
      await load();
    } catch (e) {
      setError(e.message || "Gagal mencatat invoice akuntan");
    } finally {
      setSaving("");
    }
  };

  const uploadInvoice = async (row) => {
    const file = invoiceFiles[row.submission_id];
    if (!file) {
      setError("Pilih file invoice PDF/JPG/PNG terlebih dahulu.");
      return;
    }
    const invoiceNumber = window.prompt("Nomor invoice:", row.invoice_number || "");
    if (invoiceNumber === null) return;
    const amountRaw = window.prompt("Nilai invoice (angka tanpa Rp):", row.invoice_amount ? String(row.invoice_amount) : "");
    if (amountRaw === null) return;
    const amount = Number(String(amountRaw).replace(/[^0-9.-]/g, ""));
    if (!Number.isFinite(amount) || amount <= 0) {
      setError("Nilai invoice harus lebih dari 0.");
      return;
    }
    setSaving(`upload-invoice-${row.submission_id}`); setError(""); setMessage("");
    try {
      const result = await accountantApi.uploadInvoice({
        submissionId: row.submission_id,
        file,
        invoiceNumber: invoiceNumber.trim() || null,
        invoiceAmount: amount,
      });
      setInvoiceFiles((current) => ({ ...current, [row.submission_id]: null }));
      setMessage(`Invoice #${result.accountantInvoiceId} tersimpan dan file masuk Drive.`);
      await load();
    } catch (e) {
      setError(e.message || "Gagal upload invoice akuntan");
    } finally {
      setSaving("");
    }
  };

  const createMakerAndApproval = async (row) => {
    if (!row.invoice_id || Number(row.invoice_amount || 0) <= 0) return;
    if (makerByInvoice.has(String(row.invoice_id))) {
      setError("Maker untuk invoice ini sudah ada.");
      return;
    }
    if (!window.confirm(`Buat Maker BGN dari invoice ${row.invoice_number || `#${row.invoice_id}`} sebesar ${money(row.invoice_amount)}?`)) return;
    setSaving(`maker-${row.invoice_id}`); setError(""); setMessage("");
    try {
      const result = await accountantApi.createMakerFromInvoice(row.invoice_id);
      setMessage(`Maker #${result.makerId} dibuat. Approval ${result.approvalStatus || "PENDING"} diarahkan ke ${result.approverCode || "approver site"}.`);
      await load();
    } catch (e) {
      setError(e.message || "Gagal membuat maker/approval");
    } finally {
      setSaving("");
    }
  };

  return <div className="ops-domain-stack">
    <section className="ops-module">
      <div className="ops-module-header">
        <div><span className="ops-kicker">KALKULATOR → EXCEL AKUNTAN</span><h3>Excel Belanja per Perencanaan</h3><p>Satu Excel hanya berasal dari satu perencanaan Kalkulator. Bila tanggal yang sama memiliki 2 atau lebih perencanaan, pilih perencanaan yang ingin dikirim; qty tidak digabung antar-perencanaan.</p></div>
      </div>
      <div className="ops-form-grid">
        <label>Site<select value={excelSite} onChange={e=>{setExcelSite(e.target.value);setExcelPreview(null);setSelectedPlanId("");}}><option value="MAJA">Maja → Tiara</option><option value="CEMPLANG">Cemplang → Uya</option></select></label>
        <label>Tanggal Distribusi<input type="date" value={excelDate} onChange={e=>{setExcelDate(e.target.value);setExcelPreview(null);setSelectedPlanId("");}}/></label>
        <label>Perencanaan<select value={selectedPlanId} onChange={e=>{setSelectedPlanId(e.target.value);setExcelPreview(null);}} disabled={planBusy||!planOptions.length}><option value="">{planBusy?"Menarik perencanaan…":planOptions.length>1?`Pilih 1 dari ${planOptions.length} perencanaan`:"Pilih perencanaan"}</option>{planOptions.map(row=><option key={row.documentId} value={row.documentId}>{row.planName} · {row.itemCount} item · {row.updatedAt ? String(row.updatedAt).replace("T"," ").slice(0,16) : "-"}</option>)}</select></label>
        <label>Aksi<div className="ops-row-actions"><button type="button" onClick={loadPlanningOptions} disabled={planBusy}><RefreshCw size={14}/> {planBusy?"Menarik…":"Tarik Perencanaan"}</button><button type="button" onClick={previewExcel} disabled={excelBusy||!selectedPlanId}><FileSpreadsheet size={14}/> {excelBusy?"Memproses...":"Preview Excel"}</button></div></label>
      </div>
      {planOptions.length>1&&<div className="ops-notice"><strong>{planOptions.length} perencanaan pada {excelDate}.</strong> Pilihan wajib supaya Excel tidak menggabungkan data.</div>}
      {excelPreview&&<div className="ops-parse-result">
        <div><FileSpreadsheet size={16}/><strong>Preview Excel Akuntan</strong></div>
        <div className="ops-summary-strip">
          <span>Akuntan <strong>{excelPreview.accountantCode}</strong></span>
          <span>Perencanaan <strong>{excelPreview.planName||"-"}</strong></span>
          <span>Item <strong>{excelPreview.itemCount}</strong></span>
          <span>Grand Total <strong>{money(excelPreview.grandTotal)}</strong></span>
          {excelPreview.paguBgn!=null&&<span>Pagu BGN <strong>{money(excelPreview.paguBgn)}</strong></span>}
          {excelPreview.paguMinusEstimate!=null&&<span>Selisih <strong>{money(excelPreview.paguMinusEstimate)}</strong></span>}
          <span>Status <strong>{excelPreview.status||"PREVIEW"}</strong></span>
          {excelPreview.driveUploadStatus&&<span>Drive <strong>{excelPreview.driveUploadStatus}</strong></span>}
        </div>
        <div className="ops-muted">File: {excelPreview.filename} · Document ID: {excelPreview.calculatorDocumentId}</div>
        {excelPreview.driveUploadError&&<div className="ops-error"><strong>Upload Drive gagal:</strong> {excelPreview.driveUploadError}</div>}
        <div className="ops-row-actions">
          {!excelPreview.driveUri&&<button type="button" onClick={createExcel} disabled={excelBusy}><FileSpreadsheet size={14}/> {excelPreview.retryable?"Coba Upload Drive Lagi":"Buat Excel & Arsip Drive"}</button>}
          {excelPreview.driveUri&&<button type="button" onClick={()=>window.open(excelPreview.driveUri,"_blank","noopener,noreferrer")}><ExternalLink size={14}/> Buka Excel Drive</button>}
          {excelPreview.downloadUrl&&<button type="button" onClick={()=>window.open(absoluteAccountantUrl(excelPreview.downloadUrl),"_blank","noopener,noreferrer")}><Download size={14}/> Download Excel</button>}
          <button type="button" onClick={copyGeneratedExcel}><ClipboardCopy size={14}/> Copy Pesan</button>
          <button type="button" onClick={waGeneratedExcel}><MessageCircle size={14}/> WhatsApp</button>
        </div>
        <div className="ops-muted">READY = Excel tersedia. SENT hanya setelah file benar-benar dikirim ke akuntan.</div>
      </div>}
    </section>

    <section className="ops-module">
      <div className="ops-module-header">
        <div><span className="ops-kicker">ACCOUNTANT</span><h3>Excel → Invoice Akuntan → Maker</h3><p>Maja → Tiara · Cemplang → Uya. Setelah Excel dikirim dan ditandai SENT, invoice balasan dapat dicatat atau diunggah ke Drive. Maker dibuat per invoice, bukan sekadar per tanggal.</p></div>
        <div className="ops-inline-controls"><select value={site} onChange={e=>setSite(e.target.value)}><option value="">Semua site</option><option value="MAJA">Maja</option><option value="CEMPLANG">Cemplang</option></select><button onClick={load} disabled={loading}><RefreshCw size={15}/> Refresh</button></div>
      </div>
      {error&&<div className="ops-error">{error}</div>}
      {message&&<div className="ops-success">{message}</div>}
      <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Site</th><th>Perencanaan</th><th>Akuntan</th><th>Excel</th><th>Status</th><th>Invoice</th><th>File Invoice</th><th>Maker</th><th>Aksi</th></tr></thead><tbody>{accountant.map(x=>{
        const existingMaker = x.invoice_id != null ? makerByInvoice.get(String(x.invoice_id)) : null;
        const sent = String(x.submission_status||"").toUpperCase()==="SENT";
        return <tr key={`${x.submission_id}-${x.invoice_id||0}`}><td>{x.site}</td><td><strong>{planningLabel(x)}</strong><div className="ops-muted">{x.source_distribution_date||"-"}{x.source_calculator_document_id?` · ${x.source_calculator_document_id}`:""}</div></td><td>{x.accountant_code}</td><td>{x.excel_evidence_uri?<button type="button" onClick={()=>window.open(x.excel_evidence_uri,"_blank","noopener,noreferrer")}><ExternalLink size={14}/> Buka Excel</button>:<span className="ops-muted">{x.generated_filename||"Belum ada file"}<br/>{x.drive_upload_status||""}</span>}</td><td>{x.submission_status}<div className="ops-muted">{x.sent_at||"-"}</div></td><td>{x.invoice_id?<><strong>{x.invoice_number||`#${x.invoice_id}`}</strong><div>{money(x.invoice_amount)}</div></>:"-"}</td><td>{x.invoice_evidence_uri?<button type="button" onClick={()=>window.open(x.invoice_evidence_uri,"_blank","noopener,noreferrer")}><ExternalLink size={14}/> Buka Invoice</button>:sent?<div><input type="file" accept="application/pdf,image/jpeg,image/png,image/webp" onChange={e=>setInvoiceFiles(current=>({...current,[x.submission_id]:e.target.files?.[0]||null}))}/>{invoiceFiles[x.submission_id]&&<div className="ops-muted">{invoiceFiles[x.submission_id].name}</div>}</div>:<span className="ops-muted">Tandai SENT dulu</span>}</td><td>{existingMaker?`#${existingMaker.maker_id}`:"-"}</td><td><div className="ops-row-actions">
          <button type="button" onClick={()=>copyAccountant(x)}><ClipboardCopy size={14}/> Copy</button>
          <button type="button" onClick={()=>waAccountant(x)}><MessageCircle size={14}/> WhatsApp</button>
          {!sent&&(x.excel_evidence_uri||x.generated_filename)&&<button type="button" onClick={()=>markSent(x)} disabled={saving===`sent-${x.submission_id}`}><Send size={14}/> Tandai Terkirim</button>}
          {sent&&!x.invoice_id&&<button type="button" onClick={()=>recordInvoice(x)} disabled={saving===`invoice-${x.submission_id}`}><FileCheck2 size={14}/> Catat Invoice</button>}
          {sent&&!x.invoice_evidence_uri&&<button type="button" onClick={()=>uploadInvoice(x)} disabled={saving===`upload-invoice-${x.submission_id}`||!invoiceFiles[x.submission_id]}><Upload size={14}/> Upload Invoice</button>}
          {x.invoice_id&&!existingMaker&&Number(x.invoice_amount||0)>0&&<button type="button" onClick={()=>createMakerAndApproval(x)} disabled={saving===`maker-${x.invoice_id}`}><Stamp size={14}/> Buat Maker</button>}
        </div></td></tr>;
      })}{!loading&&accountant.length===0&&<tr><td colSpan="9" className="ops-empty-cell">Belum ada submission akuntan.</td></tr>}</tbody></table></div>
    </section>

    <section className="ops-module">
      <div className="ops-module-header">
        <div><span className="ops-kicker">BGN</span><h3>Maker & Pending Approval</h3><p>Maker dan approval tetap state terpisah. Maker baru dari alur akuntan sekarang terikat ke invoice sehingga dua perencanaan pada tanggal yang sama tidak saling menimpa.</p></div>
        <div className="ops-row-actions"><button type="button" onClick={copyPending}><ClipboardCopy size={14}/> Copy Pending ({pendingBgn.length})</button><button type="button" onClick={waPending}><MessageCircle size={14}/> WhatsApp Pending</button></div>
      </div>
      <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Site</th><th>Maker</th><th>Invoice</th><th>Referensi</th><th>Nilai</th><th>Maker Status</th><th>Approver</th><th>Approval</th><th>Approved</th></tr></thead><tbody>{bgn.map(x=><tr key={x.maker_id}><td>{x.site}</td><td>#{x.maker_id}</td><td>{x.accountant_invoice_id?`#${x.accountant_invoice_id}`:"-"}</td><td>{x.reference_number||"-"}</td><td>{money(x.maker_amount)}</td><td>{x.maker_status}</td><td>{x.approver_code||"-"}</td><td>{x.approval_status||"Belum diminta"}</td><td>{x.approved_at||"-"}</td></tr>)}{!loading&&bgn.length===0&&<tr><td colSpan="9" className="ops-empty-cell">Belum ada maker BGN.</td></tr>}</tbody></table></div>
    </section>
  </div>;
}
