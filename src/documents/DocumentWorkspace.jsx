import React, { useEffect, useRef, useState } from "react";
import { CheckCircle2, Download, Edit3, Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { documentApi } from "./documentApi.js";
import { downloadBase64, lpdhApi } from "../lpdh/lpdhApi.js";
import "./documents.css";
import DocumentCalendar from "./DocumentCalendar.jsx";

const TYPES = { BAHAN_BAKU: "Invoice Bahan Baku", OPERASIONAL: "Invoice Operasional", UPAH_RELAWAN: "Kuitansi Upah Relawan", INSENTIF_GURU_KADER: "Kuitansi Insentif Guru / Kader" };
const money = value => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 2 }).format(Number(value) || 0);
export const todayJakarta = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Jakarta", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
const uuid = () => globalThis.crypto?.randomUUID?.() || `doc-${Date.now()}-${Math.random().toString(36).slice(2)}`;
const blank = type => ({ itemName: "", category: type === "OPERASIONAL" ? "Lain-lain" : "Bahan baku", quantity: 1, unit: ["UPAH_RELAWAN", "INSENTIF_GURU_KADER"].includes(type) ? "hari" : "unit", unitPrice: 0, metadata: { recipientType: "Guru" } });

function Field({ label, value, onChange, type = "text", children }) {
  return <label className="doc-field"><span>{label}</span>{children || <input type={type} value={value ?? ""} onChange={e => onChange(e.target.value)} />}</label>;
}

export default function DocumentWorkspace({ site = "MAJA", serviceDate, onDateChange, onFinalized, onOpenDaily }) {
  const [type, setType] = useState("BAHAN_BAKU");
  const [master, setMaster] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [lines, setLines] = useState([]);
  const [header, setHeader] = useState({});
  const [profile, setProfile] = useState("KOPERASI");
  const [selected, setSelected] = useState("");
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState(null);
  const [calendarRevision, setCalendarRevision] = useState(0);
  const [showCancelled, setShowCancelled] = useState(false);
  const context = useRef(0);
  const requestKey = useRef(uuid());
  const submitLock = useRef(false);
  const receipts = type === "UPAH_RELAWAN" || type === "INSENTIF_GURU_KADER";
  const total = lines.reduce((sum, row) => sum + Math.round(Number(row.quantity) * Number(row.unitPrice) * 100) / 100, 0);
  const options = (master?.items || []).filter(x => x.kind === type);
  const notify = (text, error = false) => setMessage({ text, error });

  useEffect(() => {
    const version = ++context.current;
    setLoading(true); setMaster(null); setDocuments([]); setLines([]); setEditing(null); setHeader({}); setMessage(null);
    setType("BAHAN_BAKU"); setProfile("KOPERASI"); requestKey.current = uuid();
    Promise.allSettled([documentApi.master(site), documentApi.list(site, serviceDate)]).then(results => {
      if (version !== context.current) return;
      if (results[0].status === "fulfilled") {
        setMaster(results[0].value); setHeader(results[0].value.profiles?.KOPERASI || {});
      }
      if (results[1].status === "fulfilled") setDocuments(results[1].value.documents || []);
      const failed = results.find(x => x.status === "rejected");
      if (failed) notify(failed.reason.message, true);
      setLoading(false);
    });
    return () => { context.current++; };
  }, [site, serviceDate]);

  const run = async action => {
    if (submitLock.current) return;
    submitLock.current = true; setBusy(true); setMessage(null);
    const version = context.current;
    try { await action(version); } catch (e) { if (version === context.current) notify(e.message, true); }
    finally { submitLock.current = false; setBusy(false); }
  };
  const reload = async version => {
    const result = await documentApi.list(site, serviceDate);
    if (version === context.current) { setDocuments(result.documents || []); setCalendarRevision(x => x + 1); }
  };
  const reset = nextType => {
    setType(nextType); setLines([]); setEditing(null); setSelected(""); requestKey.current = uuid();
    const nextProfile = ["UPAH_RELAWAN", "INSENTIF_GURU_KADER"].includes(nextType) ? "YAYASAN" : "KOPERASI";
    const available = master?.profiles?.[nextProfile] ? nextProfile : "KOPERASI";
    setProfile(available); setHeader(master?.profiles?.[available] || {});
  };
  const chooseType = next => {
    if ((lines.length || editing) && !window.confirm("Ganti jenis dokumen? Perubahan yang belum disimpan akan dikosongkan.")) return;
    reset(next);
  };
  const update = (index, key, value) => setLines(rows => rows.map((row, i) => i === index ? { ...row, [key]: value } : row));
  const updateMetadata = (index, key, value) => setLines(rows => rows.map((row, i) => i === index ? { ...row, metadata: { ...row.metadata, [key]: value } } : row));
  const addSelected = () => {
    const item = options.find(x => x.recordKey === selected);
    if (!item) return;
    setLines(rows => [...rows, { ...item, quantity: 1, metadata: { itemCode: item.recordKey } }]); setSelected("");
  };
  const prepare = () => {
    let rows = [];
    if (type === "UPAH_RELAWAN") rows = (master?.volunteers || []).map(x => ({ ...blank(type), itemName: x.name, unitPrice: Number(x.dailyRate) || 0, metadata: { volunteerCode: x.code || x.name, role: x.role || "" } }));
    else {
      const unique = new Map();
      (master?.recipients || []).forEach(x => unique.set(`${x.name.toLowerCase()}:${x.recipientType}`, x));
      rows = [...unique.values()].map(x => ({ ...blank(type), itemName: x.name, metadata: { recipientType: x.recipientType, unitName: x.unitName } }));
    }
    if (!rows.length) return notify("Master penerima masih kosong. Tambah penerima manual atau lengkapi Master Data LPDH.", true);
    if (lines.length && !window.confirm("Ganti daftar penerima saat ini dengan data master?")) return;
    setLines(rows); notify("Penerima disiapkan untuk satu hari. Periksa nama, tugas/unit, dan nominal sebelum menyimpan.");
  };
  const pullPlan = () => run(async version => {
    if (lines.length && !window.confirm("Ganti daftar item saat ini dengan Final Kalkulator?")) return;
    const result = await lpdhApi.getFinalPlan(site, serviceDate);
    const shopping = result.plan?.payload?.shoppingListJSON?.shoppingList || [];
    if (!shopping.length) throw new Error("Final Kalkulator untuk tanggal ini belum tersedia atau tidak memiliki daftar belanja.");
    if (version !== context.current) return;
    setLines(shopping.map(x => ({ itemName: x.item || x.name || x.source_ingredient || "", category: x.category || x.supplier_category || "Bahan baku", quantity: Number(x.jumlah ?? x.qty ?? 0), unit: x.satuan || x.unit || "unit", unitPrice: Number(x.harga_satuan ?? x.price ?? 0), metadata: { note: x.note || "" } })));
    notify("Daftar belanja ditarik sebagai rancangan invoice. Sesuaikan realisasi dan harga sebelum menyimpan.");
  });
  const save = () => run(async version => {
    if (!lines.length) throw new Error("Tambahkan item atau penerima terlebih dahulu.");
    if (lines.some(x => !x.itemName.trim() || !x.unit.trim() || Number(x.quantity) <= 0 || Number(x.unitPrice) <= 0)) throw new Error("Nama, satuan, jumlah, dan harga/nominal positif wajib diisi pada setiap baris.");
    const payload = { site, service_date: serviceDate, document_type: type, request_key: requestKey.current,
      header_payload: header, items: lines.map(x => ({ item_name: x.itemName, category_code: x.category, quantity: Number(x.quantity), unit: x.unit, unit_price: Number(x.unitPrice), metadata: x.metadata || {} })) };
    const result = editing ? await documentApi.edit(editing.id, payload) : await documentApi.create(payload);
    if (version !== context.current) return;
    setLines([]); setEditing(null); requestKey.current = uuid(); await reload(version);
    notify(`${result.document.documentNumber} tersimpan sebagai DRAFT. Buka PDF di tab baru untuk memeriksa, lalu finalkan agar masuk data harian.`);
  });
  const edit = doc => {
    if (lines.length && !window.confirm("Buka draft ini dan kosongkan perubahan yang belum disimpan?")) return;
    setEditing(doc); setType(doc.documentType); setLines(doc.items); setHeader(doc.header); setProfile(doc.header.assetProfile === "maja-yayasan" ? "YAYASAN" : "KOPERASI"); requestKey.current = uuid();
  };
  const finalize = doc => {
    if (!window.confirm(`Yakin finalkan ${doc.documentNumber} sebesar ${money(doc.total)}?\n\nIsi dokumen akan dikunci dan masuk otomatis ke data harian LPDH ${site}, tanggal ${serviceDate}.`)) return;
    run(async version => {
      const result = await documentApi.finalize(doc.id); await reload(version);
      if (version !== context.current) return;
      await onFinalized?.(); notify(`${doc.documentNumber} FINAL dan sudah masuk data harian. ${result.driveUploadStatus === "UPLOADED" ? "PDF final tersimpan di SPPG Drive." : result.driveUploadError || "Upload Drive belum berhasil; klik Simpan ke Drive untuk mencoba lagi."}`, result.driveUploadStatus !== "UPLOADED");
    });
  };
  const download = doc => run(async version => {
    const result = await documentApi.pdf(doc.id);
    if (version !== context.current) return;
    downloadBase64(result.filename, result.mimeType, result.contentBase64);
    notify(`PDF ${doc.documentNumber} berhasil diunduh. Buka file untuk mencetak.`);
  });
  const preview = doc => {
    const tab = window.open("about:blank", "_blank");
    if (!tab) return notify("Browser memblokir tab PDF. Izinkan pop-up untuk aplikasi ini lalu coba lagi.", true);
    tab.opener = null;
    run(async version => {
      try {
        const result = await documentApi.pdf(doc.id);
        if (version !== context.current) { tab.close(); return; }
        const bytes = Uint8Array.from(atob(result.contentBase64), char => char.charCodeAt(0));
        const url = URL.createObjectURL(new Blob([bytes], { type: result.mimeType }));
        tab.location.replace(url);
        setTimeout(() => URL.revokeObjectURL(url), 5 * 60 * 1000);
        notify(`PDF ${doc.documentNumber} dibuka di tab baru.`);
      } catch (e) { tab.close(); throw e; }
    });
  };
  const archive = doc => run(async version => {
    const result = await documentApi.archive(doc.id); await reload(version);
    if (version === context.current) notify(result.driveUploadStatus === "UPLOADED" ? "PDF final tersimpan di SPPG Drive." : result.driveUploadError, result.driveUploadStatus !== "UPLOADED");
  });
  const cancel = doc => {
    const reason = window.prompt(`Alasan membatalkan ${doc.documentNumber}:\nDokumen dikeluarkan dari biaya harian. Riwayat dan arsip lama tetap disimpan; pengganti memakai nomor baru.`);
    if (reason === null) return;
    if (reason.trim().length < 3) return notify("Alasan pembatalan minimal 3 karakter.", true);
    if (!window.confirm(`Yakin batalkan ${doc.documentNumber}?\n${reason.trim()}`)) return;
    run(async version => {
      await documentApi.cancel(doc.id, reason.trim()); await reload(version);
      if (version !== context.current) return;
      if (editing?.id === doc.id) reset(type);
      await onFinalized?.(); notify(`${doc.documentNumber} dibatalkan. Buat dokumen pengganti dengan nomor baru bila diperlukan.`);
    });
  };
  const changeDate = value => {
    if (!value || busy || loading) return;
    if (lines.length && !window.confirm("Ganti tanggal? Simpan draft dahulu jika ingin mempertahankan daftar ini.")) return;
    onDateChange?.(value);
  };

  return <div className="doc-workspace" aria-busy={busy || loading}>
    <DocumentCalendar site={site} serviceDate={serviceDate} onSelect={changeDate} revision={calendarRevision}/>
    <section className="doc-card">
      <div className="doc-heading"><div><span className="doc-kicker">DOKUMEN HARIAN · {site}</span><h2>Buat Invoice & Kuitansi</h2><p>1. Pilih item/penerima · 2. Simpan draft & buka PDF · 3. Finalkan → data harian LPDH & SPPG Drive</p></div><button type="button" disabled={busy || loading} onClick={() => run(reload)}><RefreshCw size={15}/> Refresh register</button></div>
      {message && <div role="status" className={`doc-message${message.error ? " error" : ""}`}>{message.text}</div>}
      <fieldset disabled={busy || loading} className="doc-form">
        <div className="doc-grid">
          <Field label="Tanggal pembayaran / pelayanan" type="date" value={serviceDate} onChange={changeDate}/>
          <Field label="Jenis dokumen"><select value={type} disabled={Boolean(editing)} onChange={e => chooseType(e.target.value)}>{Object.entries(TYPES).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field>
          <Field label="Kop surat"><select value={profile} onChange={e => { const next = e.target.value; setProfile(next); setHeader({ ...master?.profiles?.[next], evidenceLink: header.evidenceLink || "", paymentReference: header.paymentReference || "" }); }}>{Object.keys(master?.profiles || { KOPERASI: {} }).map(key => <option key={key}>{key}</option>)}</select></Field>
        </div>
        <details className="doc-details" open={!header.issuerName || !header.recipientAddress}>
          <summary>Kop, alamat, rekening & penandatangan {site === "MAJA" ? "(terisi dari contoh Maja)" : "(lengkapi data Cemplang)"}</summary>
          <div className="doc-grid">{[["issuerName", "Nama penerbit"], ["issuerAddress", "Alamat penerbit"], ["senderName", "Nama pengirim"], ["senderCompany", "Perusahaan pengirim"], ["recipientName", "Nama penerima / dapur"], ["recipientAddress", "Alamat penerima"], ["bankName", "Bank"], ["accountNumber", "Nomor rekening"], ["accountName", "Atas nama rekening"], ["senderSignatory", "Penandatangan penerbit"], ["recipientSignatory", "Penandatangan dapur"]].map(([key, label]) => <Field key={key} label={label} value={header[key]} onChange={v => setHeader({ ...header, [key]: v })}/>)}</div>
        </details>
        <div className="doc-grid">
          <Field label="Metode pembayaran"><select value={header.paymentMethod || "Transfer"} onChange={e => setHeader({ ...header, paymentMethod: e.target.value })}><option>Transfer</option><option>Tunai</option><option>Lainnya</option></select></Field>
          <Field label="Referensi pembayaran (jika tersedia)" value={header.paymentReference} onChange={v => setHeader({ ...header, paymentReference: v })}/>
          <Field label="Link bukti autentik / PDF bertanda tangan" value={header.evidenceLink} onChange={v => setHeader({ ...header, evidenceLink: v })}/>
        </div>
        <div className="doc-actions">
          {!receipts && <><select aria-label="Item dari master" value={selected} onChange={e => setSelected(e.target.value)}><option value="">Pilih item dari master…</option>{options.map(x => <option key={x.recordKey} value={x.recordKey}>{x.itemName} · {money(x.unitPrice)}/{x.unit}</option>)}</select><button type="button" onClick={addSelected} disabled={!selected}><Plus size={15}/> Tambah item master</button></>}
          {type === "BAHAN_BAKU" && <button type="button" onClick={pullPlan}>Tarik Final Kalkulator</button>}
          {receipts && <button type="button" onClick={prepare}>Siapkan penerima dari master</button>}
          <button type="button" onClick={() => setLines(rows => [...rows, blank(type)])}><Plus size={15}/> {receipts ? "Tambah penerima" : "Tambah manual"}</button>
        </div>
        <p className="doc-hint">{receipts ? "Pembayaran satu hari per penerima. Satu file PDF memuat seluruh kuitansi jenis ini; nomor setiap penerima berbeda." : "Pilih beberapa item sebelum membuat invoice. Harga referensi Maja perlu diperiksa; sewa mobil diisi sesuai biaya harian yang berlaku."}</p>
        <div className="doc-table-wrap"><table className="doc-table"><thead><tr><th>{receipts ? "Nama penerima" : "Nama item"}</th><th>{receipts ? "Tugas / Jenis & unit" : "Kategori"}</th><th>Jumlah</th><th>Satuan</th><th>{receipts ? "Nominal harian" : "Harga satuan"}</th><th>Total</th><th/></tr></thead><tbody>
          {lines.map((row, index) => <tr key={index}>
            <td><input aria-label={`Nama baris ${index + 1}`} value={row.itemName} onChange={e => update(index, "itemName", e.target.value)}/></td>
            <td>{type === "OPERASIONAL" ? <select aria-label={`Kategori baris ${index + 1}`} value={row.category} onChange={e => update(index, "category", e.target.value)}>{(master?.categories || ["Lain-lain"]).map(x => <option key={x}>{x}</option>)}</select> : type === "INSENTIF_GURU_KADER" ? <><select aria-label="Jenis penerima" value={row.metadata?.recipientType || "Guru"} onChange={e => updateMetadata(index, "recipientType", e.target.value)}><option>Guru</option><option>Kader</option></select><input placeholder="Sekolah / posyandu" value={row.metadata?.unitName || ""} onChange={e => updateMetadata(index, "unitName", e.target.value)}/></> : type === "UPAH_RELAWAN" ? <input placeholder="Tugas" value={row.metadata?.role || ""} onChange={e => updateMetadata(index, "role", e.target.value)}/> : <input value={row.category} onChange={e => update(index, "category", e.target.value)}/>}</td>
            <td><input type="number" aria-label="Jumlah" step="0.0001" min="0.0001" disabled={receipts} value={row.quantity} onChange={e => update(index, "quantity", e.target.value)}/></td>
            <td><input aria-label="Satuan" disabled={receipts} value={row.unit} onChange={e => update(index, "unit", e.target.value)}/></td>
            <td><input type="number" aria-label="Harga atau nominal" step="0.01" min="0.01" value={row.unitPrice} onChange={e => update(index, "unitPrice", e.target.value)}/></td>
            <td className="doc-money">{money(Math.round(Number(row.quantity) * Number(row.unitPrice) * 100) / 100)}</td>
            <td><button type="button" aria-label="Hapus baris" onClick={() => setLines(rows => rows.filter((_, i) => i !== index))}><Trash2 size={15}/></button></td>
          </tr>)}
          {!lines.length && <tr><td colSpan="7" className="doc-empty">{loading ? "Memuat master dan register…" : "Pilih item/penerima untuk memulai dokumen."}</td></tr>}
        </tbody></table></div>
        <div className="doc-bottom"><strong>Total {money(total)}</strong><div className="doc-actions">{editing && <button type="button" onClick={() => reset(type)}>Selesai edit</button>}<button type="button" className="primary" disabled={!lines.length || loading || busy} onClick={save}><Save size={15}/> {editing ? "Simpan perubahan draft" : "Buat nomor & simpan draft"}</button></div></div>
      </fieldset>
    </section>
    <section className="doc-card"><div className="doc-heading"><div><h3>Register Invoice & Kuitansi · {serviceDate}</h3><p>Beberapa invoice operasional per hari. Final masuk data harian dan diarsipkan ke Drive; pembatalan menyimpan riwayat, bukan menghapus bukti.</p></div>{onOpenDaily && <button type="button" onClick={onOpenDaily}>Buka Data Harian</button>}</div>
      <label className="doc-history-toggle"><input type="checkbox" checked={showCancelled} onChange={e => setShowCancelled(e.target.checked)}/> Tampilkan riwayat dibatalkan</label>
      <div className="doc-table-wrap"><table className="doc-table"><thead><tr><th>Nomor dokumen</th><th>Jenis</th><th>Item / penerima</th><th>Total</th><th>Status</th><th>Aksi</th></tr></thead><tbody>{documents.filter(doc => showCancelled || doc.status !== "CANCELLED").map(doc => <tr key={doc.id}>
        <td><strong>{doc.documentNumber}</strong></td><td>{TYPES[doc.documentType]}</td><td>{doc.items.length}</td><td className="doc-money">{money(doc.total)}</td>
        <td><span className={`doc-status ${doc.status === "FINAL" ? "final" : ""}`}>{doc.status === "CANCELLED" ? "DIBATALKAN" : doc.status}</span>
          {doc.status === "FINAL" && <><small>Dasar data harian</small><small>{doc.driveUri ? "Tersimpan di Drive" : "Belum tersimpan di Drive"}</small>{doc.driveUploadError && <small>{doc.driveUploadError}</small>}</>}
          {doc.status === "CANCELLED" && <small>{doc.cancellationReason}</small>}
        </td>
        <td><div className="doc-actions">
          <button type="button" disabled={busy} onClick={() => preview(doc)}>Buka PDF{doc.status === "DRAFT" ? " Draft" : ""}</button>
          {doc.status === "FINAL" && <><button type="button" disabled={busy} onClick={() => download(doc)}><Download size={14}/> Unduh PDF</button>{doc.driveUri ? <a href={doc.driveUri} target="_blank" rel="noopener noreferrer">Buka SPPG Drive</a> : <button type="button" disabled={busy} onClick={() => archive(doc)}>Simpan ke Drive</button>}</>}
          {doc.status === "DRAFT" && <><button type="button" disabled={busy} onClick={() => edit(doc)}><Edit3 size={14}/> Edit</button><button type="button" className="primary" disabled={busy} onClick={() => finalize(doc)}><CheckCircle2 size={14}/> Finalkan</button></>}
          {doc.status !== "CANCELLED" && <button type="button" disabled={busy} onClick={() => cancel(doc)}><Trash2 size={14}/> Batalkan</button>}
        </div></td></tr>)}{!documents.some(doc => showCancelled || doc.status !== "CANCELLED") && <tr><td colSpan="6" className="doc-empty">Belum ada dokumen aktif pada tanggal ini.</td></tr>}</tbody></table></div>
    </section>
  </div>;
}
