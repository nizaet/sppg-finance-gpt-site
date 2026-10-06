import React, { useEffect, useRef, useState } from "react";
import { CheckCircle2, Download, Edit3, Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { documentApi } from "./documentApi.js";
import { downloadBase64, lpdhApi } from "../lpdh/lpdhApi.js";
import "./documents.css";
import DocumentCalendar from "./DocumentCalendar.jsx";
import DocumentAssets from "./DocumentAssets.jsx";

const TYPES = { BAHAN_BAKU: "Invoice Bahan Baku", OPERASIONAL: "Invoice Operasional", UPAH_RELAWAN: "Kuitansi Upah Relawan", INSENTIF_GURU_KADER: "Kuitansi Insentif Guru / Kader" };
const money = value => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 2 }).format(Number(value) || 0);
export const todayJakarta = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Jakarta", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
const uuid = () => globalThis.crypto?.randomUUID?.() || `doc-${Date.now()}-${Math.random().toString(36).slice(2)}`;
const blank = type => ({ itemName: "", category: type === "OPERASIONAL" ? "Lain-lain" : "Bahan baku", quantity: 1, unit: ["UPAH_RELAWAN", "INSENTIF_GURU_KADER"].includes(type) ? "hari" : "unit", unitPrice: 0, metadata: { recipientType: "Guru" } });

function Field({ label, value, onChange, type = "text", children }) {
  return <label className="doc-field"><span>{label}</span>{children || <input type={type} value={value ?? ""} onChange={e => onChange(e.target.value)} />}</label>;
}

export default function DocumentWorkspace({ site = "MAJA", serviceDate, onDateChange, onFinalized, onOpenDaily, onRoutineDaily, searchable = false }) {
  const [type, setType] = useState("BAHAN_BAKU");
  const [master, setMaster] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [lines, setLines] = useState([]);
  const [header, setHeader] = useState({});
  const [documentNumber, setDocumentNumber] = useState("");
  const [profile, setProfile] = useState("KOPERASI");
  const [selected, setSelected] = useState("");
  const [itemSearch, setItemSearch] = useState("");
  const [lineSearch, setLineSearch] = useState("");
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState(null);
  const [calendarRevision, setCalendarRevision] = useState(0);
  const [showCancelled, setShowCancelled] = useState(false);
  const [routineQueue, setRoutineQueue] = useState([]);
  const [activeRoutine, setActiveRoutine] = useState(null);
  const [routineScope, setRoutineScope] = useState("ALL");
  const [routineDate, setRoutineDate] = useState("");
  const context = useRef(0);
  const documentReads = useRef(0);
  const requestKey = useRef(uuid());
  const submitLock = useRef(false);
  const numberEdited = useRef(false);
  const numberReads = useRef(0);
  const receipts = type === "UPAH_RELAWAN" || type === "INSENTIF_GURU_KADER";
  const legacyReceipts = receipts && Boolean(editing) && editing.header?.paymentSnapshotVersion !== 2;
  const subtype = header.recipientSubtype || "Guru";
  const total = lines.reduce((sum, row) => sum + Math.round(Number(row.quantity) * Number(row.unitPrice) * 100) / 100, 0);
  const options = (master?.items || []).filter(x => x.kind === type);
  const matches = (values, query) => {
    const text = values.filter(value => value != null).join(" ").toLocaleLowerCase("id-ID");
    return query.trim().toLocaleLowerCase("id-ID").split(/\s+/).filter(Boolean).every(term => text.includes(term));
  };
  const matchingOptions = options.filter(item => matches([item.itemName, item.recordKey, item.category, item.unit], itemSearch));
  // Filtering never changes source indexes used for edits or deletes.
  const visibleLines = lines.map((row, index) => ({ row, index })).filter(({ row }) => !searchable || matches([row.itemName, row.category, row.metadata?.role, row.metadata?.unitName, row.metadata?.volunteerCode], lineSearch));
  const notify = (text, error = false) => setMessage({ text, error });

  useEffect(() => {
    const version = ++context.current;
    const readVersion = ++documentReads.current;
    setLoading(true); setMaster(null); setDocuments([]); setLines([]); setEditing(null); setHeader({}); setMessage(null); setDocumentNumber("");
    setType("BAHAN_BAKU"); setProfile("KOPERASI"); requestKey.current = uuid();
    setRoutineQueue([]); setActiveRoutine(null); setRoutineDate(""); setItemSearch(""); setLineSearch(""); setSelected("");
    numberEdited.current = false;
    Promise.allSettled([documentApi.master(site), documentApi.list(site, serviceDate)]).then(results => {
      if (version !== context.current) return;
      if (results[0].status === "fulfilled") {
        setMaster(results[0].value); setHeader({ ...results[0].value.profiles?.KOPERASI, documentProfileKey: "KOPERASI" });
      }
      if (results[1].status === "fulfilled" && readVersion === documentReads.current) setDocuments(results[1].value.documents || []);
      const failed = results.find(x => x.status === "rejected");
      if (failed) notify(failed.reason.message, true);
      setLoading(false);
    });
    return () => { context.current++; };
  }, [site, serviceDate]);

  useEffect(() => {
    const version = ++numberReads.current;
    if (editing || loading || numberEdited.current) return;
    documentApi.suggestNumber(site, serviceDate, type).then(result => {
      if (version === numberReads.current && !numberEdited.current) setDocumentNumber(result.documentNumber);
    }).catch(error => notify(error.message, true));
    return () => { numberReads.current++; };
  }, [site, serviceDate, type, editing, loading, calendarRevision]);

  useEffect(() => {
    const refresh = () => {
      if (submitLock.current || document.visibilityState === "hidden") return;
      const version = context.current;
      const readVersion = ++documentReads.current;
      documentApi.list(site, serviceDate).then(result => { if (version === context.current && readVersion === documentReads.current) { setDocuments(result.documents || []); setCalendarRevision(x => x + 1); } }).catch(() => {});
    };
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [site, serviceDate]);

  const run = async action => {
    if (submitLock.current) return;
    submitLock.current = true; setBusy(true); setMessage(null);
    const version = context.current;
    try { await action(version); } catch (e) { if (version === context.current) notify(e.message, true); }
    finally { submitLock.current = false; setBusy(false); }
  };
  const reload = async version => {
    const readVersion = ++documentReads.current;
    const result = await documentApi.list(site, serviceDate);
    if (version === context.current && readVersion === documentReads.current) { setDocuments(result.documents || []); setCalendarRevision(x => x + 1); }
  };
  const reset = nextType => {
    numberEdited.current = false; numberReads.current++;
    setType(nextType); setLines([]); setEditing(null); setSelected(""); setItemSearch(""); setLineSearch(""); setDocumentNumber(""); requestKey.current = uuid();
    setActiveRoutine(null);
    const nextProfile = ["UPAH_RELAWAN", "INSENTIF_GURU_KADER"].includes(nextType) ? "YAYASAN" : "KOPERASI";
    setProfile(nextProfile); setHeader({ ...master?.profiles?.[nextProfile], documentProfileKey: nextProfile, ...(["UPAH_RELAWAN", "INSENTIF_GURU_KADER"].includes(nextType) ? { paymentSnapshotVersion: 2, recipientSubtype: "Guru" } : {}) });
  };
  const chooseType = next => {
    if (next === type) return;
    if ((lines.length || editing) && !window.confirm("Ganti jenis dokumen? Perubahan yang belum disimpan akan dikosongkan.")) return;
    reset(next);
  };
  const update = (index, key, value) => setLines(rows => rows.map((row, i) => i === index ? { ...row, [key]: value } : row));
  const updateMetadata = (index, key, value) => setLines(rows => rows.map((row, i) => i === index ? { ...row, metadata: { ...row.metadata, [key]: value } } : row));
  const addSelected = (key = selected) => {
    const item = options.find(x => x.recordKey === key);
    if (!item) return;
    setLines(rows => [...rows, { ...item, quantity: 1, metadata: { itemCode: item.recordKey } }]); setSelected("");
  };
  const prepare = () => {
    let rows = [];
    if (type === "UPAH_RELAWAN") rows = (master?.volunteers || []).map(x => ({ ...blank(type), itemName: x.name, unitPrice: Number(x.dailyRate) || 0, metadata: { volunteerCode: x.code || x.name, role: x.role || "" } }));
    else {
      const unique = new Map();
      (master?.recipients || []).filter(x => legacyReceipts || x.recipientType === subtype).forEach(x => unique.set(`${x.name.toLowerCase()}:${x.recipientType}`, x));
      rows = [...unique.values()].map(x => ({ ...blank(type), itemName: x.name, metadata: { recipientType: x.recipientType, unitName: x.unitName } }));
    }
    if (!rows.length) return notify("Master penerima masih kosong. Tambah penerima manual atau lengkapi Master Data LPDH.", true);
    if (lines.length && !window.confirm("Ganti daftar penerima saat ini dengan data master?")) return;
    setLines(rows); notify("Penerima disiapkan untuk satu hari. Periksa nama, tugas/unit, dan nominal sebelum menyimpan.");
  };
  const activateRoutine = entry => {
    setItemSearch(""); setLineSearch(""); setSelected("");
    numberEdited.current = false; numberReads.current++;
    setEditing(null); setActiveRoutine(entry.key); setType(entry.documentType); setHeader(entry.header);
    setProfile(entry.header.documentProfileKey || (entry.documentType === "OPERASIONAL" ? "KOPERASI" : "YAYASAN"));
    setLines(entry.items.map(item => ({ ...item, metadata: { ...item.metadata } })));
    setDocumentNumber(""); setCalendarRevision(x => x+1); requestKey.current = entry.key;
  };
  const pullRoutine = () => run(async version => {
    if ((lines.length || editing || routineQueue.length) && !window.confirm("Ganti isian dan antrean yang belum disimpan dengan tarikan baru? Draft yang sudah disimpan tetap aman.")) return;
    const result = routineScope === "UPAH_RELAWAN" ? {sourceDate:"master relawan aktif",templates:[],hasDaily:false} : await documentApi.previousRoutine(site, serviceDate, routineDate);
    if (version !== context.current) return;
    let entries = (result.templates || []).filter(entry => routineScope === "ALL" || routineScope === entry.documentType || entry.header?.recipientSubtype === routineScope);
    if (routineScope === "ALL" || routineScope === "UPAH_RELAWAN") {
      const items = (master?.volunteers || []).map(x => ({ ...blank("UPAH_RELAWAN"), itemName: x.name,
        unitPrice: Number(x.dailyRate) || 0, metadata: { volunteerCode: x.code || x.name, role: x.role || "" } }));
      if (items.length) entries.push({ documentType: "UPAH_RELAWAN", sourceDate: "Master terbaru", items,
        header: { ...master?.profiles?.YAYASAN, recipientSignatureAssetId: null, evidenceLink: "", paymentReference: "", documentProfileKey: "YAYASAN", paymentSnapshotVersion: 2 } });
    }
    if (!entries.length && !(routineScope === "ALL" && result.hasDaily && onRoutineDaily)) throw new Error("Bagian yang dipilih belum memiliki data sumber. Relawan diambil dari master aktif, bahan baku dari Final Kalkulator hari ini.");
    if (!window.confirm(`Tarik ${entries.length} rancangan dokumen untuk ${serviceDate} dari ${result.sourceDate}?\nRelawan dari master terbaru; bahan baku tetap dari kalkulator. Rancangan dokumen belum disimpan dan belum FINAL. Periksa setiap rancangan sebelum Simpan draft.${routineScope === "ALL" && result.hasDaily && onRoutineDaily ? " Isian PM harian saat ini juga akan diganti dan DISIMPAN SEBAGAI DRAFT, bukan FINAL. Invoice serta bukti pembayaran hari ini tetap aman." : ""}`)) return;
    if (routineScope === "ALL" && result.hasDaily && onRoutineDaily) await onRoutineDaily(result);
    if (version !== context.current) return;
    entries = entries.map(entry => ({ ...entry, key: uuid() }));
    setRoutineQueue(entries);
    if (entries.length) activateRoutine(entries[0]);
    notify(`${entries.length} rancangan disiapkan. Pilih setiap rancangan pada antrean, edit, lalu Simpan draft. Bahan baku tidak disalin. ${routineScope === "ALL" && result.hasDaily && onRoutineDaily ? "Isian PM telah tersimpan sebagai draft di Data Harian, bukan FINAL." : ""}`);
  });
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
    if (!documentNumber.trim()) throw new Error("Isi nomor invoice atau nomor paket kuitansi secara manual terlebih dahulu.");
    if (!lines.length) throw new Error("Tambahkan item atau penerima terlebih dahulu.");
    if (lines.some(x => !x.itemName.trim() || !x.unit.trim() || Number(x.quantity) <= 0 || Number(x.unitPrice) <= 0)) throw new Error("Nama, satuan, jumlah, dan harga/nominal positif wajib diisi pada setiap baris.");
    if (legacyReceipts && lines.some(x => !x.metadata?.receiptNo?.trim())) throw new Error("Isi nomor kuitansi manual untuk setiap penerima historis.");
    if (type === "INSENTIF_GURU_KADER" && !legacyReceipts && lines.some(x => x.metadata?.recipientType !== subtype)) throw new Error("Penerima wajib sesuai paket Guru atau Kader.");
    const payload = { site, service_date: serviceDate, document_type: type, request_key: requestKey.current,
      document_number: documentNumber.trim(), header_payload: { ...header, documentProfileKey: profile, ...(receipts && !legacyReceipts ? { paymentSnapshotVersion: 2, recipientSubtype: subtype } : {}) }, items: lines.map(x => ({ item_name: x.itemName, category_code: x.category, quantity: Number(x.quantity), unit: x.unit, unit_price: Number(x.unitPrice), metadata: x.metadata || {} })) };
    const result = editing ? await documentApi.edit(editing.id, payload) : await documentApi.create(payload);
    if (version !== context.current) return;
    setMaster(old => ({ ...old, profiles: { ...old?.profiles, [profile]: { ...header, documentProfileKey: profile, evidenceLink: "", paymentReference: "" } } }));
    setHeader(old => ({ ...old, evidenceLink: "", paymentReference: "" }));
    numberEdited.current = false; numberReads.current++;
    setLines([]); setEditing(null); setDocumentNumber(""); setItemSearch(""); setLineSearch(""); setSelected(""); requestKey.current = uuid(); await reload(version);
    if (activeRoutine) { setRoutineQueue(rows => rows.filter(row => row.key !== activeRoutine)); setActiveRoutine(null); }
    notify(`${result.document.documentNumber} tersimpan sebagai DRAFT. Buka PDF di tab baru untuk memeriksa, lalu finalkan agar masuk data harian.`);
  });
  const edit = doc => {
    if (lines.length && !window.confirm("Buka draft ini dan kosongkan perubahan yang belum disimpan?")) return;
    setItemSearch(""); setLineSearch(""); setSelected("");
    numberEdited.current = true; numberReads.current++;
    setEditing(doc); setType(doc.documentType); setLines(doc.items); setHeader(doc.header); setDocumentNumber(doc.documentNumber); setProfile(doc.header.documentProfileKey || (doc.header.assetProfile === "maja-yayasan" ? "YAYASAN" : "KOPERASI")); requestKey.current = uuid();
  };
  const finalize = doc => {
    run(async version => {
      ++documentReads.current;
      const current = (await documentApi.get(doc.id)).document;
      if (version !== context.current) return;
      if (current.site !== site || current.serviceDate !== serviceDate) throw new Error("Tanggal/dapur dokumen berubah. Refresh register.");
      setDocuments(rows => rows.map(row => row.id === current.id ? current : row));
      if (current.status === "CANCELLED") {
        setShowCancelled(true);
        notify(`Invoice ${current.documentNumber} sebelumnya sudah DIBATALKAN${current.cancellationReason ? `: ${current.cancellationReason}` : ""}. Klik Buat ulang pada riwayat tersebut, isi nomor baru, simpan draft, lalu finalkan dokumen penggantinya. Klik Finalkan tidak membatalkan invoice.`, true);
        return;
      }
      if (current.status === "FINAL") { await reload(version); return notify("Invoice ini sudah FINAL. Gunakan Buka PDF atau Simpan ke Drive bila diperlukan."); }
      const check = await documentApi.finalizationCheck(current.id);
      if (version !== context.current) return;
      if (check.dailyStatus === "GENERATED") throw new Error("LPDH tanggal ini sudah digenerate. Buka data harian dan simpan sebagai draft sebelum finalisasi.");
      const legacy = check.legacyReplacement;
      const replacementText = legacy ? `\n\nAda ${legacy.legacyCount} penerima dalam isian lama (${money(legacy.legacyTotal)}). GANTIKAN seluruh isian lama jenis paket ini dengan ${legacy.newCount} penerima pada kuitansi (${money(legacy.newTotal)})?\n${legacy.removedCount} penerima lama tidak ada pada paket baru; ${legacy.addedCount} penerima baru. Selisih nominal ${money(legacy.newTotal-legacy.legacyTotal)}. Isian lama disimpan sebagai riwayat, tidak dihitung ganda. Paket Guru/Kader lain dan dokumen FINAL lain tidak diganti.` : "";
      if (!window.confirm(`Yakin finalkan ${current.documentNumber} sebesar ${money(current.total)}?\n\nIsi dokumen akan dikunci dan masuk otomatis ke data harian LPDH ${site}, tanggal ${serviceDate}.${replacementText}`)) return;
      let result;
      try { result = await documentApi.finalize(current.id, legacy ? {replace_legacy_snapshot:legacy.snapshotHash} : {}); }
      catch (e) { await reload(version); setShowCancelled(true); throw e; }
      await reload(version);
      if (version !== context.current) return;
      await onFinalized?.(); notify(`${doc.documentNumber} FINAL dan sudah masuk data harian. ${result.driveUploadStatus === "UPLOADED" ? "PDF dan Excel final tersimpan bersama di SPPG Drive." : result.driveUploadError || "Upload Drive belum berhasil; klik Simpan ke Drive untuk mencoba lagi."}`, result.driveUploadStatus !== "UPLOADED");
    });
  };
  const recreate = doc => {
    if ((lines.length || documentNumber) && !window.confirm("Salin item dokumen dibatalkan? Isian yang belum disimpan akan diganti.")) return;
    numberEdited.current = false; numberReads.current++;
    setEditing(null); setType(doc.documentType); setDocumentNumber(""); setCalendarRevision(x => x + 1); setHeader({ ...doc.header, evidenceLink: "", paymentReference: "", ...(["UPAH_RELAWAN", "INSENTIF_GURU_KADER"].includes(doc.documentType) ? { paymentSnapshotVersion: 2, recipientSubtype: doc.header.recipientSubtype || doc.items[0]?.metadata?.recipientType || "Guru" } : {}) });
    setProfile(doc.header.documentProfileKey || (doc.header.assetProfile === "maja-yayasan" ? "YAYASAN" : "KOPERASI"));
    setLines(doc.items.map(x => ({ ...x, metadata: { ...x.metadata, receiptNo: "" } }))); requestKey.current = uuid();
    notify("Item disalin sebagai isian baru, belum disimpan. Isi nomor dokumen dan nomor kuitansi baru, lalu Simpan draft. Riwayat lama tetap dibatalkan.");
  };
  const saveDefault = () => run(async version => {
    const result = await documentApi.saveProfile(site, { ...header, documentProfileKey: profile });
    if (version !== context.current) return;
    setMaster(old => ({ ...old, profiles: { ...old?.profiles, [result.profile]: result.header } }));
    notify(`Data kop ${result.profile} ${site} disimpan sebagai default, berlaku sampai diisi ulang. Nomor, item, nominal, dan bukti transaksi tidak menjadi default.`);
  });
  const uploadAsset = (file, kind, field) => run(async version => {
    if (file.size > 5 * 1024 * 1024) throw new Error("Ukuran gambar maksimal 5 MB.");
    const content = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1]); reader.onerror = () => reject(new Error("Gambar tidak dapat dibaca")); reader.readAsDataURL(file); });
    const result = await documentApi.uploadAsset({ site, asset_kind: kind, filename: file.name, content_base64: content });
    if (version !== context.current) return;
    setHeader(old => ({ ...old, [field]: result.id }));
    notify("Gambar diunggah privat. Simpan data kop sebagai default atau Simpan draft untuk memakai gambar ini.");
  });
  const download = doc => run(async version => {
    const result = await documentApi.pdf(doc.id);
    if (version !== context.current) return;
    downloadBase64(result.filename, result.mimeType, result.contentBase64);
    notify(`PDF ${doc.documentNumber} berhasil diunduh. Buka file untuk mencetak.`);
  });
  const downloadExcel = doc => run(async version => {
    const result = await documentApi.excel(doc.id);
    if (version !== context.current) return;
    downloadBase64(result.filename, result.mimeType, result.contentBase64);
    notify(`Excel ${doc.documentNumber} diunduh dari data FINAL yang sama dengan PDF.`);
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
    if (version === context.current && result.driveUri) await onFinalized?.();
    if (version === context.current) notify(result.driveUploadStatus === "UPLOADED" ? "PDF dan Excel final tersimpan bersama di SPPG Drive." : result.driveUploadError, result.driveUploadStatus !== "UPLOADED");
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
        <details className="doc-details">
          <summary>Tarik dari hari pelayanan sebelumnya</summary>
          <div className="doc-grid">
            <Field label="Bagian yang ditarik"><select value={routineScope} onChange={e=>setRoutineScope(e.target.value)}><option value="ALL">Semua isian rutin</option><option value="OPERASIONAL">Semua invoice operasional</option><option value="Guru">Insentif guru</option><option value="Kader">Insentif kader</option><option value="UPAH_RELAWAN">Relawan dari master terbaru</option></select></Field>
            <Field label="Tanggal sumber (kosong = hari pelayanan sebelumnya)" type="date" value={routineDate} onChange={setRoutineDate}/>
            <button type="button" onClick={pullRoutine}>Tarik isian rutin sebagai draft</button>
          </div>
          <p className="doc-hint">Bahan baku masak tetap dari Final Kalkulator hari ini. Relawan dari master aktif. Nomor baru, bukti bayar, BAST, referensi transaksi dan status FINAL lama tidak disalin. Setiap invoice operasional tetap terpisah.</p>
        </details>
        {routineQueue.length > 0 && <div className="doc-details"><strong>Antrean tarikan · {routineQueue.length} belum disimpan</strong><div className="doc-actions">{routineQueue.map((entry, index)=><button type="button" key={entry.key} aria-pressed={entry.key===activeRoutine} disabled={entry.key===activeRoutine} onClick={()=>{if(lines.length&&!window.confirm("Pindah rancangan? Perubahan rancangan aktif yang belum disimpan akan dikosongkan."))return;activateRoutine(entry);}}>{index+1}. {entry.header.recipientSubtype || TYPES[entry.documentType]} · {entry.sourceNumber || "Master relawan"}</button>)}</div><p className="doc-hint">Periksa dan Simpan draft setiap rancangan. Nomor berikutnya muncul setelah nomor sebelumnya disimpan.</p></div>}
        <div className="doc-grid">
          <Field label={receipts ? "Nomor paket kuitansi (otomatis, bisa diedit)" : "Nomor invoice (otomatis, bisa diedit)"} value={documentNumber} onChange={value => { numberEdited.current = true; numberReads.current++; setDocumentNumber(value); }}/>
          <Field label="Tanggal pembayaran / pelayanan" type="date" value={serviceDate} onChange={changeDate}/>
          <Field label="Jenis dokumen"><select aria-label="Jenis dokumen" value={type} disabled={Boolean(editing)} onChange={e => chooseType(e.target.value)}>{Object.entries(TYPES).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field>
          <Field label="Kop surat"><select value={profile} onChange={e => { const next = e.target.value; setProfile(next); setHeader({ ...master?.profiles?.[next], documentProfileKey: next, paymentSnapshotVersion: header.paymentSnapshotVersion, recipientSubtype: header.recipientSubtype, evidenceLink: header.evidenceLink || "", paymentReference: header.paymentReference || "" }); }}>{["KOPERASI", "YAYASAN"].map(key => <option key={key}>{key}</option>)}</select></Field>
          {type === "INSENTIF_GURU_KADER" && !legacyReceipts && <Field label="Jenis paket insentif"><select aria-label="Jenis paket insentif" value={subtype} disabled={Boolean(editing)} onChange={e => { if (lines.length && !window.confirm("Ganti paket dan kosongkan penerima yang belum disimpan?")) return; setHeader(old => ({ ...old, recipientSubtype: e.target.value })); setLines([]); }}><option>Guru</option><option>Kader</option></select></Field>}
        </div>
        <details className="doc-details" open={!header.issuerName || !header.recipientAddress}>
          <summary>Kop, alamat, rekening & penandatangan {site === "MAJA" ? "(terisi dari contoh Maja)" : "(lengkapi data Cemplang)"}</summary>
          <div className="doc-grid">{[["issuerName", "Nama penerbit"], ["issuerAddress", "Alamat penerbit"], ["senderName", "Nama pengirim"], ["senderCompany", "Perusahaan pengirim"], ["recipientName", "Nama penerima / dapur"], ["recipientAddress", "Alamat penerima"], ["bankName", "Bank"], ["accountNumber", "Nomor rekening"], ["accountName", "Atas nama rekening"], ["senderSignatory", "Penandatangan penerbit"], ["recipientSignatory", "Penandatangan dapur"]].map(([key, label]) => <Field key={key} label={label} value={header[key]} onChange={v => setHeader({ ...header, [key]: v })}/>)}</div>
          <DocumentAssets header={header} site={site} disabled={busy || loading} onUpload={uploadAsset} onRemove={field => setHeader(old => ({ ...old, [field]: null }))}/>
          <button type="button" onClick={saveDefault} disabled={busy || loading}>Simpan data kop sebagai default</button>
          <p className="doc-hint">Data identitas, rekening, stempel dan TTD ini juga menjadi default saat draft disimpan. Tanggal, nomor, item dan nominal transaksi tetap diisi tiap dokumen.</p>
        </details>
        <div className="doc-grid">
          <Field label="Metode pembayaran"><select value={header.paymentMethod || "Transfer"} onChange={e => setHeader({ ...header, paymentMethod: e.target.value })}><option>Transfer</option><option>Tunai</option><option>Lainnya</option></select></Field>
          <Field label="Referensi pembayaran (jika tersedia)" value={header.paymentReference} onChange={v => setHeader({ ...header, paymentReference: v })}/>
          <Field label="Link bukti autentik / PDF bertanda tangan" value={header.evidenceLink} onChange={v => setHeader({ ...header, evidenceLink: v })}/>
        </div>
        <div className="doc-actions">
          {!receipts && <><select aria-label="Item dari master" value={selected} onChange={e => setSelected(e.target.value)}><option value="">Pilih item dari master…</option>{options.map(x => <option key={x.recordKey} value={x.recordKey}>{x.itemName} · {money(x.unitPrice)}/{x.unit}</option>)}</select><button type="button" onClick={() => addSelected()} disabled={!selected}><Plus size={15}/> Tambah item master</button></>}
          {type === "BAHAN_BAKU" && <button type="button" onClick={pullPlan}>Tarik Final Kalkulator</button>}
          {receipts && <button type="button" onClick={prepare}>Siapkan penerima dari master</button>}
          <button type="button" onClick={() => setLines(rows => [...rows, { ...blank(type), metadata: { recipientType: subtype } }])}><Plus size={15}/> {receipts ? "Tambah penerima" : "Tambah manual"}</button>
        </div>
        <p className="doc-hint">{receipts ? (legacyReceipts ? "Kuitansi historis mempertahankan nomor tiap penerima." : "Satu nomor kuitansi untuk total pembayaran harian. Halaman berikutnya memuat semua penerima dan kolom tanda terima kosong. Paket Guru dan Kader terpisah.") : "Pilih beberapa item sebelum membuat invoice. Harga referensi Maja perlu diperiksa; sewa mobil diisi sesuai biaya harian yang berlaku."}</p>
        {searchable && !receipts && <div className="doc-search-items">
          <Field label="Cari item dari master" type="search" value={itemSearch} onChange={setItemSearch}/>
          {itemSearch.trim() && <>
            <p role="status">{matchingOptions.length} item ditemukan{matchingOptions.length > 8 ? " · 8 hasil pertama; ketik lebih spesifik." : ""}</p>
            <div className="doc-search-results">{matchingOptions.slice(0, 8).map(item => <button key={item.recordKey} type="button" onClick={() => addSelected(item.recordKey)} aria-label={`Tambah ${item.itemName} dari hasil pencarian`}><Plus size={15}/><span>{item.itemName}<small>{item.category} · {money(item.unitPrice)}/{item.unit}</small></span></button>)}</div>
            {!matchingOptions.length && <p>Coba nama/kategori lain, atau gunakan Tambah manual.</p>}
          </>}
        </div>}
        {searchable && <div className="doc-line-search">
          <Field label={receipts ? "Cari penerima dalam kuitansi" : "Cari item dalam invoice"} type="search" value={lineSearch} onChange={setLineSearch}/>
          <span role="status">{visibleLines.length} dari {lines.length} baris · total dan penyimpanan tetap seluruh baris.</span>
          {lineSearch && <button type="button" onClick={() => setLineSearch("")}>Hapus pencarian</button>}
          {lines.length > 0 && !visibleLines.length && <p>Tidak ada hasil. Data tidak dihapus.</p>}
        </div>}
        <div className="doc-table-wrap"><table className="doc-table"><thead><tr><th>{receipts ? (legacyReceipts ? "Nama penerima & nomor kuitansi manual" : "Nama penerima") : "Nama item"}</th><th>{receipts ? "Tugas / Jenis & unit" : "Kategori"}</th><th>Jumlah</th><th>Satuan</th><th>{receipts ? "Nominal harian" : "Harga satuan"}</th><th>Total</th><th/></tr></thead><tbody>
          {visibleLines.map(({ row, index }) => <tr key={index}>
            <td data-label={receipts ? "Nama penerima" : "Nama item"}><input aria-label={`Nama baris ${index + 1}`} value={row.itemName} onChange={e => update(index, "itemName", e.target.value)}/>{legacyReceipts && <input aria-label={`Nomor kuitansi baris ${index + 1}`} placeholder="Nomor kuitansi manual" value={row.metadata?.receiptNo || ""} onChange={e => updateMetadata(index, "receiptNo", e.target.value)}/>}</td>
            <td data-label={receipts ? "Tugas / Jenis & unit" : "Kategori"}>{type === "OPERASIONAL" ? <select aria-label={`Kategori baris ${index + 1}`} value={row.category} onChange={e => update(index, "category", e.target.value)}>{(master?.categories || ["Lain-lain"]).map(x => <option key={x}>{x}</option>)}</select> : type === "INSENTIF_GURU_KADER" ? <><select aria-label="Jenis penerima" value={row.metadata?.recipientType || "Guru"} onChange={e => updateMetadata(index, "recipientType", e.target.value)}><option>Guru</option><option>Kader</option></select><input placeholder="Sekolah / posyandu" value={row.metadata?.unitName || ""} onChange={e => updateMetadata(index, "unitName", e.target.value)}/></> : type === "UPAH_RELAWAN" ? <input placeholder="Tugas" value={row.metadata?.role || ""} onChange={e => updateMetadata(index, "role", e.target.value)}/> : <input value={row.category} onChange={e => update(index, "category", e.target.value)}/>}</td>
            <td data-label={"Jumlah"}><input type="number" aria-label="Jumlah" step="0.0001" min="0.0001" disabled={receipts} value={row.quantity} onChange={e => update(index, "quantity", e.target.value)}/></td>
            <td data-label={"Satuan"}><input aria-label="Satuan" disabled={receipts} value={row.unit} onChange={e => update(index, "unit", e.target.value)}/></td>
            <td data-label={receipts ? "Nominal harian" : "Harga satuan"}><input type="number" aria-label="Harga atau nominal" step="0.01" min="0.01" value={row.unitPrice} onChange={e => update(index, "unitPrice", e.target.value)}/></td>
            <td className="doc-money" data-label={"Total"}>{money(Math.round(Number(row.quantity) * Number(row.unitPrice) * 100) / 100)}</td>
            <td data-label={"Tindakan"}><button type="button" aria-label="Hapus baris" onClick={() => setLines(rows => rows.filter((_, i) => i !== index))}><Trash2 size={15}/></button></td>
          </tr>)}
          {!lines.length && <tr><td colSpan="7" className="doc-empty">{loading ? "Memuat master dan register…" : "Pilih item/penerima untuk memulai dokumen."}</td></tr>}
        </tbody></table></div>
        <div className="doc-bottom"><strong>Total {money(total)}</strong><div className="doc-actions">{editing && <button type="button" onClick={() => reset(type)}>Selesai edit</button>}<button type="button" className="primary" disabled={!lines.length || loading || busy} onClick={save}><Save size={15}/> {editing ? "Simpan perubahan draft" : "Simpan draft"}</button></div></div>
      </fieldset>
    </section>
    <section className="doc-card"><div className="doc-heading"><div><h3>Register Invoice & Kuitansi · {serviceDate}</h3><p>Beberapa invoice operasional per hari. Final masuk data harian dan diarsipkan ke Drive; pembatalan menyimpan riwayat, bukan menghapus bukti.</p></div>{onOpenDaily && <button type="button" onClick={onOpenDaily}>Buka Data Harian</button>}</div>
      <label className="doc-history-toggle"><input type="checkbox" checked={showCancelled} onChange={e => setShowCancelled(e.target.checked)}/> Tampilkan riwayat dibatalkan</label>
      <div className="doc-table-wrap"><table className="doc-table"><thead><tr><th>Nomor dokumen</th><th>Jenis</th><th>Item / penerima</th><th>Total</th><th>Status</th><th>Aksi</th></tr></thead><tbody>{documents.filter(doc => showCancelled || doc.status !== "CANCELLED").map(doc => <tr key={doc.id}>
        <td data-label="Nomor dokumen"><strong>{doc.documentNumber}</strong></td><td data-label="Jenis">{doc.header?.recipientSubtype && doc.documentType === "INSENTIF_GURU_KADER" ? `Kuitansi Insentif ${doc.header.recipientSubtype}` : TYPES[doc.documentType]}</td><td data-label="Item / penerima">{doc.items.length}</td><td className="doc-money" data-label="Total">{money(doc.total)}</td>
        <td data-label="Status"><span className={`doc-status ${doc.status === "FINAL" ? "final" : ""}`}>{doc.status === "CANCELLED" ? "DIBATALKAN" : doc.status}</span>
          {doc.status === "FINAL" && <><small>Dasar data harian</small><small>{doc.driveUri && doc.driveExcelUri ? "PDF + Excel tersimpan di Drive" : doc.driveUri ? "PDF tersimpan; Excel belum diarsipkan" : "Arsip Drive belum lengkap"}</small>{doc.driveUploadError && <small>{doc.driveUploadError}</small>}</>}
          {doc.status === "CANCELLED" && <small>{doc.cancellationReason}</small>}
          {doc.cancelledAt && <small>Dibatalkan: {new Date(doc.cancelledAt).toLocaleString("id-ID", { timeZone: "Asia/Jakarta" })}</small>}
        </td>
        <td data-label="Aksi"><div className="doc-actions">
          <button type="button" disabled={busy} onClick={() => preview(doc)}>Buka PDF{doc.status === "DRAFT" ? " Draft" : ""}</button>
          {doc.status === "FINAL" && <><button type="button" disabled={busy} onClick={() => download(doc)}><Download size={14}/> Unduh PDF</button><button type="button" disabled={busy} onClick={() => downloadExcel(doc)}><Download size={14}/> Unduh Excel</button>{doc.driveUri && <a href={doc.driveUri} target="_blank" rel="noopener noreferrer">PDF di Drive</a>}{doc.driveExcelUri && <a href={doc.driveExcelUri} target="_blank" rel="noopener noreferrer">Excel di Drive</a>}{!(doc.driveUri && doc.driveExcelUri) && <button type="button" disabled={busy} onClick={() => archive(doc)}>Simpan ke Drive</button>}</>}
          {doc.status === "DRAFT" && <><button type="button" disabled={busy} onClick={() => edit(doc)}><Edit3 size={14}/> Edit</button><button type="button" className="primary" disabled={busy} onClick={() => finalize(doc)}><CheckCircle2 size={14}/> Finalkan</button></>}
          {doc.status !== "CANCELLED" && <button type="button" disabled={busy} onClick={() => cancel(doc)}><Trash2 size={14}/> Batalkan</button>}
          {doc.status === "CANCELLED" && <button type="button" disabled={busy} onClick={() => recreate(doc)}>Buat ulang</button>}
        </div></td></tr>)}{!documents.some(doc => showCancelled || doc.status !== "CANCELLED") && <tr><td colSpan="6" className="doc-empty">Belum ada dokumen aktif pada tanggal ini.</td></tr>}</tbody></table></div>
    </section>
  </div>;
}
