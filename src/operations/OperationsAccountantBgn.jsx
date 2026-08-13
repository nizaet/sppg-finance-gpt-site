import React, { useEffect, useMemo, useState } from "react";
import { ClipboardCopy, ExternalLink, FileCheck2, FileSpreadsheet, MessageCircle, RefreshCw, Send, Stamp } from "lucide-react";
import { operationsApi } from "./apiClient";

const money = (v) => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(Number(v || 0));
const APPROVERS = { MAJA: "EMBUN", CEMPLANG: "MALIK" };

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

function generatedExcelMessage(preview) {
  return [
    `*SPPG ${preview.site} — EXCEL AKUNTAN*`,
    `Akuntan: ${preview.accountantCode}`,
    `Tanggal distribusi: ${preview.distributionDate}`,
    `File: ${preview.filename}`,
    `Item: ${preview.itemCount}`,
    `Grand Total Estimasi: ${money(preview.grandTotal)}`,
    preview.paguBgn == null ? null : `Pagu BGN: ${money(preview.paguBgn)}`,
    preview.paguMinusEstimate == null ? null : `Selisih Pagu - Estimasi: ${money(preview.paguMinusEstimate)}`,
    preview.driveUri ? `Link Excel: ${preview.driveUri}` : "Link Excel: belum dibuat",
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
  const [excelPreview,setExcelPreview]=useState(null);
  const [excelBusy,setExcelBusy]=useState(false);

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

  const makerByCycle = useMemo(() => {
    const map = new Map();
    bgn.forEach((x) => {
      if (x.production_cycle_id != null && !map.has(String(x.production_cycle_id))) map.set(String(x.production_cycle_id), x);
    });
    return map;
  }, [bgn]);

  const previewExcel = async () => {
    setExcelBusy(true); setError(""); setMessage(""); setExcelPreview(null);
    try {
      const data = await operationsApi.generateAccountantExcel({ site: excelSite, distribution_date: excelDate }, false);
      setExcelPreview(data);
    } catch (e) {
      setError(e.message || "Gagal preview Excel akuntan");
    } finally {
      setExcelBusy(false);
    }
  };

  const createExcel = async () => {
    if (!excelPreview) return;
    const confirmed = window.confirm(
      `Buat file ${excelPreview.filename} dari snapshot Kalkulator #${excelPreview.planningSnapshotId} dan arsipkan ke Google Drive?\n\nFile akan berstatus READY, belum dianggap sudah dikirim ke ${excelPreview.accountantCode}.`
    );
    if (!confirmed) return;
    setExcelBusy(true); setError(""); setMessage("");
    try {
      const data = await operationsApi.generateAccountantExcel({
        site: excelSite,
        distribution_date: excelDate,
        planning_snapshot_id: excelPreview.planningSnapshotId,
      }, true);
      setExcelPreview(data);
      setMessage(data.duplicate ? "Excel untuk snapshot ini sudah pernah dibuat; file yang sama ditampilkan kembali." : "Excel dibuat dan diarsipkan ke Google Drive. Status masih READY sampai Anda benar-benar mengirimkannya.");
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
    if (!row.excel_evidence_uri) return;
    if (!window.confirm(`Tandai Excel submission #${row.submission_id} benar-benar sudah dikirim ke ${row.accountant_code}?`)) return;
    setSaving(`sent-${row.submission_id}`); setError(""); setMessage("");
    try {
      await operationsApi.markAccountantSubmissionSent(row.submission_id);
      setMessage(`Submission #${row.submission_id} ditandai SENT. Ini hanya dilakukan karena Anda mengonfirmasi file memang sudah dikirim.`);
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
    setMessage("WhatsApp dibuka dengan rekap pending approval. Pilih Embun/Malik sesuai site sebelum kirim.");
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
      setMessage("Invoice akuntan tercatat. Status pembayaran/receipt BGN belum berubah.");
      await load();
    } catch (e) {
      setError(e.message || "Gagal mencatat invoice akuntan");
    } finally {
      setSaving("");
    }
  };

  const createMakerAndApproval = async (row) => {
    if (!row.invoice_id || !row.production_cycle_id || Number(row.invoice_amount || 0) <= 0) return;
    if (makerByCycle.has(String(row.production_cycle_id))) {
      setError("Maker untuk production cycle ini sudah ada.");
      return;
    }
    const approver = APPROVERS[String(row.site || "").toUpperCase()];
    if (!approver) {
      setError("Approver site belum dapat ditentukan.");
      return;
    }
    const reference = row.invoice_number || `AKUNTAN-${row.submission_id}`;
    const confirmed = window.confirm(
      `Buat Maker BGN ${row.site} dari invoice ${reference} sebesar ${money(row.invoice_amount)} dan masukkan approval PENDING ke ${approver}?`
    );
    if (!confirmed) return;

    setSaving(`maker-${row.submission_id}`); setError(""); setMessage("");
    try {
      const maker = await operationsApi.createBgnMaker({
        production_cycle_id: row.production_cycle_id,
        site: row.site,
        reference_number: reference,
        amount: Number(row.invoice_amount),
      });
      await operationsApi.createBgnApproval({
        bgn_maker_id: maker.makerId,
        approver_code: approver,
        status: "PENDING",
        requested_at: null,
        approved_at: null,
        rejected_at: null,
      });
      setMessage(`Maker #${maker.makerId} dibuat dan approval PENDING diarahkan ke ${approver}. Belum dianggap approved.`);
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
        <div><span className="ops-kicker">KALKULATOR → EXCEL AKUNTAN</span><h3>Excel Belanja dari Planning Final</h3><p>Format mengikuti export Belanja Kalkulator: Item, Jumlah, Satuan, Harga Satuan Estimasi, Total Harga Estimasi, Catatan, dan Kategori/Supplier. Pembuatan file tidak otomatis berarti sudah dikirim.</p></div>
      </div>
      <div className="ops-form-grid">
        <label>Site<select value={excelSite} onChange={e=>{setExcelSite(e.target.value);setExcelPreview(null);}}><option value="MAJA">Maja → Tiara</option><option value="CEMPLANG">Cemplang → Uya</option></select></label>
        <label>Tanggal Distribusi<input type="date" value={excelDate} onChange={e=>{setExcelDate(e.target.value);setExcelPreview(null);}}/></label>
        <label>Aksi<div className="ops-row-actions"><button type="button" onClick={previewExcel} disabled={excelBusy}><FileSpreadsheet size={14}/> {excelBusy?"Memproses...":"Preview Excel"}</button></div></label>
      </div>
      {excelPreview&&<div className="ops-parse-result">
        <div><FileSpreadsheet size={16}/><strong>Preview Excel Akuntan</strong></div>
        <div className="ops-summary-strip">
          <span>Akuntan <strong>{excelPreview.accountantCode}</strong></span>
          <span>Snapshot <strong>#{excelPreview.planningSnapshotId}</strong></span>
          <span>Item <strong>{excelPreview.itemCount}</strong></span>
          <span>Grand Total <strong>{money(excelPreview.grandTotal)}</strong></span>
          {excelPreview.paguBgn!=null&&<span>Pagu BGN <strong>{money(excelPreview.paguBgn)}</strong></span>}
          {excelPreview.paguMinusEstimate!=null&&<span>Selisih <strong>{money(excelPreview.paguMinusEstimate)}</strong></span>}
          <span>Status <strong>{excelPreview.status||"PREVIEW"}</strong></span>
        </div>
        <div className="ops-muted">File: {excelPreview.filename} · Sheet: {excelPreview.sheetName}</div>
        <div className="ops-row-actions">
          {!excelPreview.driveUri&&<button type="button" onClick={createExcel} disabled={excelBusy}><FileSpreadsheet size={14}/> Buat Excel & Arsip Drive</button>}
          {excelPreview.driveUri&&<button type="button" onClick={()=>window.open(excelPreview.driveUri,"_blank","noopener,noreferrer")}><ExternalLink size={14}/> Buka Excel</button>}
          <button type="button" onClick={copyGeneratedExcel}><ClipboardCopy size={14}/> Copy Pesan</button>
          <button type="button" onClick={waGeneratedExcel}><MessageCircle size={14}/> WhatsApp</button>
        </div>
        <div className="ops-muted">READY = file sudah dibuat. SENT hanya setelah Anda mengonfirmasi file benar-benar sudah dikirim ke akuntan.</div>
      </div>}
    </section>

    <section className="ops-module">
      <div className="ops-module-header">
        <div><span className="ops-kicker">ACCOUNTANT</span><h3>Excel → Invoice Akuntan → Maker</h3><p>Maja → Tiara · Cemplang → Uya. Pengiriman WhatsApp masih manual; tombol hanya menyiapkan pesan/link dan tidak menganggap file sudah terkirim.</p></div>
        <div className="ops-inline-controls"><select value={site} onChange={e=>setSite(e.target.value)}><option value="">Semua site</option><option value="MAJA">Maja</option><option value="CEMPLANG">Cemplang</option></select><button onClick={load} disabled={loading}><RefreshCw size={15}/> Refresh</button></div>
      </div>
      {error&&<div className="ops-error">{error}</div>}
      {message&&<div className="ops-success">{message}</div>}
      <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Site</th><th>Akuntan</th><th>Excel Sent</th><th>Status</th><th>Invoice</th><th>Nilai</th><th>Diterima</th><th>Maker</th><th>Aksi</th></tr></thead><tbody>{accountant.map(x=>{
        const existingMaker = x.production_cycle_id != null ? makerByCycle.get(String(x.production_cycle_id)) : null;
        return <tr key={`${x.submission_id}-${x.invoice_id||0}`}><td>{x.site}</td><td>{x.accountant_code}</td><td>{x.sent_at||"-"}</td><td>{x.submission_status}</td><td>{x.invoice_number||"-"}</td><td>{money(x.invoice_amount)}</td><td>{x.received_at||"-"}</td><td>{existingMaker ? `#${existingMaker.maker_id}` : "-"}</td><td><div className="ops-row-actions">
          {x.excel_evidence_uri&&<button type="button" onClick={()=>window.open(x.excel_evidence_uri,"_blank","noopener,noreferrer")}><ExternalLink size={14}/> Buka Excel</button>}
          <button type="button" onClick={()=>copyAccountant(x)}><ClipboardCopy size={14}/> Copy</button>
          <button type="button" onClick={()=>waAccountant(x)}><MessageCircle size={14}/> WhatsApp</button>
          {x.excel_evidence_uri&&String(x.submission_status||"").toUpperCase()!=="SENT"&&<button type="button" onClick={()=>markSent(x)} disabled={saving===`sent-${x.submission_id}`}><Send size={14}/> Tandai Terkirim</button>}
          {!x.invoice_id&&<button type="button" onClick={()=>recordInvoice(x)} disabled={saving===`invoice-${x.submission_id}`}><FileCheck2 size={14}/> Catat Invoice</button>}
          {x.invoice_id&&!existingMaker&&x.production_cycle_id&&Number(x.invoice_amount||0)>0&&<button type="button" onClick={()=>createMakerAndApproval(x)} disabled={saving===`maker-${x.submission_id}`}><Stamp size={14}/> Buat Maker</button>}
        </div></td></tr>;
      })}{!loading&&accountant.length===0&&<tr><td colSpan="9" className="ops-empty-cell">Belum ada submission akuntan.</td></tr>}</tbody></table></div>
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
