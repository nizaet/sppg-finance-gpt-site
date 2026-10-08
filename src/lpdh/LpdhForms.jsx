import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import { Download, FileUp, Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { arrayBufferToBase64, downloadBase64 } from "./lpdhApi.js";
import { evidenceGroups, applyEvidence } from "./lpdhEvidence.js";
import { balanceSummary } from "./balanceSummary.mjs";
import { defaultBastRows } from './bastDefaults.mjs';
import { pendingReview } from './reviewSaveGate.mjs';
import TopupReceiptActions from './TopupReceiptActions.jsx';

export const GROUP_DEFAULTS = [
  { code: "KS-01", label: "PAUD/TK/RA", portion: "Kecil", pic: "Sekolah" },
  { code: "KS-02", label: "SD/MI Kelas 1–3", portion: "Kecil", pic: "Sekolah" },
  { code: "KS-03", label: "SD/MI Kelas 4–6", portion: "Besar", pic: "Sekolah" },
  { code: "KS-04", label: "SMP/MTs", portion: "Besar", pic: "Sekolah" },
  { code: "KS-05", label: "SMA/MA/SMK/SLB", portion: "Besar", pic: "Sekolah" },
  { code: "KS-06", label: "Santri", portion: "Besar", pic: "Sekolah" },
  { code: "KS-07", label: "Ibu Hamil", portion: "Besar", pic: "3B" },
  { code: "KS-08", label: "Ibu Menyusui", portion: "Besar", pic: "3B" },
  { code: "KS-09", label: "Anak Balita (6–59 bulan)", portion: "Kecil", pic: "3B" },
  { code: "PTK", label: "Pendidik dan Tenaga Kependidikan", portion: "Besar", pic: "Sekolah" },
];

const DEFAULT_PARAMETERS = {
  incentiveTariff: 2000,
  rawSmall: 8000,
  rawLarge: 10000,
  operationalPerPm: 3000,
  maxVa: 500000000,
  maxHpePerWeek: 5,
  uploadHour: 6,
  bufferPct: "",
  dateTolerance: 1,
  applyIndexRaw: true,
  applyIndexOp: true,
  cityIndex: 1,
  cityIndexSource: "",
};

function clone(value) {
  return JSON.parse(JSON.stringify(value ?? null));
}

function textValue(value) {
  return value == null ? "" : String(value);
}

function numValue(value) {
  if (value === "" || value == null) return "";
  const n = Number(value);
  return Number.isFinite(n) ? n : "";
}

function Field({ label, value, onChange, type = "text", placeholder = "", children, disabled = false }) {
  return <label className="lpdh-field">
    <span>{label}</span>
    {children || <input type={type} value={textValue(value)} onChange={(e) => onChange(type === "number" ? numValue(e.target.value) : e.target.value)} placeholder={placeholder} disabled={disabled} />}
  </label>;
}

function YesNo({ label, value, onChange }) {
  return <Field label={label}>
    <select value={value === true || value === "Ya" ? "Ya" : value === false || value === "Tidak" ? "Tidak" : ""} onChange={(e) => onChange(e.target.value)}>
      <option value="">— pilih —</option>
      <option value="Ya">Ya</option>
      <option value="Tidak">Tidak</option>
    </select>
  </Field>;
}

function Section({ title, subtitle, children, actions }) {
  return <section className="lpdh-form-section">
    <div className="lpdh-form-section-head">
      <div><h3>{title}</h3>{subtitle && <p>{subtitle}</p>}</div>
      {actions && <div className="lpdh-inline-actions">{actions}</div>}
    </div>
    {children}
  </section>;
}

// Only the visible section mounts; all editable values stay in the parent form.
function FormTabs({ label, defaultTab, children, issueTarget }) {
  const sections = React.Children.toArray(children);
  const [selected, setSelected] = useState(defaultTab || sections[0].props.tabKey);
  const id = useId();
  const buttons = useRef({});
  const container = useRef(null);
  useEffect(()=>{if(issueTarget?.tab)setSelected(issueTarget.tab);},[issueTarget]);
  useEffect(()=>{
    if(!issueTarget || selected!==issueTarget.tab || !container.current)return;
    const fields=(issueTarget.fields||[]).map(x=>x.toLowerCase());
    const elements=[...container.current.querySelectorAll('td[data-label],label')].filter(el=>fields.some(field=>(el.getAttribute('data-label')||el.querySelector('span')?.textContent||'').toLowerCase().includes(field)));
    elements.forEach(el=>el.classList.add('lpdh-issue-focus'));
    const target=elements.find(el=>{const input=el.querySelector('input,select');return input&&(!input.value||input.value==='Tidak');})||elements[0];
    (target?.querySelector('input,select')||buttons.current[selected])?.focus();
    target?.scrollIntoView?.({block:'center',behavior:'smooth'});
    return()=>elements.forEach(el=>el.classList.remove('lpdh-issue-focus'));
  },[issueTarget,selected]);
  const active = sections.find(section => section.props.tabKey === selected) || sections[0];
  const selectWithKeyboard = (event, index) => {
    const keys = { ArrowRight: (index + 1) % sections.length, ArrowLeft: (index + sections.length - 1) % sections.length, Home: 0, End: sections.length - 1 };
    if (!(event.key in keys)) return;
    event.preventDefault();
    const key = sections[keys[event.key]].props.tabKey;
    setSelected(key);
    buttons.current[key]?.focus();
  };
  return <div className="lpdh-form-tabs-layout" ref={container}>
    <div className="lpdh-form-tabs" role="tablist" aria-label={label}>
      {sections.map((section, index) => {
        const { tabKey, tabLabel } = section.props;
        const isActive = active.props.tabKey === tabKey;
        return <button key={tabKey} ref={node => { buttons.current[tabKey] = node; }} type="button" role="tab"
          id={`${id}-tab-${tabKey}`} aria-controls={`${id}-panel-${tabKey}`} aria-selected={isActive}
          tabIndex={isActive ? 0 : -1} className={isActive ? "active" : ""}
          onClick={() => setSelected(tabKey)} onKeyDown={event => selectWithKeyboard(event, index)}>{tabLabel}</button>;
      })}
    </div>
    <div role="tabpanel" tabIndex={0} id={`${id}-panel-${active.props.tabKey}`} aria-labelledby={`${id}-tab-${active.props.tabKey}`}>
      {active}
    </div>
  </div>;
}

function nodeText(node) {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (!React.isValidElement(node)) return "";
  return React.Children.toArray(node.props.children).map(nodeText).join("");
}

// One table/one set of controls: desktop columns become labelled mobile cards.
function searchableText(node) {
  if (!React.isValidElement(node)) return nodeText(node);
  if (["input", "select"].includes(node.type)) return String(node.props.value ?? "");
  return React.Children.toArray(node.props.children).map(searchableText).join(" ");
}

function FormTable({ children, className, searchLabel, locked = false }) {
  const [query, setQuery] = useState("");
  const searchId = useId();
  const parts = React.Children.toArray(children);
  const head = parts.find(part => part.type === "thead");
  const headings = React.Children.toArray(React.Children.toArray(head?.props.children)[0]?.props.children).map(cell => nodeText(cell) || "Tindakan");
  const terms = query.trim().toLocaleLowerCase("id-ID").split(/\s+/).filter(Boolean);
  let rowCount = 0, matchCount = 0;
  const labelled = parts.map(part => part.type !== "tbody" ? part : React.cloneElement(part, {},
    React.Children.map(part.props.children, (row, rowIndex) => {
      if (!React.isValidElement(row) || row.type !== "tr") return row;
      rowCount++;
      const text = searchableText(row).toLocaleLowerCase("id-ID");
      if (!terms.every(term => text.includes(term))) return null;
      matchCount++;
      return React.cloneElement(row, {}, React.Children.map(row.props.children, (cell, columnIndex) => {
        if (!React.isValidElement(cell)) return cell;
        const label = headings[columnIndex] || "Tindakan";
        const controls = React.Children.map(cell.props.children, control => {
          if (!React.isValidElement(control) || !["input", "select", "button"].includes(control.type)) return control;
          return React.cloneElement(control, { "aria-label": control.props["aria-label"] || `${control.type === "button" && !nodeText(control) ? "Hapus" : label} · baris ${rowIndex + 1}` });
        });
        return React.cloneElement(cell, { "data-label": label }, controls);
      }));
    })));
  const table = <table className={`${className} lpdh-responsive-form-table`}>{labelled}</table>;
  return <>
    {searchLabel && <div className="lpdh-table-search">
      <label htmlFor={searchId}>{searchLabel}</label>
      <input id={searchId} type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Ketik nama, kode, atau kategori…" />
      <span role="status">{matchCount} dari {rowCount} baris</span>
      {query && <button type="button" onClick={() => setQuery("")}>Hapus pencarian</button>}
      {rowCount > 0 && matchCount === 0 && <p>Tidak ada hasil. Coba kata lain; data tetap tersimpan.</p>}
    </div>}
    {locked ? <fieldset disabled style={{ border: 0, padding: 0, margin: 0 }}>{table}</fieldset> : table}
  </>;
}

function EmptyRow({ colSpan, children = "Belum ada data." }) {
  return <tr><td className="lpdh-empty-cell" colSpan={colSpan}>{children}</td></tr>;
}

export function normalizeMasters(value = {}) {
  const data = clone(value || {}) || {};
  data.identity = data.identity || {};
  data.signers = Array.isArray(data.signers) ? data.signers : [];
  const signerTypes = ["NIK", "NIP", "NIK"];
  while (data.signers.length < 3) {
    const index = data.signers.length;
    data.signers.push({ name: "", identityType: signerTypes[index], identityNumber: "", signed: "Tidak" });
  }
  data.signers = data.signers.slice(0, 3).map((row, index) => ({
    ...row,
    identityType: signerTypes[index],
  }));
  data.beneficiaries = Array.isArray(data.beneficiaries) ? data.beneficiaries : [];
  data.schools = Array.isArray(data.schools) ? data.schools : [];
  data.posyandu = Array.isArray(data.posyandu) ? data.posyandu : [];
  data.groupTargets = data.groupTargets || {};
  data.volunteers = Array.isArray(data.volunteers) ? data.volunteers : [];
  data.operations = Array.isArray(data.operations) ? data.operations : [];
  data.vendor = data.vendor || {};
  data.assets = data.assets || {};
  data.dailyDefaults = data.dailyDefaults || {};
  data.parameters = { ...DEFAULT_PARAMETERS, ...(data.parameters || {}) };
  return data;
}

export function aggregateMasterTargets(masters = {}) {
  const totals = Object.fromEntries(GROUP_DEFAULTS.map(group => [group.code, 0]));
  const active = row => !["nonaktif", "inactive"].includes(String(row.status || "Aktif").trim().toLowerCase());
  const codes = { PAUD: ["KS-01", null], "SD/MI": ["KS-02", "KS-03"], "SMP/MTs": [null, "KS-04"], "SMA/MA/SMK/SLB": [null, "KS-05"], Santri: [null, "KS-06"], PTK: [null, "PTK"] };
  (masters.schools || []).filter(active).forEach(row => {
    const [small, large] = codes[row.schoolType] || [];
    if (small) totals[small] += Number(row.smallPortions) || 0;
    if (large) totals[large] += Number(row.largePortions) || 0;
    totals.PTK += Number(row.staffLarge) || 0;
  });
  (masters.posyandu || []).filter(active).forEach(row => {
    totals["KS-09"] += Number(row.balitaSmall) || 0;
    totals["KS-07"] += Number(row.pregnantLarge) || 0;
    totals["KS-08"] += Number(row.breastfeedingLarge) || 0;
  });
  return totals;
}

export function normalizeDaily(value = {}, serviceDate = "") {
  const data = clone(value || {}) || {};
  data.pm = data.pm || {};
  data.pm.production = data.pm.production || {};
  const supplied = Array.isArray(data.pm.rows) ? data.pm.rows : [];
  const byCode = Object.fromEntries(supplied.map((x) => [String(x.code || x.groupCode || "").toUpperCase(), x]));
  data.pm.rows = GROUP_DEFAULTS.map((group) => ({ ...group, ...(byCode[group.code] || {}), code: group.code }));
  data.pm.rows = defaultBastRows(data.pm.rows,serviceDate,data._historicalGeneratedSnapshot);
  data.rawMaterials = Array.isArray(data.rawMaterials) ? data.rawMaterials : [];
  data.operations = Array.isArray(data.operations) ? data.operations : [];
  data.volunteerPayments = Array.isArray(data.volunteerPayments) ? data.volunteerPayments : [];
  data.incentiveRecipients = Array.isArray(data.incentiveRecipients) ? data.incentiveRecipients : [];
  data.incentive = data.incentive || {};
  data.incentive.eligibility = data.incentive.eligibility || {};
  data.balance = data.balance || {};
  data.topups = Array.isArray(data.topups) ? data.topups : [];
  data.topupProposal = data.topupProposal || {};
  data.upload = data.upload || {};
  data.dayStatus = data.dayStatus || "HPE";
  data.hpeNumber = data.hpeNumber || 1;
  data._serviceDate = serviceDate;
  return data;
}

export function productionBreakdown(daily = {}) {
  const production = daily.pm?.production || {};
  const parts = {
    distributed: (daily.pm?.rows || []).reduce((sum, row) => sum + (Number(row.distributed) || 0), 0),
    organoleptic: Number(production.organoleptic) || 0,
    retainedSample: Number(production.retainedSample) || 0,
    notDistributed: Number(production.notDistributed) || 0,
    buffer: Number(production.buffer) || 0,
  };
  return { ...parts, total: Object.values(parts).reduce((sum, value) => sum + value, 0) };
}

export function syncDailyMasterTargets(value, masters, serviceDate) {
  const data = normalizeDaily(value, serviceDate);
  if (data._historicalGeneratedSnapshot) return data;
  const targets = aggregateMasterTargets(masters);
  data.pm.rows = data.pm.rows.map(row => {
    const next = { ...row, targetPm: targets[row.code] };
    for (const field of ["distributed", "received"]) if (next[field] == null || next[field] === "") next[field] = targets[row.code];
    if (next.bnba == null || next.bnba === "") next.bnba = "Ya";
    if (!String(next.bastNo || "").trim()) next.bastNo = `DRAFT-WAJIB-DIGANTI/${serviceDate}/${row.code}`;
    if (!String(next.bastLink || "").trim()) next.bastLink = `https://example.invalid/BAST-DRAFT-WAJIB-DIGANTI/${serviceDate}/${row.code}`;
    return next;
  });
  for (const [field, defaultValue] of [["organoleptic", 3], ["retainedSample", 2]]) {
    if (data.pm.production[field] == null || data.pm.production[field] === "") data.pm.production[field] = defaultValue;
  }
  if (data.pm.production.produced == null || data.pm.production.produced === "") data.pm.production.produced = productionBreakdown(data).total;
  return data;
}

export function rawFromFinalPlan(finalPlan, serviceDate) {
  const shopping = finalPlan?.payload?.shoppingListJSON?.shoppingList || [];
  return shopping.slice(0, 40).map((item) => ({
    date: serviceDate,
    name: item.item || item.name || item.source_ingredient || "",
    category: item.category || item.supplier_category || "",
    qty: Number(item.jumlah ?? item.qty ?? 0) || 0,
    unit: item.satuan || item.unit || "",
    price: Number(item.harga_satuan ?? item.price ?? 0) || 0,
    supplier: item.supplier || item.vendor || "",
    invoiceNo: "",
    evidenceLink: "",
    note: item.note || "",
    source: "FINAL_KALKULATOR",
  })).filter((row) => row.name);
}

export function MasterPanel({ site, masters, setMasters, api, onSaved, onReload, issueTarget }) {
  const fileRef = useRef(null);
  const officialTemplateRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [officialTemplate, setOfficialTemplate] = useState({ installed: false, filename: "" });
  const [uploadingAssets, setUploadingAssets] = useState(0);
  const assetReads = useRef({});
  useEffect(() => () => { Object.values(assetReads.current).forEach(reader => reader.abort()); assetReads.current = {}; }, [site]);
  const data = normalizeMasters(masters);

  useEffect(() => {
    let cancelled = false;
    api.officialTemplateStatus(site).then((result) => {
      if (!cancelled) setOfficialTemplate(result || { installed: false, filename: "" });
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [api, site]);

  const updateIdentity = (key, value) => setMasters({ ...data, identity: { ...data.identity, [key]: value } });
  const updateParameter = (key, value) => setMasters({ ...data, parameters: { ...data.parameters, [key]: value } });
  const updateVendor = (key, value) => setMasters({ ...data, vendor: { ...data.vendor, [key]: value } });
  const updateAsset = (key, value) => setMasters(current => {
    const latest = normalizeMasters(current);
    return { ...latest, assets: { ...latest.assets, [key]: value } };
  });
  const updateSigner = (index, key, value) => {
    const signers = clone(data.signers);
    signers[index] = { ...signers[index], [key]: value };
    setMasters({ ...data, signers });
  };
  const updateList = (name, index, key, value) => {
    const list = clone(data[name]);
    list[index] = { ...list[index], [key]: value };
    setMasters({ ...data, [name]: list });
  };
  const addList = (name, row) => setMasters({ ...data, [name]: [...data[name], row] });
  const deleteList = (name, index) => setMasters({ ...data, [name]: data[name].filter((_, i) => i !== index) });

  const save = async () => {
    setBusy(true);
    try {
      await api.saveMasters(site, data);
      await onReload?.();
      onSaved?.("Master data tersimpan di cloud.");
    } catch (error) { onSaved?.(error.message || "Master gagal disimpan", "error");
    } finally { setBusy(false); }
  };

  const downloadTemplate = async () => {
    setBusy(true);
    try {
      const result = await api.masterTemplate(site);
      downloadBase64(result.filename, result.mimeType, result.contentBase64);
    } finally { setBusy(false); }
  };

  const importFile = async (file) => {
    if (!file) return;
    setBusy(true);
    try {
      const contentBase64 = arrayBufferToBase64(await file.arrayBuffer());
      const result = await api.importMaster(site, file.name, contentBase64);
      onSaved?.(`Import ditambahkan: ${result.imported.schools || 0} sekolah, ${result.imported.posyandu || 0} posyandu, ${result.imported.beneficiaries || 0} penerima lama, ${result.imported.volunteers || 0} relawan, ${result.imported.operations || 0} operasional; ${result.groupTargets || 0} total kelompok. ${result.warnings?.length ? "Identitas berbeda: isian aplikasi dipertahankan. " + result.warnings.join("; ") : "Isian lama tidak ditimpa."}`);
      await onReload?.();
    } catch (error) {
      onSaved?.(error.message || "Import gagal", "error");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const uploadOfficialTemplate = async (file) => {
    if (!file) return;
    setBusy(true);
    try {
      const contentBase64 = arrayBufferToBase64(await file.arrayBuffer());
      const result = await api.saveOfficialTemplate(site, file.name, contentBase64);
      setOfficialTemplate(result);
      onSaved?.(`Template resmi ${file.name} terpasang. Generate berikutnya akan memakai workbook ini beserta rumus dan formatnya.`);
    } catch (error) {
      onSaved?.(error.message || "Template resmi gagal dipasang.", "error");
    } finally {
      setBusy(false);
      if (officialTemplateRef.current) officialTemplateRef.current.value = "";
    }
  };

  const uploadImageAsset = (key, file) => {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      onSaved?.("Gambar maksimal 5 MB per file. Gunakan PNG/JPG/WebP.", "error");
      return;
    }
    const reader = new FileReader();
    assetReads.current[key]?.abort();
    assetReads.current[key] = reader;
    setUploadingAssets(count => count + 1);
    reader.onload = () => {
      if (assetReads.current[key] !== reader) return;
      updateAsset(key, String(reader.result || ""));
      onSaved?.("Gambar sudah dimuat. Klik Simpan Semua Master agar dipakai pada PDF.");
    };
    reader.onerror = () => onSaved?.("Gambar gagal dibaca. Pilih ulang PNG/JPG/WebP.", "error");
    reader.onloadend = () => {
      if (assetReads.current[key] === reader) delete assetReads.current[key];
      setUploadingAssets(count => Math.max(0, count - 1));
    };
    reader.readAsDataURL(file);
  };

  return <div className="lpdh-stack lpdh-tabbed-form">
    <Section title="Master Data LPDH" subtitle="Diisi sekali, lalu dipakai ulang untuk seluruh hari pelayanan." actions={<>
      <button type="button" onClick={downloadTemplate} disabled={busy}><Download size={15}/> Template Excel</button>
      <button type="button" onClick={() => fileRef.current?.click()} disabled={busy}><FileUp size={15}/> Import Master</button>
      <input ref={fileRef} hidden type="file" accept=".xlsx" onChange={(e) => importFile(e.target.files?.[0])} />
      <button type="button" onClick={() => officialTemplateRef.current?.click()} disabled={busy}><FileUp size={15}/> Template LPDH Resmi</button>
      <input ref={officialTemplateRef} hidden type="file" accept=".xlsx" onChange={(e) => uploadOfficialTemplate(e.target.files?.[0])} />
      <button type="button" className="primary" onClick={save} disabled={busy || uploadingAssets > 0}><Save size={15}/> Simpan Master</button>
    </>}>
      <div className="lpdh-note">Master tersimpan per dapur. Akun YAYASAN dapat mengelola Maja dan Cemplang; akun dapur hanya site sendiri.</div>
      <div className={officialTemplate.installed ? "lpdh-status-box ok" : "lpdh-status-box warn"} style={{ marginTop: 10 }}>
        <strong>{officialTemplate.installed ? "Template resmi terpasang" : "Template resmi belum diunggah"}</strong>
        <span>{officialTemplate.installed ? `${officialTemplate.filename} · Unduhan mengisi sel input kuning pada salinan template server; rumus dan format tetap ikut. Template baru dapat diunggah lewat tombol Template LPDH Resmi dan diperiksa sebelum mengganti acuan.` : "Unggah workbook LPDH lengkap lewat Template LPDH Resmi. Unduhan mengisi salinan template server, bukan membuat rumus dari awal. Import Master hanya mengisi data master, bukan memasang format output."}</span>
      </div>
    </Section>

    <FormTabs key={site} label="Bagian Master Data" defaultTab="schools" issueTarget={issueTarget}>
    <Section tabKey="identity" tabLabel="Identitas" title="Identitas SPPG & Rekening">
      <div className="lpdh-form-grid">
        <Field label="ID SPPG" value={data.identity.sppgId} onChange={(v) => updateIdentity("sppgId", v)} />
        <Field label="Nama SPPG" value={data.identity.sppgName} onChange={(v) => updateIdentity("sppgName", v)} />
        <Field label="Yayasan" value={data.identity.foundation} onChange={(v) => updateIdentity("foundation", v)} />
        <Field label="Desa/Kelurahan" value={data.identity.village} onChange={(v) => updateIdentity("village", v)} />
        <Field label="Kecamatan" value={data.identity.district} onChange={(v) => updateIdentity("district", v)} />
        <Field label="Kabupaten/Kota" value={data.identity.city} onChange={(v) => updateIdentity("city", v)} />
        <Field label="Provinsi" value={data.identity.province} onChange={(v) => updateIdentity("province", v)} />
        <Field label="Nomor VA" value={data.identity.vaNumber} onChange={(v) => updateIdentity("vaNumber", v)} />
        <Field label="Bank" value={data.identity.bankName} onChange={(v) => updateIdentity("bankName", v)} />
      </div>
    </Section>

    <Section tabKey="vendor" tabLabel="Vendor & Aset" title="Master Vendor & Aset Invoice" subtitle="Dipakai saat preview/cetak invoice. Layout persis akan mengikuti contoh invoice yang Anda kirim; data dan asetnya sudah disiapkan.">
      <div className="lpdh-form-grid">
        <Field label="Nama vendor / koperasi" value={data.vendor.name} onChange={(v) => updateVendor("name", v)} />
        <Field label="Alamat vendor" value={data.vendor.address} onChange={(v) => updateVendor("address", v)} />
        <Field label="No. HP / kontak" value={data.vendor.phone} onChange={(v) => updateVendor("phone", v)} />
        <Field label="NPWP / identitas" value={data.vendor.taxId} onChange={(v) => updateVendor("taxId", v)} />
        <Field label="Prefix invoice bahan" value={data.vendor.rawInvoicePrefix} onChange={(v) => updateVendor("rawInvoicePrefix", v)} placeholder="mis. INV/BB/" />
        <Field label="Prefix invoice operasional" value={data.vendor.operationalInvoicePrefix} onChange={(v) => updateVendor("operationalInvoicePrefix", v)} placeholder="mis. INV/OP/" />
        <Field label="Nama penandatangan invoice" value={data.vendor.signatoryName} onChange={(v) => updateVendor("signatoryName", v)} />
      </div>
      <div className="lpdh-asset-grid">
        <label className="lpdh-asset-upload"><span>Tanda tangan vendor</span><input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e)=>uploadImageAsset("vendorSignature",e.target.files?.[0])}/>{data.assets.vendorSignature && <img src={data.assets.vendorSignature} alt="Preview tanda tangan vendor"/>}</label>
        <label className="lpdh-asset-upload"><span>Stempel vendor</span><input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e)=>uploadImageAsset("vendorStamp",e.target.files?.[0])}/>{data.assets.vendorStamp && <img src={data.assets.vendorStamp} alt="Preview stempel vendor"/>}</label>
        <label className="lpdh-asset-upload"><span>Logo vendor</span><input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e)=>uploadImageAsset("vendorLogo",e.target.files?.[0])}/>{data.assets.vendorLogo && <img src={data.assets.vendorLogo} alt="Preview logo vendor"/>}</label>
      </div>
    </Section>

    <Section tabKey="signers" tabLabel="Pengesah" title="Pengesah" subtitle="Tiga baris ini dipakai juga pada J_Pengesahan.">
      <div className="lpdh-asset-grid">
        {[["approvalFinanceSignature","TTD Pengawas Keuangan"],["approvalSppgSignature","TTD Kepala SPPG"],["approvalFoundationSignature","TTD Yayasan"],["approvalSppgStamp","Stempel SPPG"],["approvalFoundationStamp","Stempel Yayasan"]].map(([key,label])=><label key={key} className="lpdh-asset-upload"><span>{label}</span><input type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>uploadImageAsset(key,e.target.files?.[0])}/>{data.assets[key]&&<img src={data.assets[key]} alt={label}/>}</label>)}
      </div>
      <div className="lpdh-table-wrap"><FormTable className="lpdh-data-table"><thead><tr><th>Peran</th><th>Nama</th><th>Jenis ID</th><th>Nomor ID</th><th>Ditandatangani</th></tr></thead>
        <tbody>{data.signers.slice(0, 3).map((row, index) => <tr key={index}>
          <td>{["Pengawas Keuangan SPPG","Kepala SPPG","Perwakilan Mitra/Yayasan"][index]}</td>
          <td><input value={row.name || ""} onChange={(e) => updateSigner(index, "name", e.target.value)} /></td>
          <td><input value={["NIK","NIP","NIK"][index]} disabled /></td>
          <td><input value={row.identityNumber || ""} onChange={(e) => updateSigner(index, "identityNumber", e.target.value)} /></td>
          <td><select value={row.signed || "Tidak"} onChange={(e) => updateSigner(index, "signed", e.target.value)}><option>Ya</option><option>Tidak</option></select></td>
        </tr>)}</tbody></FormTable></div>
    </Section>

    <Section tabKey="schools" tabLabel="Sekolah" title="Master Sekolah" subtitle="Kolom F = porsi kecil; G = porsi besar. SD kelas 1–3 kecil, kelas 4–6 besar; PAUD kecil; SMP/SMA/Santri/PTK besar." actions={<button type="button" onClick={() => addList("schools", { code: "", name: "", schoolType: "SD/MI", smallPortions: 0, largePortions: 0, status: "Aktif" })}><Plus size={15}/> Tambah sekolah</button>}>
      <div className="lpdh-table-wrap"><FormTable searchLabel="Cari sekolah" className="lpdh-data-table wide"><thead><tr><th>Kode</th><th>Nama Sekolah</th><th>Jenis</th><th>Porsi Kecil (F)</th><th>Porsi Besar (G)</th><th>Tenaga Pendidik Besar (H)</th><th>PIC</th><th>Telepon</th><th>Alamat</th><th>Status</th><th/></tr></thead><tbody>
        {data.schools.map((row, index) => <tr key={index}>
          <td><input value={row.code || ""} onChange={e => updateList("schools", index, "code", e.target.value)}/></td>
          <td><input value={row.name || ""} onChange={e => updateList("schools", index, "name", e.target.value)}/></td>
          <td><select value={row.schoolType || "SD/MI"} onChange={e => { const list = clone(data.schools); list[index] = { ...row, schoolType: e.target.value, smallPortions: ["PAUD", "SD/MI"].includes(e.target.value) ? row.smallPortions : 0, largePortions: e.target.value === "PAUD" ? 0 : row.largePortions }; setMasters({ ...data, schools: list }); }}>{["PAUD", "SD/MI", "SMP/MTs", "SMA/MA/SMK/SLB", "Santri", "PTK"].map(t => <option key={t}>{t}</option>)}</select></td>
          <td><input aria-label={`Porsi kecil sekolah ${index + 1}`} type="number" min="0" step="1" disabled={!["PAUD", "SD/MI"].includes(row.schoolType)} value={row.smallPortions ?? ""} onChange={e => updateList("schools", index, "smallPortions", numValue(e.target.value))}/></td>
          <td><input aria-label={`Porsi besar sekolah ${index + 1}`} type="number" min="0" step="1" disabled={row.schoolType === "PAUD"} value={row.largePortions ?? ""} onChange={e => updateList("schools", index, "largePortions", numValue(e.target.value))}/></td>
          <td><input aria-label={`Tenaga pendidik sekolah ${index + 1}`} type="number" min="0" step="1" value={row.staffLarge ?? ""} onChange={e => updateList("schools", index, "staffLarge", numValue(e.target.value))}/></td>
          {["picName", "phone", "address"].map(key => <td key={key}><input value={row[key] || ""} onChange={e => updateList("schools", index, key, e.target.value)}/></td>)}
          <td><select value={row.status || "Aktif"} onChange={e => updateList("schools", index, "status", e.target.value)}><option>Aktif</option><option>Nonaktif</option></select></td>
          <td><button type="button" className="icon danger" onClick={() => deleteList("schools", index)}><Trash2 size={14}/></button></td>
        </tr>)}{!data.schools.length && <EmptyRow colSpan={11}/>}</tbody></FormTable></div>
    </Section>

    <Section tabKey="posyandu" tabLabel="Posyandu" title="Master Posyandu" subtitle="Balita 6–59 bulan selalu kecil; ibu hamil dan ibu menyusui selalu besar." actions={<button type="button" onClick={() => addList("posyandu", { code: "", name: "", balitaSmall: 0, pregnantLarge: 0, breastfeedingLarge: 0, status: "Aktif" })}><Plus size={15}/> Tambah posyandu</button>}>
      <div className="lpdh-table-wrap"><FormTable searchLabel="Cari posyandu" className="lpdh-data-table wide"><thead><tr><th>Kode</th><th>Nama Posyandu</th><th>Balita Kecil</th><th>Ibu Hamil Besar</th><th>Ibu Menyusui Besar</th><th>Kader</th><th>Telepon</th><th>Alamat</th><th>Status</th><th/></tr></thead><tbody>
        {data.posyandu.map((row, index) => <tr key={index}>
          {["code", "name"].map(key => <td key={key}><input value={row[key] || ""} onChange={e => updateList("posyandu", index, key, e.target.value)}/></td>)}
          {["balitaSmall", "pregnantLarge", "breastfeedingLarge"].map(key => <td key={key}><input type="number" min="0" step="1" value={row[key] ?? ""} onChange={e => updateList("posyandu", index, key, numValue(e.target.value))}/></td>)}
          {["picName", "phone", "address"].map(key => <td key={key}><input value={row[key] || ""} onChange={e => updateList("posyandu", index, key, e.target.value)}/></td>)}
          <td><select value={row.status || "Aktif"} onChange={e => updateList("posyandu", index, "status", e.target.value)}><option>Aktif</option><option>Nonaktif</option></select></td>
          <td><button type="button" className="icon danger" onClick={() => deleteList("posyandu", index)}><Trash2 size={14}/></button></td>
        </tr>)}{!data.posyandu.length && <EmptyRow colSpan={10}/>}</tbody></FormTable></div>
    </Section>

    <Section tabKey="totals" tabLabel="Total Porsi" title="Total Kelompok dari Master Sekolah & Posyandu" subtitle="Jumlah otomatis dari sekolah dan posyandu aktif. Tenaga pendidik masuk PTK besar. Total impor lama disimpan sebagai riwayat.">
      <div className="lpdh-form-grid">{GROUP_DEFAULTS.map(group => <Field key={group.code} label={`${group.label} · ${group.portion}`} type="number" disabled value={aggregateMasterTargets(data)[group.code]}/>)}<Field label="Total seluruh kelompok" type="number" disabled value={Object.values(aggregateMasterTargets(data)).reduce((sum, n) => sum + n, 0)}/></div>
    </Section>

    <Section tabKey="legacy" tabLabel="Data Lama" title="Master Penerima Lama" subtitle="Data format lama tetap dapat dipakai. Untuk data baru gunakan tab Sekolah dan Posyandu." actions={
      <button type="button" onClick={() => addList("beneficiaries", { code: "", unitType: "Sekolah", unitName: "", groupCode: "KS-01", groupName: "", portionCategory: "Kecil", picType: "Sekolah", targetPm: 0, picName: "", phone: "", address: "", status: "Aktif", note: "" })}><Plus size={15}/> Tambah</button>
    }>
      <div className="lpdh-table-wrap"><FormTable searchLabel="Cari penerima lama" className="lpdh-data-table wide"><thead><tr><th>Kode Unit</th><th>Jenis</th><th>Nama Unit</th><th>Kode Kelompok</th><th>Target PM</th><th>PIC</th><th>Status</th><th></th></tr></thead>
        <tbody>{data.beneficiaries.map((row, index) => <tr key={index}>
          <td><input value={row.code || ""} onChange={(e) => updateList("beneficiaries", index, "code", e.target.value)} /></td>
          <td><select value={row.unitType || "Sekolah"} onChange={(e) => updateList("beneficiaries", index, "unitType", e.target.value)}><option>Sekolah</option><option>Posyandu</option></select></td>
          <td><input value={row.unitName || ""} onChange={(e) => updateList("beneficiaries", index, "unitName", e.target.value)} /></td>
          <td><select value={row.groupCode || ""} onChange={(e) => updateList("beneficiaries", index, "groupCode", e.target.value)}><option value="">—</option>{GROUP_DEFAULTS.map((g) => <option key={g.code} value={g.code}>{g.code} · {g.label}</option>)}</select></td>
          <td><input type="number" value={row.targetPm ?? ""} onChange={(e) => updateList("beneficiaries", index, "targetPm", numValue(e.target.value))} /></td>
          <td><input value={row.picName || ""} onChange={(e) => updateList("beneficiaries", index, "picName", e.target.value)} /></td>
          <td><select value={row.status || "Aktif"} onChange={(e) => updateList("beneficiaries", index, "status", e.target.value)}><option>Aktif</option><option>Nonaktif</option></select></td>
          <td><button className="icon danger" type="button" onClick={() => deleteList("beneficiaries", index)}><Trash2 size={14}/></button></td>
        </tr>)}{!data.beneficiaries.length && <EmptyRow colSpan={8}/>}</tbody></FormTable></div>
    </Section>

    <Section tabKey="volunteers" tabLabel="Relawan" title="Master Relawan" subtitle={`${data.volunteers.length} relawan. Tarif harian dipakai otomatis pada C1_Relawan.`} actions={
      <button type="button" onClick={() => addList("volunteers", { code: `RL-${String(data.volunteers.length + 1).padStart(3, "0")}`, name: "", role: "", status: "Aktif", dailyRate: 90000, paymentMethod: "Transfer" })}><Plus size={15}/> Tambah</button>
    }>
      <div className="lpdh-table-wrap"><FormTable searchLabel="Cari relawan" className="lpdh-data-table wide"><thead><tr><th>Kode</th><th>Nama</th><th>Tugas</th><th>Tarif/Hari</th><th>Metode</th><th>Bank/Rekening</th><th>Status</th><th></th></tr></thead>
        <tbody>{data.volunteers.map((row, index) => <tr key={index}>
          <td><input value={row.code || ""} onChange={(e) => updateList("volunteers", index, "code", e.target.value)} /></td>
          <td><input value={row.name || ""} onChange={(e) => updateList("volunteers", index, "name", e.target.value)} /></td>
          <td><input value={row.role || ""} onChange={(e) => updateList("volunteers", index, "role", e.target.value)} /></td>
          <td><input type="number" value={row.dailyRate ?? ""} onChange={(e) => updateList("volunteers", index, "dailyRate", numValue(e.target.value))} /></td>
          <td><select value={row.paymentMethod || "Transfer"} onChange={(e) => updateList("volunteers", index, "paymentMethod", e.target.value)}><option>Transfer</option><option>Tunai</option><option>Lainnya</option></select></td>
          <td><input value={[row.bankName, row.accountNumber].filter(Boolean).join(" / ")} onChange={(e) => updateList("volunteers", index, "accountNumber", e.target.value)} placeholder="rekening" /></td>
          <td><select value={row.status || "Aktif"} onChange={(e) => updateList("volunteers", index, "status", e.target.value)}><option>Aktif</option><option>Nonaktif</option></select></td>
          <td><button className="icon danger" type="button" onClick={() => deleteList("volunteers", index)}><Trash2 size={14}/></button></td>
        </tr>)}{!data.volunteers.length && <EmptyRow colSpan={8}/>}</tbody></FormTable></div>
    </Section>

    <Section tabKey="operations" tabLabel="Operasional" title="Master Bahan Operasional" actions={<button type="button" onClick={() => addList("operations", { code: `OP-${String(data.operations.length + 1).padStart(3, "0")}`, name: "", category: "Operasional", unit: "unit", defaultPrice: 0, costNature: "Rutin", vendor: "", status: "Aktif" })}><Plus size={15}/> Tambah</button>}>
      <div className="lpdh-table-wrap"><FormTable searchLabel="Cari item operasional" className="lpdh-data-table wide"><thead><tr><th>Kode</th><th>Item</th><th>Kategori</th><th>Satuan</th><th>Harga Default</th><th>Sifat</th><th>Vendor</th><th>Status</th><th></th></tr></thead>
        <tbody>{data.operations.map((row, index) => <tr key={index}>
          <td><input value={row.code || ""} onChange={(e) => updateList("operations", index, "code", e.target.value)} /></td>
          <td><input value={row.name || ""} onChange={(e) => updateList("operations", index, "name", e.target.value)} /></td>
          <td><input value={row.category || ""} onChange={(e) => updateList("operations", index, "category", e.target.value)} /></td>
          <td><input value={row.unit || ""} onChange={(e) => updateList("operations", index, "unit", e.target.value)} /></td>
          <td><input type="number" value={row.defaultPrice ?? ""} onChange={(e) => updateList("operations", index, "defaultPrice", numValue(e.target.value))} /></td>
          <td><select value={row.costNature || "Rutin"} onChange={(e) => updateList("operations", index, "costNature", e.target.value)}><option>Rutin</option><option>Insidental</option></select></td>
          <td><input value={row.vendor || ""} onChange={(e) => updateList("operations", index, "vendor", e.target.value)} /></td>
          <td><select value={row.status || "Aktif"} onChange={(e) => updateList("operations", index, "status", e.target.value)}><option>Aktif</option><option>Nonaktif</option></select></td>
          <td><button className="icon danger" type="button" onClick={() => deleteList("operations", index)}><Trash2 size={14}/></button></td>
        </tr>)}{!data.operations.length && <EmptyRow colSpan={9}/>}</tbody></FormTable></div>
    </Section>

    <Section tabKey="parameters" tabLabel="Parameter" title="Parameter Ref / Pagu" subtitle="Nilai ini memetakan parameter utama pada sheet Ref.">
      <h4>Nilai awal pilihan harian</h4>
      <p>Dipakai untuk pilihan yang belum diisi pada dapur ini. Periksa sesuai kejadian setiap hari; nilai awal bukan bukti verifikasi atau pengiriman SIPGN. Saldo, nomor transaksi, dan link bukti tidak disalin.</p>
      <div className="lpdh-form-grid">
        {[["contamination","Default ada kontaminasi?"],["fatalIncident","Default ada insiden fatal?"],["suspended","Default SPPG disuspend?"],["verified","Default sudah diverifikasi?"],["pmInputSipgn","Default PM sudah masuk SIPGN?"]].map(([key,label]) => <YesNo key={key} label={label} value={data.dailyDefaults.incentiveEligibility?.[key]} onChange={value=>setMasters(current=>({...current,dailyDefaults:{...(current.dailyDefaults||{}),incentiveEligibility:{...(current.dailyDefaults?.incentiveEligibility||{}),[key]:value}}}))}/>)}
      </div>
      <div className="lpdh-form-grid">
        <Field label="Tarif insentif / PM" type="number" value={data.parameters.incentiveTariff} onChange={(v) => updateParameter("incentiveTariff", v)} />
        <Field label="Pagu bahan porsi kecil" type="number" value={data.parameters.rawSmall} onChange={(v) => updateParameter("rawSmall", v)} />
        <Field label="Pagu bahan porsi besar" type="number" value={data.parameters.rawLarge} onChange={(v) => updateParameter("rawLarge", v)} />
        <Field label="Pagu operasional / PM" type="number" value={data.parameters.operationalPerPm} onChange={(v) => updateParameter("operationalPerPm", v)} />
        <Field label="Maksimum VA" type="number" value={data.parameters.maxVa} onChange={(v) => updateParameter("maxVa", v)} />
        <Field label="Maks HPE / minggu" type="number" value={data.parameters.maxHpePerWeek} onChange={(v) => updateParameter("maxHpePerWeek", v)} />
        <Field label="Batas upload H+1 (jam)" type="number" value={data.parameters.uploadHour} onChange={(v) => updateParameter("uploadHour", v)} />
        <Field label="Batas buffer (desimal; 0,05 = 5%)" type="number" value={data.parameters.bufferPct} onChange={(v) => updateParameter("bufferPct", v)} />
        <Field label="Toleransi tanggal transaksi (hari)" type="number" value={data.parameters.dateTolerance} onChange={(v) => updateParameter("dateTolerance", v)} />
        <Field label="Indeks kemahalan" type="number" value={data.parameters.cityIndex} onChange={(v) => updateParameter("cityIndex", v)} />
        <Field label="Sumber indeks" value={data.parameters.cityIndexSource} onChange={(v) => updateParameter("cityIndexSource", v)} />
        <YesNo label="Terapkan indeks ke bahan" value={data.parameters.applyIndexRaw ? "Ya" : "Tidak"} onChange={(v) => updateParameter("applyIndexRaw", v === "Ya")} />
        <YesNo label="Terapkan indeks ke operasional" value={data.parameters.applyIndexOp ? "Ya" : "Tidak"} onChange={(v) => updateParameter("applyIndexOp", v === "Ya")} />
      </div>
    </Section>

    </FormTabs>
    <div className="lpdh-sticky-save"><button type="button" className="primary" onClick={save} disabled={busy || uploadingAssets > 0}><Save size={16}/> Simpan Semua Master</button><button type="button" onClick={onReload} disabled={busy || uploadingAssets > 0}><RefreshCw size={16}/> Muat ulang</button></div>
  </div>;
}

export function applyRoutineDaily(daily, result, masters, serviceDate) {
  const current = normalizeDaily(daily, serviceDate);
  const pm = result.dailyDefaults?.pm || {};
  const byCode = new Map((pm.rows || []).map(row => [row.code, row]));
  const next = { ...current, lpdhNumber: current.lpdhNumber || result.lpdhNumber,
    pm: { ...current.pm, rows: current.pm.rows.map(row => ({ ...row, ...(byCode.get(row.code) || {}) })),
      production: { ...current.pm.production, ...pm.production } } };
  return syncDailyMasterTargets(next, masters, serviceDate);
}

export function DailyPanel({ site, serviceDate, masters, daily, setDaily, finalPlan, preview, api, onSaved, onPreview, onValidated, onValidationCancelled, dailySaved=false, issueTarget }) {
  const data = normalizeDaily(daily, serviceDate);
  const topupFormRef=useRef(data);
  topupFormRef.current=data;
  const displayPreview=dailySaved?preview:pendingReview(preview);
  const saldo = balanceSummary(dailySaved?data:{...data,incentive:{...data.incentive,paidAmount:0}}, displayPreview);
  const saldoMoney = value => new Intl.NumberFormat('id-ID', {style:'currency',currency:'IDR',maximumFractionDigits:0}).format(value || 0);
  const [busy, setBusy] = useState(false);
  const copyContext = useRef(`${site}|${serviceDate}`);
  copyContext.current = `${site}|${serviceDate}`;
  const masterData = normalizeMasters(masters);
  const proofGroups = evidenceGroups(data);
  const updateProofGroup = (group, field, value) => {
    if (group.conflictingFields.includes(field) && !window.confirm(`Isian ${field === "evidenceLink" ? "link bukti" : "referensi pembayaran"} pada ${group.number} berbeda antarbaris. Samakan seluruh ${group.indexes.length} baris dengan isian baru?`)) return;
    setDaily(applyEvidence(data, group, field, value));
  };

  const update = (key, value) => setDaily({ ...data, [key]: value });
  const updateNested = (parent, key, value) => {
    const nested = { ...(data[parent] || {}), [key]: value };
    if (parent === "incentive" && ["statementAmount","paidAmount"].includes(key)) nested._automaticAmounts = (nested._automaticAmounts || []).filter(field=>field !== key);
    setDaily({ ...data, [parent]: nested });
  };
  const updateProduction = (key, value) => setDaily({ ...data, pm: { ...data.pm, production: { ...data.pm.production, [key]: value } } });
  const production = productionBreakdown(data);
  const recalculateProduction = () => {
    if (data.pm.production.produced != null && data.pm.production.produced !== "" && Number(data.pm.production.produced) !== production.total
      && !window.confirm(`Ganti total produksi ${data.pm.production.produced} menjadi ${production.total} sesuai rincian isian saat ini? Perubahan belum disimpan.`)) return;
    updateProduction("produced", production.total);
  };
  const updatePmRow = (index, key, value) => {
    const rows = clone(data.pm.rows); rows[index] = { ...rows[index], [key]: value };
    setDaily({ ...data, pm: { ...data.pm, rows } });
  };
  const updateList = (name, index, key, value) => {
    if (data[name][index]?.sourceDocumentId && !["evidenceLink", "paymentReference"].includes(key)) return onSaved?.("Nilai dan nomor berasal dari dokumen FINAL yang terkunci. Link bukti masih dapat dilengkapi.", "error");
    const list = clone(data[name]); list[index] = { ...list[index], [key]: value };
    setDaily({ ...data, [name]: list });
  };
  const deleteList = (name, index) => {
    if (data[name][index]?.sourceDocumentId) return onSaved?.("Baris berasal dari dokumen FINAL dan tidak dapat dihapus dari data harian.", "error");
    setDaily({ ...data, [name]: data[name].filter((_, i) => i !== index) });
  };
  const addList = (name, row) => setDaily({ ...data, [name]: [...data[name], row] });

  const pullFinal = () => {
    if (!finalPlan?.payload) return onSaved?.("Belum ada data FINAL dari Kalkulator untuk tanggal ini.", "error");
    const payload = finalPlan.payload || {};
    setDaily({
      ...data,
      pm: {
        ...data.pm,
        production: {
          ...data.pm.production,
          produced: data.pm.production.produced || (Number(payload.porsiKecil || 0) + Number(payload.porsiBesar || 0)),
        },
      },
    });
    onSaved?.("Porsi produksi ditarik dari Final Kalkulator. Bahan dan biaya berasal dari tab Buat Invoice & Kuitansi setelah finalisasi.");
  };

  const pullDocuments = async () => {
    setBusy(true);
    try {
      await api.saveDaily(site, serviceDate, data, "DRAFT");
      const result = await api.syncDocuments(site, serviceDate);
      const next = normalizeDaily(result.data || {}, serviceDate);
      setDaily(next);
      onSaved?.(result.imported ? `${result.imported} dokumen FINAL ditarik tanpa menggandakan biaya.` : "Belum ada dokumen FINAL. Buat dan finalkan invoice/kuitansi terlebih dahulu.");
      await onPreview?.(next);
    } catch (error) { onSaved?.(error.message, "error"); }
    finally { setBusy(false); }
  };

  const prepareVolunteers = () => {
    const existing = Object.fromEntries(data.volunteerPayments.map((x) => [x.volunteerCode || x.code || x.name, x]));
    const rows = masterData.volunteers.filter((x) => String(x.status || "Aktif").toLowerCase() !== "nonaktif").map((v) => ({
      ...existing[v.code || v.name],
      volunteerCode: v.code || v.name,
      name: v.name,
      role: v.role || "",
      date: existing[v.code || v.name]?.date || data.volunteerPaymentDate || serviceDate,
      workDays: existing[v.code || v.name]?.workDays ?? 1,
      dailyRate: existing[v.code || v.name]?.dailyRate ?? v.dailyRate ?? 0,
      paymentMethod: existing[v.code || v.name]?.paymentMethod || v.paymentMethod || "Transfer",
      receiptNo: existing[v.code || v.name]?.receiptNo || "",
      evidenceLink: existing[v.code || v.name]?.evidenceLink || data.volunteerBatchEvidenceLink || "",
    }));
    setDaily({ ...data, volunteerPayments: rows });
    onSaved?.(`${rows.length} relawan aktif disiapkan untuk pembayaran.`);
  };

  const save = async () => {
    setBusy(true);
    try {
      const context=copyContext.current;
      const saved={...data,_reviewValidated:true};
      await api.saveDaily(site, serviceDate, saved, "DRAFT");
      if (context !== copyContext.current) return;
      setDaily(saved);
      await onPreview?.(saved);
      if (context !== copyContext.current) return;
      onValidated?.(saved);
      onSaved?.("Data Harian tersimpan dan validasi diperbarui. Nilai sudah masuk ke Review; periksa hasil G_CekPPK.");
    } catch(error) { onSaved?.(error.message || "Simpan & Validasi gagal. Silakan coba lagi.","error");
    } finally { setBusy(false); }
  };

  const cancelValidation = async () => {
    if (!window.confirm('Batalkan validasi tanggal ini? Isian dan dokumen FINAL tetap tersimpan. Insentif Review kembali Rp0 sampai Simpan & Validasi ulang.')) return;
    const context=copyContext.current;
    setBusy(true);
    try {
      await api.cancelDailyValidation(site,serviceDate);
      if(context!==copyContext.current)return;
      setDaily({...data,_reviewValidated:false});
      onValidationCancelled?.();
      onSaved?.('Validasi dibatalkan. Perbarui isian lalu Simpan & Validasi kembali.');
    } catch(error){onSaved?.(error.message||'Pembatalan validasi gagal.','error');}
    finally{setBusy(false);}
  };

  const pullPrevious = async () => {
    if (!window.confirm("Tarik jumlah porsi, distribusi, dan produksi hari pelayanan sebelumnya? Isian PM saat ini diganti sebagai draft yang belum disimpan. Target tetap dari master terbaru; invoice, pembayaran, bukti, BAST, serta pengesahan tidak disalin.")) return;
    const key = copyContext.current;
    setBusy(true);
    try {
      const result = await api.previousRoutine(site, serviceDate);
      if (key !== copyContext.current) return;
      if (result.targetDailyStatus === "GENERATED") throw new Error("LPDH sudah digenerate. Simpan sebagai draft dahulu sebelum menarik isian rutin.");
      if (!result.hasDaily) throw new Error("Tanggal sebelumnya belum memiliki isian Data Harian. Dokumen rutin bisa ditarik di tab Buat Invoice & Kuitansi.");
      const next = applyRoutineDaily(data, result, masters, serviceDate);
      setDaily(next);
      onSaved?.(`Isian PM ditarik dari ${result.sourceDate}, belum disimpan. Target tetap dari master terbaru; periksa jumlah porsi dan produksi lalu Simpan Draft.`);
      await onPreview?.(next);
    } finally { setBusy(false); }
  };

  const total = (rows, amountFn) => rows.reduce((s, x) => s + amountFn(x), 0);
  const rawTotal = total(data.rawMaterials, (x) => (Number(x.qty) || 0) * (Number(x.price) || 0));
  const volunteerTotal = total(data.volunteerPayments, (x) => (Number(x.workDays) || 0) * (Number(x.dailyRate) || 0));
  const opTotal = total(data.operations, (x) => (Number(x.qty) || 0) * (Number(x.price) || 0));
  const recipientTotal = total(data.incentiveRecipients, (x) => Number(x.amount) || 0);

  return <div className="lpdh-stack lpdh-tabbed-form">
    <Section title={`Data Harian · ${serviceDate}`} subtitle="Isi realisasi tanggal ini. Data tidak menimpa tanggal lain." actions={<>
      <button type="button" onClick={pullPrevious} disabled={busy}>Tarik isian hari sebelumnya</button>
      <button type="button" onClick={pullDocuments} disabled={busy}><Download size={15}/> Tarik Invoice & Kuitansi Final</button>
      <button type="button" className={dailySaved?"primary":"lpdh-save-pending"} onClick={save} disabled={busy}><Save size={15}/> Simpan & Validasi</button>
      {dailySaved&&<button type="button" onClick={cancelValidation} disabled={busy}>Batalkan Validasi</button>}
    </>}>
      <div className={finalPlan?.payload ? "lpdh-status-box ok" : "lpdh-status-box warn"}>
        <strong>{finalPlan?.payload ? "Final Kalkulator tersedia" : "Belum ada Final Kalkulator"}</strong>
        <span>{finalPlan?.payload ? `${finalPlan.planName || "Rencana"} · revisi ${finalPlan.revision || 1}` : "Finalkan rencana di Kalkulator. Buat invoice dari daftar belanja pada tab Buat Invoice & Kuitansi."}</span>
      </div>
      <div className={preview?.effective ? "lpdh-status-box ok" : "lpdh-status-box warn"} style={{ marginTop: 10 }}>
        <strong>{preview?.effective ? "Hari Pelayanan Efektif" : "Bukan Hari Pelayanan Efektif"}</strong>
        <span>{preview?.effective ? `HPE ke-${preview?.hpeNumber || 1} minggu ini · otomatis dari kalender pelayanan` : "Tanggal ini tidak dapat digenerate. Atur dari tab Hari Pelayanan Efektif."}</span>
      </div>
      <div className="lpdh-form-grid compact">
        <Field label="Nomor LPDH (otomatis, bisa diedit)" value={data.lpdhNumber} onChange={(v) => update("lpdhNumber", v)} />
        {data.volunteerReceiptBaseNo && <Field label="Nomor dasar kuitansi relawan (historis)" value={data.volunteerReceiptBaseNo} disabled />}
        {data.volunteerPayments.some(row=>!row.sourceDocumentId) && <>
        <Field label="Tanggal pembayaran relawan (historis)" type="date" value={data.volunteerPaymentDate} onChange={(v) => update("volunteerPaymentDate", v)} />
        <Field label="Ref penarikan/bank relawan" value={data.volunteerPaymentReference} onChange={(v) => update("volunteerPaymentReference", v)} />
        <Field label="Bukti bank relawan (1 untuk batch)" value={data.volunteerBatchEvidenceLink} onChange={(v) => update("volunteerBatchEvidenceLink", v)} placeholder="https://..." />
        </>}
        {data.incentiveReceiptBaseNo && <Field label="Nomor dasar kuitansi guru/kader (historis)" value={data.incentiveReceiptBaseNo} disabled />}
        {data.incentiveRecipients.some(row=>!row.sourceDocumentId) && <>
        <Field label="Tanggal pembayaran guru/kader (historis)" type="date" value={data.incentivePaymentDate} onChange={(v) => update("incentivePaymentDate", v)} />
        <Field label="Ref penarikan/bank guru/kader" value={data.incentivePaymentReference} onChange={(v) => update("incentivePaymentReference", v)} />
        <Field label="Bukti bank guru/kader (1 untuk batch)" value={data.incentiveBatchEvidenceLink} onChange={(v) => update("incentiveBatchEvidenceLink", v)} placeholder="https://..." />
        </>}
        {data.schoolPicOperationalProofNo && <Field label="No bukti agregat guru (historis)" value={data.schoolPicOperationalProofNo} disabled />}
        {data.cadreOperationalProofNo && <Field label="No bukti agregat kader (historis)" value={data.cadreOperationalProofNo} disabled />}
        {data.rawInvoiceNo && <Field label="No invoice bahan baku (historis)" value={data.rawInvoiceNo} disabled />}
        {data.operationalInvoiceNo && <Field label="No invoice operasional (historis)" value={data.operationalInvoiceNo} disabled />}
      </div>
    </Section>

    <FormTabs key={`${site}|${serviceDate}`} label="Bagian Data Harian" issueTarget={issueTarget}>
    <Section tabKey="pm" tabLabel="A · Penerima Manfaat" title="A_PM · Penerima Manfaat & Distribusi" subtitle="BAST kosong diisi DRAFT-WAJIB-DIGANTI. Dummy diizinkan dan dianggap OK pada pemeriksaan aplikasi, tetapi bukan bukti autentik: wajib diganti nomor dan link asli di Excel setelah unduh. Isian BAST yang sudah ada tidak ditimpa.">
      <div className="lpdh-table-wrap"><FormTable className="lpdh-data-table wide"><thead><tr><th>Kode</th><th>Kelompok / Porsi</th><th>Target dari Master</th><th>Distribusi POP</th><th>Diterima Fleet</th><th>Tidak diterima</th><th>Alasan</th><th>BNBA</th><th>No BAST</th><th>Link BAST</th></tr></thead>
        <tbody>{data.pm.rows.map((row, index) => <tr key={row.code}>
          <td><strong>{row.code}</strong></td><td>{row.label} · {row.portion}</td>
          <td>{row.targetPm ?? aggregateMasterTargets(masterData)[row.code]}</td>
          <td><input type="number" value={row.distributed ?? ""} onChange={(e) => updatePmRow(index, "distributed", numValue(e.target.value))}/></td>
          <td><input type="number" value={row.received ?? ""} onChange={(e) => updatePmRow(index, "received", numValue(e.target.value))}/></td>
          <td><input type="number" value={row.notReceived ?? ""} onChange={(e) => updatePmRow(index, "notReceived", numValue(e.target.value))}/></td>
          <td><input value={row.reason || ""} onChange={(e) => updatePmRow(index, "reason", e.target.value)}/></td>
          <td><select className="lpdh-bnba-select" aria-label={`BNBA ${row.code}`} value={row.bnba === true || row.bnba === "Ya" ? "Ya" : row.bnba === false || row.bnba === "Tidak" ? "Tidak" : ""} onChange={(e) => updatePmRow(index, "bnba", e.target.value)}><option value="">— pilih —</option><option>Ya</option><option>Tidak</option></select></td>
          <td><input value={row.bastNo || ""} onChange={(e) => updatePmRow(index, "bastNo", e.target.value)}/></td>
          <td><input value={row.bastLink || ""} onChange={(e) => updatePmRow(index, "bastLink", e.target.value)} placeholder="https://..."/></td>
        </tr>)}</tbody></FormTable></div>
      <div className="lpdh-form-grid">
        <Field label="Total diproduksi" type="number" value={data.pm.production.produced} onChange={(v) => updateProduction("produced", v)} />
        <Field label="Organoleptik" type="number" value={data.pm.production.organoleptic} onChange={(v) => updateProduction("organoleptic", v)} />
        <Field label="Retained sample" type="number" value={data.pm.production.retainedSample} onChange={(v) => updateProduction("retainedSample", v)} />
        <Field label="Tidak didistribusikan" type="number" value={data.pm.production.notDistributed} onChange={(v) => updateProduction("notDistributed", v)} />
        <Field label="Buffer" type="number" value={data.pm.production.buffer} onChange={(v) => updateProduction("buffer", v)} />
      </div>
      <div className="lpdh-note lpdh-production-note">
        <p>Total produksi = distribusi POP + organoleptik + retained sample + tidak didistribusikan + buffer.</p>
        <p>Rincian saat ini: {production.distributed.toLocaleString("id-ID")} + {production.organoleptic} + {production.retainedSample} + {production.notDistributed} + {production.buffer} = <strong>{production.total.toLocaleString("id-ID")}</strong>.</p>
        {Number(data.pm.production.produced) !== production.total && <p>Total tersimpan/isian {Number(data.pm.production.produced || 0).toLocaleString("id-ID")} berbeda dari rincian. Tidak diubah otomatis.</p>}
        <button type="button" onClick={recalculateProduction}>Hitung ulang total produksi</button>
      </div>
    </Section>

    <Section tabKey="raw" tabLabel="B · Bahan Baku" title="B_BahanBaku" subtitle={`Total Rp ${rawTotal.toLocaleString("id-ID")}. Buat invoice lalu finalkan pada tab Buat Invoice & Kuitansi. Baris manual historis tetap ditampilkan.`}>
      <div className="lpdh-table-wrap"><FormTable locked searchLabel="Cari bahan baku" className="lpdh-data-table extra-wide"><thead><tr><th>Tanggal</th><th>Bahan</th><th>Kategori</th><th>Qty</th><th>Unit</th><th>Harga</th><th>Supplier</th><th>No Invoice/Nota</th><th>Link Bukti</th><th></th></tr></thead>
        <tbody>{data.rawMaterials.map((row, index) => <tr key={index}>
          <td><input type="date" value={row.date || serviceDate} onChange={(e) => updateList("rawMaterials", index, "date", e.target.value)}/></td>
          <td><input value={row.name || ""} onChange={(e) => updateList("rawMaterials", index, "name", e.target.value)}/></td>
          <td><input value={row.category || ""} onChange={(e) => updateList("rawMaterials", index, "category", e.target.value)}/></td>
          <td><input type="number" step="0.01" value={row.qty ?? ""} onChange={(e) => updateList("rawMaterials", index, "qty", numValue(e.target.value))}/></td>
          <td><input value={row.unit || ""} onChange={(e) => updateList("rawMaterials", index, "unit", e.target.value)}/></td>
          <td><input type="number" value={row.price ?? ""} onChange={(e) => updateList("rawMaterials", index, "price", numValue(e.target.value))}/></td>
          <td><input value={row.supplier || ""} onChange={(e) => updateList("rawMaterials", index, "supplier", e.target.value)}/></td>
          <td><input value={row.invoiceNo || ""} onChange={(e) => updateList("rawMaterials", index, "invoiceNo", e.target.value)} placeholder="Nomor dasar invoice"/></td>
          <td><input value={row.evidenceLink || ""} onChange={(e) => updateList("rawMaterials", index, "evidenceLink", e.target.value)} placeholder="https://..."/></td>
          <td><button className="icon danger" onClick={() => deleteList("rawMaterials", index)} type="button"><Trash2 size={14}/></button></td>
        </tr>)}{!data.rawMaterials.length && <EmptyRow colSpan={10}>Finalkan invoice bahan baku agar otomatis masuk di sini.</EmptyRow>}</tbody></FormTable></div>
    </Section>

    <Section tabKey="operations" tabLabel="C · Operasional" title="C_Operasional" subtitle={`Belanja operasional Rp ${opTotal.toLocaleString("id-ID")}. Semua invoice FINAL masuk otomatis. Baris manual historis tetap ditampilkan.`}>
      <div className="lpdh-table-wrap"><FormTable locked searchLabel="Cari item operasional" className="lpdh-data-table extra-wide"><thead><tr><th>Tanggal</th><th>Item master</th><th>Deskripsi</th><th>Qty</th><th>Unit</th><th>Harga</th><th>No Invoice/Nota</th><th>Link Bukti</th><th></th></tr></thead>
        <tbody>{data.operations.map((row, index) => <tr key={index}>
          <td><input type="date" value={row.date || serviceDate} onChange={(e) => updateList("operations", index, "date", e.target.value)}/></td>
          <td><select disabled={Boolean(row.sourceDocumentId)} value={row.itemCode || ""} onChange={(e) => { const code=e.target.value; const master=masterData.operations.find((x)=>x.code===code); const list=clone(data.operations); list[index]={...list[index],itemCode:code,description:master?.name||list[index].description,unit:master?.unit||list[index].unit,price:master?.defaultPrice??list[index].price}; setDaily({...data,operations:list}); }}><option value="">— pilih —</option>{masterData.operations.filter((x)=>String(x.status||"Aktif").toLowerCase()!=="nonaktif").map((x)=><option key={x.code} value={x.code}>{x.name}</option>)}</select></td>
          <td><input value={row.description || ""} onChange={(e) => updateList("operations", index, "description", e.target.value)}/></td>
          <td><input type="number" step="0.01" value={row.qty ?? ""} onChange={(e) => updateList("operations", index, "qty", numValue(e.target.value))}/></td>
          <td><input value={row.unit || ""} onChange={(e) => updateList("operations", index, "unit", e.target.value)}/></td>
          <td><input type="number" value={row.price ?? ""} onChange={(e) => updateList("operations", index, "price", numValue(e.target.value))}/></td>
          <td><input value={row.invoiceNo || ""} onChange={(e) => updateList("operations", index, "invoiceNo", e.target.value)}/></td>
          <td><input value={row.evidenceLink || ""} onChange={(e) => updateList("operations", index, "evidenceLink", e.target.value)} placeholder="https://..."/></td>
          <td><button className="icon danger" onClick={() => deleteList("operations", index)} type="button"><Trash2 size={14}/></button></td>
        </tr>)}{!data.operations.length && <EmptyRow colSpan={9}/>}</tbody></FormTable></div>
    </Section>

    <Section tabKey="volunteers" tabLabel="C1 · Relawan" title="C1_Relawan" subtitle={`Total upah harian relawan Rp ${volunteerTotal.toLocaleString("id-ID")}. Buat paket kuitansi harian di tab Buat Invoice & Kuitansi. Pembayaran historis tetap ditampilkan.`}>
      <div className="lpdh-table-wrap"><FormTable locked searchLabel="Cari relawan" className="lpdh-data-table extra-wide"><thead><tr><th>Nama</th><th>Tugas</th><th>Tgl Bayar</th><th>Hari Kerja</th><th>Tarif/Hari</th><th>Jumlah</th><th>Metode</th><th>Kuitansi override</th><th>Link Bukti</th></tr></thead>
        <tbody>{data.volunteerPayments.map((row, index) => <tr key={row.volunteerCode || index}>
          <td>{row.name}</td><td>{row.role}</td>
          <td><input type="date" value={row.date || ""} onChange={(e) => updateList("volunteerPayments", index, "date", e.target.value)}/></td>
          <td><input type="number" step="0.5" value={row.workDays ?? ""} onChange={(e) => updateList("volunteerPayments", index, "workDays", numValue(e.target.value))}/></td>
          <td><input type="number" value={row.dailyRate ?? ""} onChange={(e) => updateList("volunteerPayments", index, "dailyRate", numValue(e.target.value))}/></td>
          <td>Rp {((Number(row.workDays)||0)*(Number(row.dailyRate)||0)).toLocaleString("id-ID")}</td>
          <td><select value={row.paymentMethod || "Transfer"} onChange={(e) => updateList("volunteerPayments", index, "paymentMethod", e.target.value)}><option>Transfer</option><option>Tunai</option><option>Lainnya</option></select></td>
          <td><input value={row.receiptNo || ""} onChange={(e) => updateList("volunteerPayments", index, "receiptNo", e.target.value)} placeholder="kosong = pakai nomor dasar"/></td>
          <td><input value={row.evidenceLink || ""} onChange={(e) => updateList("volunteerPayments", index, "evidenceLink", e.target.value)} placeholder="https://..."/></td>
        </tr>)}{!data.volunteerPayments.length && <EmptyRow colSpan={9}>Finalkan paket kuitansi relawan.</EmptyRow>}</tbody></FormTable></div>
    </Section>

    <Section tabKey="recipients" tabLabel="Guru / Kader" title="Insentif Guru / Kader (bagian operasional)" subtitle={`Total Rp ${recipientTotal.toLocaleString("id-ID")}. Buat paket Guru dan Kader terpisah pada tab Buat Invoice & Kuitansi. Pembayaran historis tetap ditampilkan.`}>
      <div className="lpdh-table-wrap"><FormTable locked searchLabel="Cari guru atau kader" className="lpdh-data-table"><thead><tr><th>Jenis</th><th>Nama</th><th>Sekolah/Posyandu</th><th>Tgl</th><th>Nilai</th><th>Kuitansi override</th><th>Link Bukti</th><th></th></tr></thead>
        <tbody>{data.incentiveRecipients.map((row,index)=><tr key={index}>
          <td><select value={row.type || "Guru"} onChange={(e)=>updateList("incentiveRecipients",index,"type",e.target.value)}><option>Guru</option><option>Kader</option></select></td>
          <td><input value={row.name||""} onChange={(e)=>updateList("incentiveRecipients",index,"name",e.target.value)}/></td>
          <td><input value={row.unitName||""} onChange={(e)=>updateList("incentiveRecipients",index,"unitName",e.target.value)}/></td>
          <td><input type="date" value={row.date||serviceDate} onChange={(e)=>updateList("incentiveRecipients",index,"date",e.target.value)}/></td>
          <td><input type="number" value={row.amount??""} onChange={(e)=>updateList("incentiveRecipients",index,"amount",numValue(e.target.value))}/></td>
          <td><input value={row.receiptNo||""} onChange={(e)=>updateList("incentiveRecipients",index,"receiptNo",e.target.value)}/></td>
          <td><input value={row.evidenceLink||""} onChange={(e)=>updateList("incentiveRecipients",index,"evidenceLink",e.target.value)} placeholder="https://..."/></td>
          <td><button className="icon danger" type="button" onClick={()=>deleteList("incentiveRecipients",index)}><Trash2 size={14}/></button></td>
        </tr>)}{!data.incentiveRecipients.length&&<EmptyRow colSpan={8}/>}</tbody></FormTable></div>
    </Section>

    <Section tabKey="proof" tabLabel="Bukti & Referensi" title="Lengkapi bukti invoice & kuitansi" subtitle="Satu isian per invoice/kuitansi gabungan FINAL, diterapkan ke seluruh item/penerima paket itu. Guru dan Kader tetap terpisah. Nomor dan nominal terkunci; referensi bank diisi sesuai transaksi nyata. Simpan Draft setelah melengkapi bukti.">
      {proofGroups.map(group => <div key={group.key} className="lpdh-proof-package">
        <h4>{group.label} · {group.number}{group.name ? ` · ${group.name}` : ""}</h4>
        <p>{group.indexes.length} baris terkait{group.conflictingFields.length ? " · Isian lama berbeda antarbaris; tidak dipilih otomatis." : ""}</p>
        <div className="lpdh-form-grid">
          <Field label={`Link bukti · ${group.number}`} value={group.evidenceLink} onChange={value => updateProofGroup(group,"evidenceLink",value)} placeholder={group.conflictingFields.includes("evidenceLink") ? "Berbeda antarbaris — isi untuk menyamakan" : "https://..."}/>
          <Field label={`Referensi pembayaran · ${group.number}`} value={group.paymentReference} onChange={value => updateProofGroup(group,"paymentReference",value)} placeholder={group.conflictingFields.includes("paymentReference") ? "Berbeda antarbaris — isi untuk menyamakan" : "Referensi bank/penarikan sebenarnya"}/>
        </div>
      </div>)}
    </Section>

    <Section tabKey="incentive" tabLabel="D · Insentif Yayasan" title="D_Insentif · Ketersediaan & Mutu Layanan" subtitle="Ini Insentif ke Mitra/Yayasan sesuai workbook, berbeda dari insentif guru/kader yang masuk biaya operasional.">
      <p>Nilai kosong mengikuti insentif dihitung; tetap bisa diedit. Tanggal default mengikuti HPE, bukan tanggal unduhan. Nomor bukti dibuat sistem dan nomor kuitansi berlanjut saat disimpan.</p>
      <button type="button" onClick={()=>{
        if (!window.confirm("Terapkan kembali nilai insentif dihitung dan tanggal HPE? Nilai manual pada tiga isian ini akan diganti.")) return;
        setDaily({...data,incentive:{...data.incentive,statementAmount:preview?.incentiveCalculated??0,paidAmount:preview?.incentiveCalculated??0,paymentDate:serviceDate,receiptSigned:"Ya",_automaticAmounts:["statementAmount","paidAmount"]}});
      }}>Terapkan nilai hitung &amp; tanggal HPE</button>
      <div className="lpdh-form-grid">
        <YesNo label="Ada kontaminasi?" value={data.incentive.eligibility.contamination} onChange={(v)=>setDaily({...data,incentive:{...data.incentive,eligibility:{...data.incentive.eligibility,contamination:v}}})}/>
        <YesNo label="Ada insiden fatal?" value={data.incentive.eligibility.fatalIncident} onChange={(v)=>setDaily({...data,incentive:{...data.incentive,eligibility:{...data.incentive.eligibility,fatalIncident:v}}})}/>
        <YesNo label="SPPG disuspend?" value={data.incentive.eligibility.suspended} onChange={(v)=>setDaily({...data,incentive:{...data.incentive,eligibility:{...data.incentive.eligibility,suspended:v}}})}/>
        <YesNo label="Sudah diverifikasi?" value={data.incentive.eligibility.verified} onChange={(v)=>setDaily({...data,incentive:{...data.incentive,eligibility:{...data.incentive.eligibility,verified:v}}})}/>
        <YesNo label="PM sudah masuk SIPGN?" value={data.incentive.eligibility.pmInputSipgn} onChange={(v)=>setDaily({...data,incentive:{...data.incentive,eligibility:{...data.incentive.eligibility,pmInputSipgn:v}}})}/>
        <Field label="No pernyataan PPK" value={data.incentive.ppkStatementNo} onChange={(v)=>updateNested("incentive","ppkStatementNo",v)}/>
        <Field label="Nilai pernyataan PPK" type="number" value={data.incentive.statementAmount} onChange={(v)=>updateNested("incentive","statementAmount",v)}/>
        <Field label="Nilai dibayar" type="number" value={data.incentive.paidAmount} onChange={(v)=>updateNested("incentive","paidAmount",v)}/>
        <Field label="Tanggal pembayaran" type="date" value={data.incentive.paymentDate} onChange={(v)=>updateNested("incentive","paymentDate",v)}/>
        <Field label="No bukti pembayaran" value={data.incentive.proofNo} onChange={(v)=>updateNested("incentive","proofNo",v)}/>
        <Field label="No kuitansi" value={data.incentive.receiptNo} onChange={(v)=>updateNested("incentive","receiptNo",v)}/>
        <YesNo label="Kuitansi ditandatangani?" value={data.incentive.receiptSigned} onChange={(v)=>updateNested("incentive","receiptSigned",v)}/>
        <Field label="Link bukti" value={data.incentive.evidenceLink} onChange={(v)=>updateNested("incentive","evidenceLink",v)} placeholder="https://..."/>
        {data.incentive.approvalEvidenceLink && <p><a href={data.incentive.approvalEvidenceLink} target="_blank" rel="noopener noreferrer">PDF J_Pengesahan di Drive</a> · Dokumen pengesahan, bukan verifikasi transfer.</p>}
        <Field label="Referensi transaksi VA" value={data.incentive.vaReference} onChange={(v)=>updateNested("incentive","vaReference",v)}/>
      </div>
    </Section>

    <Section tabKey="balance" tabLabel="E / F · Saldo & TopUp" title="E_Saldo & F_TopUp" subtitle="Usulan SPPG pada F_TopUp dihitung otomatis dari bahan baku + operasional + Insentif Ketersediaan dan Mutu Layanan. Kolom persetujuan PPK tidak diisi oleh aplikasi.">
      <div className="lpdh-form-grid">
        <Field label="Saldo awal bahan" type="number" value={data.balance.openingRaw} onChange={(v)=>updateNested("balance","openingRaw",v)}/>
        <Field label="Saldo awal operasional" type="number" value={data.balance.openingOperational} onChange={(v)=>updateNested("balance","openingOperational",v)}/>
        <Field label="Saldo awal insentif" type="number" value={data.balance.openingIncentive} onChange={(v)=>updateNested("balance","openingIncentive",v)}/>
        <Field label="Saldo VA rekening koran" type="number" value={data.balance.bankBalance} onChange={(v)=>updateNested("balance","bankBalance",v)}/>
      </div>
      <h4>Posisi saldo per komponen</h4>
      <p>Saldo akhir = saldo awal + top-up diterima − pengeluaran/pembayaran hari ini. Pengeluaran mengikuti perhitungan laporan; insentif memakai nominal dibayarkan, bukan hanya insentif dihitung.</p>
      {!preview?.balance && <div className="lpdh-status-box warn"><strong>Perhitungan pengeluaran belum tersedia</strong><span>Simpan &amp; Validasi untuk memuat angka laporan. Jangan gunakan ringkasan ini sebagai saldo final sebelum perhitungan tersedia.</span></div>}
      <div className="lpdh-table-wrap"><FormTable className="lpdh-data-table"><thead><tr><th>Komponen</th><th>Saldo awal</th><th>Top-up diterima</th><th>Pengeluaran hari ini</th><th>Saldo akhir</th><th>Keterangan</th></tr></thead><tbody>
        {saldo.rows.map(row=><tr key={row.key}><td>{row.label}</td><td>{saldoMoney(row.opening)}</td><td>{saldoMoney(row.topup)}</td><td>{saldoMoney(row.expenditure)}</td><td style={{color:row.closing<0?'#b42318':undefined,fontWeight:700}}>{saldoMoney(row.closing)}</td><td>{row.closing<0?`MINUS: dana komponen kurang ${saldoMoney(-row.closing)}. Periksa saldo awal, top-up diterima, dan pembayaran komponen ini.`:row.opening<0?'PERIKSA: saldo awal negatif.':'Tidak minus'}</td></tr>)}
        <tr><td><strong>JUMLAH</strong></td><td>{saldoMoney(saldo.opening)}</td><td>{saldoMoney(saldo.topup)}</td><td>{saldoMoney(saldo.expenditure)}</td><td><strong>{saldoMoney(saldo.closing)}</strong></td><td>Bandingkan dengan saldo VA di rekening.</td></tr>
      </tbody></FormTable></div>
      <div className={`lpdh-status-box ${saldo.bankEntered&&Math.abs(saldo.difference)<1?'ok':'warn'}`} role="status" style={{marginTop:12}}>
        <strong>{!saldo.bankEntered?'Saldo VA belum diisi':Math.abs(saldo.difference)<1?'Saldo komponen sesuai saldo VA':`SELISIH ${saldoMoney(saldo.difference)}`}</strong>
        <span>Total saldo akhir {saldoMoney(saldo.closing)} − saldo VA rekening {saldoMoney(saldo.bank)} = {saldoMoney(saldo.difference)}. {saldo.bankEntered&&Math.abs(saldo.difference)>=1?`Saldo komponen ${saldo.difference>0?'lebih besar':'lebih kecil'} dari rekening. Periksa saldo awal, penerimaan top-up, pengeluaran, dan mutasi rekening; jangan ubah saldo VA hanya agar cocok.`:'Isi saldo VA sesuai mutasi rekening setelah transaksi hari ini.'}</span>
      </div>
      <h4>F_TopUp · Usulan (bukan penerimaan)</h4>
      <div className="lpdh-summary-cards"><div><span>Bahan baku</span><strong>{saldoMoney(displayPreview?.topup?.requiredRaw)}</strong></div><div><span>Operasional</span><strong>{saldoMoney(displayPreview?.topup?.requiredOperational)}</strong></div><div><span>Insentif dihitung</span><strong>{saldoMoney(displayPreview?.topup?.requiredIncentive)}</strong></div><div><span>Total usulan</span><strong>{saldoMoney(displayPreview?.topup?.proposalTotal)}</strong></div></div>
      <p>Ruang sampai batas saldo VA: {saldoMoney(displayPreview?.topup?.roomToMax)}. {displayPreview?.topup?displayPreview.topup.withinMax?'Usulan dalam batas saldo VA.':'PERIKSA: usulan melebihi ruang saldo VA.':''} Usulan tidak menambah saldo sampai dana benar-benar diterima. Persetujuan PPK tetap diisi oleh PPK.</p>
      <h4>Bukti penerimaan top-up hari ini</h4>
      <div className="lpdh-inline-actions"><button type="button" onClick={()=>addList("topups",{date:serviceDate,reference:"",rawAmount:0,operationalAmount:0,incentiveAmount:0,receiptNo:"",evidenceLink:""})}><Plus size={15}/> Tambah penerimaan TopUp</button></div>
      <div className="lpdh-table-wrap"><FormTable className="lpdh-data-table"><thead><tr><th>Tgl</th><th>SP2D/Ref</th><th>Bahan</th><th>Operasional</th><th>Insentif</th><th>No Kuitansi</th><th>Link</th><th></th></tr></thead><tbody>
        {data.topups.map((row,index)=><tr key={index}>
          <td><input type="date" value={row.date||""} onChange={(e)=>updateList("topups",index,"date",e.target.value)}/></td>
          <td><input value={row.reference||""} onChange={(e)=>updateList("topups",index,"reference",e.target.value)}/></td>
          <td><input type="number" value={row.rawAmount??""} onChange={(e)=>updateList("topups",index,"rawAmount",numValue(e.target.value))}/></td>
          <td><input type="number" value={row.operationalAmount??""} onChange={(e)=>updateList("topups",index,"operationalAmount",numValue(e.target.value))}/></td>
          <td><input type="number" value={row.incentiveAmount??""} onChange={(e)=>updateList("topups",index,"incentiveAmount",numValue(e.target.value))}/></td>
          <td><input value={row.receiptNo||""} onChange={(e)=>updateList("topups",index,"receiptNo",e.target.value)}/></td>
          <td><input value={row.evidenceLink||""} onChange={(e)=>updateList("topups",index,"evidenceLink",e.target.value)} placeholder="https://..."/></td>
          <td><button className="icon danger" type="button" onClick={()=>deleteList("topups",index)}><Trash2 size={14}/></button></td>
        </tr>)}{!data.topups.length&&<EmptyRow colSpan={8}/>}</tbody></FormTable></div>
      <div className="lpdh-inline-actions">{data.topups.map((row,index)=><TopupReceiptActions key={`${site}-${serviceDate}-${index}`} site={site} serviceDate={serviceDate} row={row} index={index} api={api} disabled={busy||!dailySaved} onData={next=>{
        const current=topupFormRef.current;
        if(JSON.stringify(current.topups[index])!==JSON.stringify(row)){onSaved?.('Kuitansi tersimpan, tetapi isian lokal berubah. Muat ulang untuk mengambil link terbaru; isian Anda tidak ditimpa.','error');return;}
        setDaily({...current,topups:current.topups.map((r,i)=>i===index?next.topups[index]:r)});
      }}/>)}</div>
      <TopupReceiptActions key={`${site}-${serviceDate}-new`} isNew site={site} serviceDate={serviceDate} row={{date:serviceDate,reference:'',rawAmount:0,operationalAmount:0,incentiveAmount:0}} index={data.topups.length} api={api} disabled={busy} onData={(next,receiptId)=>{
        const current=topupFormRef.current;
        const target=next.topups.find(r=>r._topupReceiptId===receiptId);
        if(!target)return;
        const found=current.topups.findIndex(r=>r._topupReceiptId===receiptId);
        setDaily({...current,topups:found<0?[...current.topups,target]:current.topups.map((r,i)=>i===found?target:r)});
      }}/>
    </Section>

    <Section tabKey="upload" tabLabel="Upload" title="Rencana upload">
      <div className="lpdh-form-grid">
        <Field label="Tanggal upload" type="date" value={data.upload.date} onChange={(v)=>updateNested("upload","date",v)}/>
        <Field label="Jam upload" type="time" value={data.upload.time} onChange={(v)=>updateNested("upload","time",v)}/>
      </div>
    </Section>

    </FormTabs>
    <div className="lpdh-sticky-save"><span role="status">{dailySaved?"Tersimpan. Periksa hasil validasi di Review.":"Belum disimpan / ada perubahan. Klik Simpan & Validasi agar insentif masuk ke Review."}</span><button className={dailySaved?"primary":"lpdh-save-pending"} type="button" onClick={save} disabled={busy}><Save size={16}/> {busy?"Menyimpan…":"Simpan & Validasi"}</button></div>
  </div>;
}

function deriveNumbers(rows, base, overrideKey = "receiptNo") {
  const active = rows.map((row, index) => ({ row, index, base: String(row[overrideKey] || base || "").trim() })).filter((x) => x.base);
  const count = active.reduce((map, x) => ({ ...map, [x.base]: (map[x.base] || 0) + 1 }), {});
  const seen = {};
  return active.map((x) => {
    seen[x.base] = (seen[x.base] || 0) + 1;
    const width = Math.max(2, String(count[x.base] || 1).length);
    return {
      ...x.row,
      generatedNo: count[x.base] > 1 ? `${x.base}-${String(seen[x.base]).padStart(width, "0")}` : x.base,
    };
  });
}

export function DocumentsPanel({ serviceDate, daily, preview, masters, onMessage }) {
  const data = normalizeDaily(daily, serviceDate);
  const volunteerDocs = useMemo(() => deriveNumbers((data.volunteerPayments || []).filter((x)=>(Number(x.workDays)||0)*(Number(x.dailyRate)||0)>0), data.volunteerReceiptBaseNo), [data]);
  const incentiveDocs = useMemo(() => deriveNumbers((data.incentiveRecipients || []).filter((x)=>Number(x.amount)>0), data.incentiveReceiptBaseNo), [data]);
  const masterData = normalizeMasters(masters || {});
  const vendor = masterData.vendor || {};
  const assets = masterData.assets || {};
  const groupInvoices = (rows, defaultNo = "", defaultDate = "") => Object.values((rows || []).reduce((groups, row) => {
    const no = String(row.invoiceNo || defaultNo || "").trim();
    if (!no) return groups;
    if (!groups[no]) groups[no] = { invoiceNo: no, rows: [] };
    groups[no].rows.push({ ...row, invoiceNo: no, date: row.date || defaultDate || serviceDate });
    return groups;
  }, {}));
  const rawInvoices = useMemo(
    () => groupInvoices(data.rawMaterials, data.rawInvoiceNo, data.rawInvoiceDate),
    [data.rawMaterials, data.rawInvoiceNo, data.rawInvoiceDate, serviceDate]
  );
  const operationalInvoices = useMemo(
    () => groupInvoices(data.operations, data.operationalInvoiceNo, data.operationalInvoiceDate),
    [data.operations, data.operationalInvoiceNo, data.operationalInvoiceDate, serviceDate]
  );
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;" }[char]));

  const printDocument = (title, rows) => {
    const win = window.open("", "_blank", "noopener,noreferrer");
    if (!win) return onMessage?.("Popup diblokir browser. Izinkan popup untuk cetak dokumen.", "error");
    const htmlRows = rows.map((x) => `<tr><td>${x.generatedNo || ""}</td><td>${x.name || ""}</td><td>${x.unitName || x.role || ""}</td><td style="text-align:right">Rp ${Number(x.amount ?? ((Number(x.workDays)||0)*(Number(x.dailyRate)||0))).toLocaleString("id-ID")}</td></tr>`).join("");
    win.document.write(`<!doctype html><html><head><title>${title}</title><style>body{font-family:Arial,sans-serif;padding:32px;color:#111}h1{font-size:20px}table{width:100%;border-collapse:collapse;margin-top:18px}td,th{border:1px solid #bbb;padding:8px;font-size:12px}.sign{margin-top:50px;display:flex;justify-content:flex-end}.sign div{text-align:center;width:240px}</style></head><body><h1>${title}</h1><p>Tanggal: ${serviceDate}</p><table><thead><tr><th>No Bukti/Kuitansi</th><th>Nama</th><th>Keterangan</th><th>Jumlah</th></tr></thead><tbody>${htmlRows}</tbody></table><div class="sign"><div>Penerima/Petugas<br><br><br><br>_____________________</div></div><script>window.print()</script></body></html>`);
    win.document.close();
  };

  const printInvoice = (kind, invoice) => {
    const rows = invoice.rows || [];
    const win = window.open("", "_blank", "noopener,noreferrer");
    if (!win) return onMessage?.("Popup diblokir browser. Izinkan popup untuk cetak invoice.", "error");
    const items = rows.map((x, index) => {
      const qty = Number(x.qty || 0); const price = Number(x.price || 0);
      return `<tr><td>${index+1}</td><td>${esc(x.name || x.description || "")}</td><td style="text-align:right">${qty.toLocaleString("id-ID")}</td><td>${esc(x.unit || "")}</td><td style="text-align:right">Rp ${price.toLocaleString("id-ID")}</td><td style="text-align:right">Rp ${(qty*price).toLocaleString("id-ID")}</td></tr>`;
    }).join("");
    const total = rows.reduce((sum,x)=>sum+(Number(x.qty||0)*Number(x.price||0)),0);
    const logo = assets.vendorLogo ? `<img class="logo" src="${esc(assets.vendorLogo)}"/>` : "";
    const signature = assets.vendorSignature ? `<img class="sign-img" src="${esc(assets.vendorSignature)}"/>` : "";
    const stamp = assets.vendorStamp ? `<img class="stamp" src="${esc(assets.vendorStamp)}"/>` : "";
    win.document.write(`<!doctype html><html><head><title>${esc(invoice.invoiceNo)}</title><style>
      body{font-family:Arial,sans-serif;color:#111;padding:32px}.head{display:flex;justify-content:space-between;gap:20px}.logo{max-width:120px;max-height:70px}h1{font-size:22px;margin:0 0 5px}.muted{color:#666;font-size:12px}table{width:100%;border-collapse:collapse;margin-top:24px}td,th{border:1px solid #aaa;padding:8px;font-size:12px}th{background:#f3f3f3}.total{text-align:right;margin-top:14px;font-size:16px}.sign-area{display:flex;justify-content:flex-end;margin-top:45px}.sign-box{width:260px;text-align:center;position:relative;min-height:130px}.sign-img{max-height:80px;max-width:180px}.stamp{max-height:80px;max-width:100px;position:absolute;right:20px;top:20px;opacity:.8}
    </style></head><body><div class="head"><div>${logo}<h1>INVOICE</h1><div><strong>${esc(vendor.name || "Vendor / Koperasi")}</strong></div><div class="muted">${esc(vendor.address || "")}</div><div class="muted">${esc(vendor.phone || "")}</div></div><div><strong>No. ${esc(invoice.invoiceNo)}</strong><div class="muted">Tanggal pelayanan: ${esc(serviceDate)}</div><div class="muted">${esc(kind)}</div></div></div>
    <table><thead><tr><th>No</th><th>Uraian</th><th>Qty</th><th>Unit</th><th>Harga</th><th>Jumlah</th></tr></thead><tbody>${items}</tbody></table><div class="total"><strong>Total: Rp ${total.toLocaleString("id-ID")}</strong></div>
    <div class="sign-area"><div class="sign-box">Hormat kami,<br>${signature}${stamp}<br><strong>${esc(vendor.signatoryName || vendor.name || "Vendor")}</strong></div></div><script>window.print()</script></body></html>`);
    win.document.close();
  };

  return <div className="lpdh-stack">
    <Section title="Invoice & Kuitansi" subtitle="Nomor asli invoice tetap disimpan. Jika satu invoice memiliki beberapa baris, register bukti memberi suffix otomatis agar unik.">
      <div className="lpdh-summary-cards">
        <div><span>Bahan baku</span><strong>{preview?.rawMaterials?.length || 0} baris</strong><small>Satu invoice dapat mencakup seluruh bahan.</small></div>
        <div><span>Relawan</span><strong>{volunteerDocs.length} kuitansi</strong><small>Dari nomor dasar {data.volunteerReceiptBaseNo || "belum diisi"}.</small></div>
        <div><span>Guru/Kader</span><strong>{incentiveDocs.length} kuitansi</strong><small>Dari nomor dasar {data.incentiveReceiptBaseNo || "belum diisi"}.</small></div>
        <div><span>Invoice vendor</span><strong>{rawInvoices.length + operationalInvoices.length}</strong><small>{rawInvoices.length} bahan · {operationalInvoices.length} operasional.</small></div>
      </div>
      <div className="lpdh-inline-actions">
        <button type="button" onClick={()=>printDocument("Kuitansi Upah Relawan",volunteerDocs)} disabled={!volunteerDocs.length}>Cetak/Save PDF Kuitansi Relawan</button>
        <button type="button" onClick={()=>printDocument("Kuitansi Insentif Guru/Kader",incentiveDocs)} disabled={!incentiveDocs.length}>Cetak/Save PDF Kuitansi Guru/Kader</button>
      </div>
      <div className="lpdh-invoice-list">
        {rawInvoices.map((invoice)=><button type="button" key={`raw-${invoice.invoiceNo}`} onClick={()=>printInvoice("Bahan Baku",invoice)}>Invoice bahan · {invoice.invoiceNo}</button>)}
        {operationalInvoices.map((invoice)=><button type="button" key={`op-${invoice.invoiceNo}`} onClick={()=>printInvoice("Operasional",invoice)}>Invoice operasional · {invoice.invoiceNo}</button>)}
      </div>
      <div className="lpdh-note">Generator invoice vendor generik sudah aktif memakai logo, tanda tangan, dan stempel master. Saat contoh invoice asli diberikan, layoutnya dapat dibuat persis tanpa mengubah data transaksi.</div>
    </Section>
    <Section title="Nomor kuitansi yang akan dipakai">
      <div className="lpdh-table-wrap"><table className="lpdh-data-table"><thead><tr><th>Jenis</th><th>Nomor</th><th>Nama</th><th>Nilai</th></tr></thead><tbody>
        {volunteerDocs.map((x,i)=><tr key={`v-${i}`}><td>Relawan</td><td><strong>{x.generatedNo}</strong></td><td>{x.name}</td><td>Rp {((Number(x.workDays)||0)*(Number(x.dailyRate)||0)).toLocaleString("id-ID")}</td></tr>)}
        {incentiveDocs.map((x,i)=><tr key={`i-${i}`}><td>{x.type || "Insentif"}</td><td><strong>{x.generatedNo}</strong></td><td>{x.name}</td><td>Rp {(Number(x.amount)||0).toLocaleString("id-ID")}</td></tr>)}
        {!volunteerDocs.length&&!incentiveDocs.length&&<EmptyRow colSpan={4}/>}
      </tbody></table></div>
    </Section>
  </div>;
}

