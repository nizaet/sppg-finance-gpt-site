import React, { useEffect, useMemo, useRef, useState } from "react";
import { Download, FileUp, Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { arrayBufferToBase64, downloadBase64 } from "./lpdhApi.js";

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
  data.volunteers = Array.isArray(data.volunteers) ? data.volunteers : [];
  data.operations = Array.isArray(data.operations) ? data.operations : [];
  data.vendor = data.vendor || {};
  data.assets = data.assets || {};
  data.parameters = { ...DEFAULT_PARAMETERS, ...(data.parameters || {}) };
  return data;
}

export function normalizeDaily(value = {}, serviceDate = "") {
  const data = clone(value || {}) || {};
  data.pm = data.pm || {};
  data.pm.production = data.pm.production || {};
  const supplied = Array.isArray(data.pm.rows) ? data.pm.rows : [];
  const byCode = Object.fromEntries(supplied.map((x) => [String(x.code || x.groupCode || "").toUpperCase(), x]));
  data.pm.rows = GROUP_DEFAULTS.map((group) => ({ ...group, ...(byCode[group.code] || {}), code: group.code }));
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

export function MasterPanel({ site, masters, setMasters, api, onSaved, onReload }) {
  const fileRef = useRef(null);
  const officialTemplateRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [officialTemplate, setOfficialTemplate] = useState({ installed: false, filename: "" });
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
  const updateAsset = (key, value) => setMasters({ ...data, assets: { ...data.assets, [key]: value } });
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
      onSaved?.("Master data tersimpan di cloud.");
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
      onSaved?.(`Import selesai: ${result.imported.beneficiaries || 0} penerima, ${result.imported.volunteers || 0} relawan, ${result.imported.operations || 0} operasional.`);
      await onReload?.();
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
    if (file.size > 1_500_000) {
      onSaved?.("Gambar maksimal 1,5 MB. Gunakan PNG/JPG yang sudah diperkecil.", "error");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => updateAsset(key, String(reader.result || ""));
    reader.readAsDataURL(file);
  };

  return <div className="lpdh-stack">
    <Section title="Master Data LPDH" subtitle="Diisi sekali, lalu dipakai ulang untuk seluruh hari pelayanan." actions={<>
      <button type="button" onClick={downloadTemplate} disabled={busy}><Download size={15}/> Template Excel</button>
      <button type="button" onClick={() => fileRef.current?.click()} disabled={busy}><FileUp size={15}/> Import Master</button>
      <input ref={fileRef} hidden type="file" accept=".xlsx" onChange={(e) => importFile(e.target.files?.[0])} />
      <button type="button" onClick={() => officialTemplateRef.current?.click()} disabled={busy}><FileUp size={15}/> Template LPDH Resmi</button>
      <input ref={officialTemplateRef} hidden type="file" accept=".xlsx" onChange={(e) => uploadOfficialTemplate(e.target.files?.[0])} />
      <button type="button" className="primary" onClick={save} disabled={busy}><Save size={15}/> Simpan Master</button>
    </>}>
      <div className="lpdh-note">Master tersimpan per dapur. Akun YAYASAN dapat mengelola Maja dan Cemplang; akun dapur hanya site sendiri.</div>
      <div className={officialTemplate.installed ? "lpdh-status-box ok" : "lpdh-status-box warn"} style={{ marginTop: 10 }}>
        <strong>{officialTemplate.installed ? "Template resmi terpasang" : "Template resmi belum diunggah"}</strong>
        <span>{officialTemplate.installed ? officialTemplate.filename : "Fallback formula aktif. Unggah workbook resmi agar layout output persis mengikuti file sumber."}</span>
      </div>
    </Section>

    <Section title="Identitas SPPG & Rekening">
      <div className="lpdh-form-grid">
        <Field label="Nomor LPDH" value={data.identity.lpdhNumber} onChange={(v) => updateIdentity("lpdhNumber", v)} />
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

    <Section title="Master Vendor & Aset Invoice" subtitle="Dipakai saat preview/cetak invoice. Layout persis akan mengikuti contoh invoice yang Anda kirim; data dan asetnya sudah disiapkan.">
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

    <Section title="Pengesah" subtitle="Tiga baris ini dipakai juga pada J_Pengesahan.">
      <div className="lpdh-table-wrap"><table className="lpdh-data-table"><thead><tr><th>Peran</th><th>Nama</th><th>Jenis ID</th><th>Nomor ID</th><th>Ditandatangani</th></tr></thead>
        <tbody>{data.signers.slice(0, 3).map((row, index) => <tr key={index}>
          <td>{["Pengawas Keuangan SPPG","Kepala SPPG","Perwakilan Mitra/Yayasan"][index]}</td>
          <td><input value={row.name || ""} onChange={(e) => updateSigner(index, "name", e.target.value)} /></td>
          <td><input value={["NIK","NIP","NIK"][index]} disabled /></td>
          <td><input value={row.identityNumber || ""} onChange={(e) => updateSigner(index, "identityNumber", e.target.value)} /></td>
          <td><select value={row.signed || "Tidak"} onChange={(e) => updateSigner(index, "signed", e.target.value)}><option>Ya</option><option>Tidak</option></select></td>
        </tr>)}</tbody></table></div>
    </Section>

    <Section title="Master Penerima Manfaat" subtitle="Sekolah dan Posyandu digabung. Target PM akan diagregasi ke A_PM berdasarkan Kode Kelompok." actions={
      <button type="button" onClick={() => addList("beneficiaries", { code: "", unitType: "Sekolah", unitName: "", groupCode: "KS-01", groupName: "", portionCategory: "Kecil", picType: "Sekolah", targetPm: 0, picName: "", phone: "", address: "", status: "Aktif", note: "" })}><Plus size={15}/> Tambah</button>
    }>
      <div className="lpdh-table-wrap"><table className="lpdh-data-table wide"><thead><tr><th>Kode Unit</th><th>Jenis</th><th>Nama Unit</th><th>Kode Kelompok</th><th>Target PM</th><th>PIC</th><th>Status</th><th></th></tr></thead>
        <tbody>{data.beneficiaries.map((row, index) => <tr key={index}>
          <td><input value={row.code || ""} onChange={(e) => updateList("beneficiaries", index, "code", e.target.value)} /></td>
          <td><select value={row.unitType || "Sekolah"} onChange={(e) => updateList("beneficiaries", index, "unitType", e.target.value)}><option>Sekolah</option><option>Posyandu</option></select></td>
          <td><input value={row.unitName || ""} onChange={(e) => updateList("beneficiaries", index, "unitName", e.target.value)} /></td>
          <td><select value={row.groupCode || ""} onChange={(e) => updateList("beneficiaries", index, "groupCode", e.target.value)}><option value="">—</option>{GROUP_DEFAULTS.map((g) => <option key={g.code} value={g.code}>{g.code} · {g.label}</option>)}</select></td>
          <td><input type="number" value={row.targetPm ?? ""} onChange={(e) => updateList("beneficiaries", index, "targetPm", numValue(e.target.value))} /></td>
          <td><input value={row.picName || ""} onChange={(e) => updateList("beneficiaries", index, "picName", e.target.value)} /></td>
          <td><select value={row.status || "Aktif"} onChange={(e) => updateList("beneficiaries", index, "status", e.target.value)}><option>Aktif</option><option>Nonaktif</option></select></td>
          <td><button className="icon danger" type="button" onClick={() => deleteList("beneficiaries", index)}><Trash2 size={14}/></button></td>
        </tr>)}{!data.beneficiaries.length && <EmptyRow colSpan={8}/>}</tbody></table></div>
    </Section>

    <Section title="Master Relawan" subtitle={`${data.volunteers.length} relawan. Tarif harian dipakai otomatis pada C1_Relawan.`} actions={
      <button type="button" onClick={() => addList("volunteers", { code: `RL-${String(data.volunteers.length + 1).padStart(3, "0")}`, name: "", role: "", status: "Aktif", dailyRate: 90000, paymentMethod: "Transfer" })}><Plus size={15}/> Tambah</button>
    }>
      <div className="lpdh-table-wrap"><table className="lpdh-data-table wide"><thead><tr><th>Kode</th><th>Nama</th><th>Tugas</th><th>Tarif/Hari</th><th>Metode</th><th>Bank/Rekening</th><th>Status</th><th></th></tr></thead>
        <tbody>{data.volunteers.map((row, index) => <tr key={index}>
          <td><input value={row.code || ""} onChange={(e) => updateList("volunteers", index, "code", e.target.value)} /></td>
          <td><input value={row.name || ""} onChange={(e) => updateList("volunteers", index, "name", e.target.value)} /></td>
          <td><input value={row.role || ""} onChange={(e) => updateList("volunteers", index, "role", e.target.value)} /></td>
          <td><input type="number" value={row.dailyRate ?? ""} onChange={(e) => updateList("volunteers", index, "dailyRate", numValue(e.target.value))} /></td>
          <td><select value={row.paymentMethod || "Transfer"} onChange={(e) => updateList("volunteers", index, "paymentMethod", e.target.value)}><option>Transfer</option><option>Tunai</option><option>Lainnya</option></select></td>
          <td><input value={[row.bankName, row.accountNumber].filter(Boolean).join(" / ")} onChange={(e) => updateList("volunteers", index, "accountNumber", e.target.value)} placeholder="rekening" /></td>
          <td><select value={row.status || "Aktif"} onChange={(e) => updateList("volunteers", index, "status", e.target.value)}><option>Aktif</option><option>Nonaktif</option></select></td>
          <td><button className="icon danger" type="button" onClick={() => deleteList("volunteers", index)}><Trash2 size={14}/></button></td>
        </tr>)}{!data.volunteers.length && <EmptyRow colSpan={8}/>}</tbody></table></div>
    </Section>

    <Section title="Master Bahan Operasional" actions={<button type="button" onClick={() => addList("operations", { code: `OP-${String(data.operations.length + 1).padStart(3, "0")}`, name: "", category: "Operasional", unit: "unit", defaultPrice: 0, costNature: "Rutin", vendor: "", status: "Aktif" })}><Plus size={15}/> Tambah</button>}>
      <div className="lpdh-table-wrap"><table className="lpdh-data-table wide"><thead><tr><th>Kode</th><th>Item</th><th>Kategori</th><th>Satuan</th><th>Harga Default</th><th>Sifat</th><th>Vendor</th><th>Status</th><th></th></tr></thead>
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
        </tr>)}{!data.operations.length && <EmptyRow colSpan={9}/>}</tbody></table></div>
    </Section>

    <Section title="Parameter Ref / Pagu" subtitle="Nilai ini memetakan parameter utama pada sheet Ref.">
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

    <div className="lpdh-sticky-save"><button type="button" className="primary" onClick={save} disabled={busy}><Save size={16}/> Simpan Semua Master</button><button type="button" onClick={onReload} disabled={busy}><RefreshCw size={16}/> Muat ulang</button></div>
  </div>;
}

export function DailyPanel({ site, serviceDate, masters, daily, setDaily, finalPlan, preview, api, onSaved, onPreview }) {
  const data = normalizeDaily(daily, serviceDate);
  const [busy, setBusy] = useState(false);
  const masterData = normalizeMasters(masters);

  const update = (key, value) => setDaily({ ...data, [key]: value });
  const updateNested = (parent, key, value) => setDaily({ ...data, [parent]: { ...(data[parent] || {}), [key]: value } });
  const updateProduction = (key, value) => setDaily({ ...data, pm: { ...data.pm, production: { ...data.pm.production, [key]: value } } });
  const updatePmRow = (index, key, value) => {
    const rows = clone(data.pm.rows); rows[index] = { ...rows[index], [key]: value };
    setDaily({ ...data, pm: { ...data.pm, rows } });
  };
  const updateList = (name, index, key, value) => {
    const list = clone(data[name]); list[index] = { ...list[index], [key]: value };
    setDaily({ ...data, [name]: list });
  };
  const deleteList = (name, index) => setDaily({ ...data, [name]: data[name].filter((_, i) => i !== index) });
  const addList = (name, row) => setDaily({ ...data, [name]: [...data[name], row] });

  const pullFinal = () => {
    if (!finalPlan?.payload) return onSaved?.("Belum ada data FINAL dari Kalkulator untuk tanggal ini.", "error");
    const raw = rawFromFinalPlan(finalPlan, serviceDate).map((row) => ({
      ...row,
      date: data.rawInvoiceDate || serviceDate,
      invoiceNo: data.rawInvoiceNo || row.invoiceNo || "",
      evidenceLink: data.rawInvoiceEvidenceLink || row.evidenceLink || "",
    }));
    const payload = finalPlan.payload || {};
    setDaily({
      ...data,
      rawMaterials: raw,
      pm: {
        ...data.pm,
        production: {
          ...data.pm.production,
          produced: data.pm.production.produced || (Number(payload.porsiKecil || 0) + Number(payload.porsiBesar || 0)),
        },
      },
    });
    onSaved?.(`${raw.length} bahan ditarik dari Final Kalkulator. Isi nomor invoice, supplier, dan bukti sebelum generate.`);
  };

  const prepareVolunteers = () => {
    const existing = Object.fromEntries(data.volunteerPayments.map((x) => [x.volunteerCode || x.code || x.name, x]));
    const rows = masterData.volunteers.filter((x) => String(x.status || "Aktif").toLowerCase() !== "nonaktif").map((v) => ({
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
      await api.saveDaily(site, serviceDate, data, "DRAFT");
      onSaved?.("Draft harian tersimpan di cloud.");
      await onPreview?.();
    } finally { setBusy(false); }
  };

  const total = (rows, amountFn) => rows.reduce((s, x) => s + amountFn(x), 0);
  const rawTotal = total(data.rawMaterials, (x) => (Number(x.qty) || 0) * (Number(x.price) || 0));
  const volunteerTotal = total(data.volunteerPayments, (x) => (Number(x.workDays) || 0) * (Number(x.dailyRate) || 0));
  const opTotal = total(data.operations, (x) => (Number(x.qty) || 0) * (Number(x.price) || 0));
  const recipientTotal = total(data.incentiveRecipients, (x) => Number(x.amount) || 0);

  return <div className="lpdh-stack">
    <Section title={`Data Harian · ${serviceDate}`} subtitle="Isi realisasi tanggal ini. Data tidak menimpa tanggal lain." actions={<>
      <button type="button" onClick={pullFinal} disabled={!finalPlan?.payload}><Download size={15}/> Tarik Final Kalkulator</button>
      <button type="button" className="primary" onClick={save} disabled={busy}><Save size={15}/> Simpan Draft</button>
    </>}>
      <div className={finalPlan?.payload ? "lpdh-status-box ok" : "lpdh-status-box warn"}>
        <strong>{finalPlan?.payload ? "Final Kalkulator tersedia" : "Belum ada Final Kalkulator"}</strong>
        <span>{finalPlan?.payload ? `${finalPlan.planName || "Rencana"} · revisi ${finalPlan.revision || 1}` : "Finalkan dulu rencana aktual di Kalkulator agar bahan baku dapat ditarik otomatis."}</span>
      </div>
      <div className={preview?.effective ? "lpdh-status-box ok" : "lpdh-status-box warn"} style={{ marginTop: 10 }}>
        <strong>{preview?.effective ? "Hari Pelayanan Efektif" : "Bukan Hari Pelayanan Efektif"}</strong>
        <span>{preview?.effective ? `HPE ke-${preview?.hpeNumber || 1} minggu ini · otomatis dari kalender pelayanan` : "Tanggal ini tidak dapat digenerate. Atur dari tab Hari Pelayanan Efektif."}</span>
      </div>
      <div className="lpdh-form-grid compact">
        <Field label="Nomor dasar kuitansi relawan" value={data.volunteerReceiptBaseNo} onChange={(v) => update("volunteerReceiptBaseNo", v)} placeholder="mis. RL/0410/2026" />
        <Field label="Tanggal pembayaran relawan" type="date" value={data.volunteerPaymentDate} onChange={(v) => update("volunteerPaymentDate", v)} />
        <Field label="Ref penarikan/bank relawan" value={data.volunteerPaymentReference} onChange={(v) => update("volunteerPaymentReference", v)} />
        <Field label="Bukti bank relawan (1 untuk batch)" value={data.volunteerBatchEvidenceLink} onChange={(v) => update("volunteerBatchEvidenceLink", v)} placeholder="https://..." />
        <Field label="Nomor dasar kuitansi guru/kader" value={data.incentiveReceiptBaseNo} onChange={(v) => update("incentiveReceiptBaseNo", v)} placeholder="mis. IK/0410/2026" />
        <Field label="Tanggal pembayaran guru/kader" type="date" value={data.incentivePaymentDate} onChange={(v) => update("incentivePaymentDate", v)} />
        <Field label="Ref penarikan/bank guru/kader" value={data.incentivePaymentReference} onChange={(v) => update("incentivePaymentReference", v)} />
        <Field label="Bukti bank guru/kader (1 untuk batch)" value={data.incentiveBatchEvidenceLink} onChange={(v) => update("incentiveBatchEvidenceLink", v)} placeholder="https://..." />
        <Field label="No bukti agregat guru (C_Operasional)" value={data.schoolPicOperationalProofNo} onChange={(v) => update("schoolPicOperationalProofNo", v)} placeholder="kosong = nomor dasar-GURU" />
        <Field label="No bukti agregat kader (C_Operasional)" value={data.cadreOperationalProofNo} onChange={(v) => update("cadreOperationalProofNo", v)} placeholder="kosong = nomor dasar-KADER" />
        <Field label="No invoice bahan baku" value={data.rawInvoiceNo} onChange={(v) => update("rawInvoiceNo", v)} />
        <Field label="Tanggal invoice bahan baku" type="date" value={data.rawInvoiceDate || serviceDate} onChange={(v) => update("rawInvoiceDate", v)} />
        <Field label="Link invoice/bukti bahan" value={data.rawInvoiceEvidenceLink} onChange={(v) => update("rawInvoiceEvidenceLink", v)} placeholder="https://..." />
        <Field label="No invoice operasional harian" value={data.operationalInvoiceNo} onChange={(v) => update("operationalInvoiceNo", v)} />
        <Field label="Tanggal invoice operasional" type="date" value={data.operationalInvoiceDate || serviceDate} onChange={(v) => update("operationalInvoiceDate", v)} />
        <Field label="Link invoice/bukti operasional" value={data.operationalInvoiceEvidenceLink} onChange={(v) => update("operationalInvoiceEvidenceLink", v)} placeholder="https://..." />
      </div>
    </Section>

    <Section title="A_PM · Penerima Manfaat & Distribusi">
      <div className="lpdh-table-wrap"><table className="lpdh-data-table wide"><thead><tr><th>Kode</th><th>Kelompok</th><th>Distribusi POP</th><th>Diterima Fleet</th><th>Tidak diterima</th><th>Alasan</th><th>BNBA</th><th>No BAST</th><th>Link BAST</th></tr></thead>
        <tbody>{data.pm.rows.map((row, index) => <tr key={row.code}>
          <td><strong>{row.code}</strong></td><td>{row.label}</td>
          <td><input type="number" value={row.distributed ?? ""} onChange={(e) => updatePmRow(index, "distributed", numValue(e.target.value))}/></td>
          <td><input type="number" value={row.received ?? ""} onChange={(e) => updatePmRow(index, "received", numValue(e.target.value))}/></td>
          <td><input type="number" value={row.notReceived ?? ""} onChange={(e) => updatePmRow(index, "notReceived", numValue(e.target.value))}/></td>
          <td><input value={row.reason || ""} onChange={(e) => updatePmRow(index, "reason", e.target.value)}/></td>
          <td><select value={row.bnba || ""} onChange={(e) => updatePmRow(index, "bnba", e.target.value)}><option value="">—</option><option>Ya</option><option>Tidak</option></select></td>
          <td><input value={row.bastNo || ""} onChange={(e) => updatePmRow(index, "bastNo", e.target.value)}/></td>
          <td><input value={row.bastLink || ""} onChange={(e) => updatePmRow(index, "bastLink", e.target.value)} placeholder="https://..."/></td>
        </tr>)}</tbody></table></div>
      <div className="lpdh-form-grid">
        <Field label="Total diproduksi" type="number" value={data.pm.production.produced} onChange={(v) => updateProduction("produced", v)} />
        <Field label="Organoleptik" type="number" value={data.pm.production.organoleptic} onChange={(v) => updateProduction("organoleptic", v)} />
        <Field label="Retained sample" type="number" value={data.pm.production.retainedSample} onChange={(v) => updateProduction("retainedSample", v)} />
        <Field label="Tidak didistribusikan" type="number" value={data.pm.production.notDistributed} onChange={(v) => updateProduction("notDistributed", v)} />
        <Field label="Buffer" type="number" value={data.pm.production.buffer} onChange={(v) => updateProduction("buffer", v)} />
      </div>
    </Section>

    <Section title="B_BahanBaku" subtitle={`Total sementara Rp ${rawTotal.toLocaleString("id-ID")}. Satu invoice boleh punya banyak barang; nomor bukti unik akan diberi suffix otomatis.`} actions={<>
      <button type="button" onClick={() => setDaily({...data, rawMaterials:data.rawMaterials.map((row)=>({...row,date:data.rawInvoiceDate||serviceDate,invoiceNo:data.rawInvoiceNo||row.invoiceNo||"",evidenceLink:data.rawInvoiceEvidenceLink||row.evidenceLink||""}))})}>Terapkan invoice harian</button>
      <button type="button" onClick={() => addList("rawMaterials", { date: data.rawInvoiceDate || serviceDate, name: "", category: "", qty: 0, unit: "kg", price: 0, supplier: "", invoiceNo: data.rawInvoiceNo || "", evidenceLink: data.rawInvoiceEvidenceLink || "", note: "" })}><Plus size={15}/> Tambah bahan</button>
    </>}>
      <div className="lpdh-table-wrap"><table className="lpdh-data-table extra-wide"><thead><tr><th>Tanggal</th><th>Bahan</th><th>Kategori</th><th>Qty</th><th>Unit</th><th>Harga</th><th>Supplier</th><th>No Invoice/Nota</th><th>Link Bukti</th><th></th></tr></thead>
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
        </tr>)}{!data.rawMaterials.length && <EmptyRow colSpan={10}>Tarik data FINAL dari Kalkulator atau tambah bahan manual.</EmptyRow>}</tbody></table></div>
    </Section>

    <Section title="C_Operasional" subtitle={`Belanja operasional lain Rp ${opTotal.toLocaleString("id-ID")}. Upah relawan dan insentif guru/kader dihitung terpisah lalu masuk total operasional.`} actions={<>
      <button type="button" onClick={() => setDaily({...data, operations:data.operations.map((row)=>({...row,date:data.operationalInvoiceDate||serviceDate,invoiceNo:data.operationalInvoiceNo||row.invoiceNo||"",evidenceLink:data.operationalInvoiceEvidenceLink||row.evidenceLink||""}))})}>Terapkan invoice harian</button>
      <button type="button" onClick={() => addList("operations", { date: data.operationalInvoiceDate || serviceDate, itemCode: "", description: "", qty: 1, unit: "unit", price: 0, invoiceNo: data.operationalInvoiceNo || "", evidenceLink: data.operationalInvoiceEvidenceLink || "", note: "" })}><Plus size={15}/> Tambah</button>
    </>}>
      <div className="lpdh-table-wrap"><table className="lpdh-data-table extra-wide"><thead><tr><th>Tanggal</th><th>Item master</th><th>Deskripsi</th><th>Qty</th><th>Unit</th><th>Harga</th><th>No Invoice/Nota</th><th>Link Bukti</th><th></th></tr></thead>
        <tbody>{data.operations.map((row, index) => <tr key={index}>
          <td><input type="date" value={row.date || serviceDate} onChange={(e) => updateList("operations", index, "date", e.target.value)}/></td>
          <td><select value={row.itemCode || ""} onChange={(e) => { const code=e.target.value; const master=masterData.operations.find((x)=>x.code===code); const list=clone(data.operations); list[index]={...list[index],itemCode:code,description:master?.name||list[index].description,unit:master?.unit||list[index].unit,price:master?.defaultPrice??list[index].price}; setDaily({...data,operations:list}); }}><option value="">— pilih —</option>{masterData.operations.filter((x)=>String(x.status||"Aktif").toLowerCase()!=="nonaktif").map((x)=><option key={x.code} value={x.code}>{x.name}</option>)}</select></td>
          <td><input value={row.description || ""} onChange={(e) => updateList("operations", index, "description", e.target.value)}/></td>
          <td><input type="number" step="0.01" value={row.qty ?? ""} onChange={(e) => updateList("operations", index, "qty", numValue(e.target.value))}/></td>
          <td><input value={row.unit || ""} onChange={(e) => updateList("operations", index, "unit", e.target.value)}/></td>
          <td><input type="number" value={row.price ?? ""} onChange={(e) => updateList("operations", index, "price", numValue(e.target.value))}/></td>
          <td><input value={row.invoiceNo || ""} onChange={(e) => updateList("operations", index, "invoiceNo", e.target.value)}/></td>
          <td><input value={row.evidenceLink || ""} onChange={(e) => updateList("operations", index, "evidenceLink", e.target.value)} placeholder="https://..."/></td>
          <td><button className="icon danger" onClick={() => deleteList("operations", index)} type="button"><Trash2 size={14}/></button></td>
        </tr>)}{!data.operations.length && <EmptyRow colSpan={9}/>}</tbody></table></div>
    </Section>

    <Section title="C1_Relawan" subtitle={`Total upah relawan Rp ${volunteerTotal.toLocaleString("id-ID")}. Nomor dasar kuitansi dapat disiapkan di awal minggu; suffix per orang dibuat otomatis.`} actions={<button type="button" onClick={prepareVolunteers}><RefreshCw size={15}/> Siapkan dari master</button>}>
      <div className="lpdh-table-wrap"><table className="lpdh-data-table extra-wide"><thead><tr><th>Nama</th><th>Tugas</th><th>Tgl Bayar</th><th>Hari Kerja</th><th>Tarif/Hari</th><th>Jumlah</th><th>Metode</th><th>Kuitansi override</th><th>Link Bukti</th></tr></thead>
        <tbody>{data.volunteerPayments.map((row, index) => <tr key={row.volunteerCode || index}>
          <td>{row.name}</td><td>{row.role}</td>
          <td><input type="date" value={row.date || ""} onChange={(e) => updateList("volunteerPayments", index, "date", e.target.value)}/></td>
          <td><input type="number" step="0.5" value={row.workDays ?? ""} onChange={(e) => updateList("volunteerPayments", index, "workDays", numValue(e.target.value))}/></td>
          <td><input type="number" value={row.dailyRate ?? ""} onChange={(e) => updateList("volunteerPayments", index, "dailyRate", numValue(e.target.value))}/></td>
          <td>Rp {((Number(row.workDays)||0)*(Number(row.dailyRate)||0)).toLocaleString("id-ID")}</td>
          <td><select value={row.paymentMethod || "Transfer"} onChange={(e) => updateList("volunteerPayments", index, "paymentMethod", e.target.value)}><option>Transfer</option><option>Tunai</option><option>Lainnya</option></select></td>
          <td><input value={row.receiptNo || ""} onChange={(e) => updateList("volunteerPayments", index, "receiptNo", e.target.value)} placeholder="kosong = pakai nomor dasar"/></td>
          <td><input value={row.evidenceLink || ""} onChange={(e) => updateList("volunteerPayments", index, "evidenceLink", e.target.value)} placeholder="https://..."/></td>
        </tr>)}{!data.volunteerPayments.length && <EmptyRow colSpan={9}>Klik “Siapkan dari master”.</EmptyRow>}</tbody></table></div>
    </Section>

    <Section title="Insentif Guru / Kader (bagian operasional)" subtitle={`Total Rp ${recipientTotal.toLocaleString("id-ID")}. Satu nomor dasar kuitansi dapat dipecah otomatis per penerima.`} actions={<button type="button" onClick={() => addList("incentiveRecipients", { type: "Guru", name: "", unitName: "", date: serviceDate, amount: 0, receiptNo: "", evidenceLink: "" })}><Plus size={15}/> Tambah penerima</button>}>
      <div className="lpdh-table-wrap"><table className="lpdh-data-table"><thead><tr><th>Jenis</th><th>Nama</th><th>Sekolah/Posyandu</th><th>Tgl</th><th>Nilai</th><th>Kuitansi override</th><th>Link Bukti</th><th></th></tr></thead>
        <tbody>{data.incentiveRecipients.map((row,index)=><tr key={index}>
          <td><select value={row.type || "Guru"} onChange={(e)=>updateList("incentiveRecipients",index,"type",e.target.value)}><option>Guru</option><option>Kader</option></select></td>
          <td><input value={row.name||""} onChange={(e)=>updateList("incentiveRecipients",index,"name",e.target.value)}/></td>
          <td><input value={row.unitName||""} onChange={(e)=>updateList("incentiveRecipients",index,"unitName",e.target.value)}/></td>
          <td><input type="date" value={row.date||serviceDate} onChange={(e)=>updateList("incentiveRecipients",index,"date",e.target.value)}/></td>
          <td><input type="number" value={row.amount??""} onChange={(e)=>updateList("incentiveRecipients",index,"amount",numValue(e.target.value))}/></td>
          <td><input value={row.receiptNo||""} onChange={(e)=>updateList("incentiveRecipients",index,"receiptNo",e.target.value)}/></td>
          <td><input value={row.evidenceLink||""} onChange={(e)=>updateList("incentiveRecipients",index,"evidenceLink",e.target.value)} placeholder="https://..."/></td>
          <td><button className="icon danger" type="button" onClick={()=>deleteList("incentiveRecipients",index)}><Trash2 size={14}/></button></td>
        </tr>)}{!data.incentiveRecipients.length&&<EmptyRow colSpan={8}/>}</tbody></table></div>
    </Section>

    <Section title="D_Insentif · Ketersediaan & Mutu Layanan" subtitle="Ini Insentif ke Mitra/Yayasan sesuai workbook, berbeda dari insentif guru/kader yang masuk biaya operasional.">
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
        <Field label="Referensi transaksi VA" value={data.incentive.vaReference} onChange={(v)=>updateNested("incentive","vaReference",v)}/>
      </div>
    </Section>

    <Section title="E_Saldo & F_TopUp" subtitle="Usulan SPPG pada F_TopUp dihitung otomatis dari bahan baku + operasional + Insentif Ketersediaan dan Mutu Layanan. Kolom persetujuan PPK tidak diisi oleh aplikasi.">
      <div className="lpdh-form-grid">
        <Field label="Saldo awal bahan" type="number" value={data.balance.openingRaw} onChange={(v)=>updateNested("balance","openingRaw",v)}/>
        <Field label="Saldo awal operasional" type="number" value={data.balance.openingOperational} onChange={(v)=>updateNested("balance","openingOperational",v)}/>
        <Field label="Saldo awal insentif" type="number" value={data.balance.openingIncentive} onChange={(v)=>updateNested("balance","openingIncentive",v)}/>
        <Field label="Saldo VA rekening koran" type="number" value={data.balance.bankBalance} onChange={(v)=>updateNested("balance","bankBalance",v)}/>
      </div>
      <div className="lpdh-inline-actions"><button type="button" onClick={()=>addList("topups",{date:serviceDate,reference:"",rawAmount:0,operationalAmount:0,incentiveAmount:0,receiptNo:"",evidenceLink:""})}><Plus size={15}/> Tambah penerimaan TopUp</button></div>
      <div className="lpdh-table-wrap"><table className="lpdh-data-table"><thead><tr><th>Tgl</th><th>SP2D/Ref</th><th>Bahan</th><th>Operasional</th><th>Insentif</th><th>No Kuitansi</th><th>Link</th><th></th></tr></thead><tbody>
        {data.topups.map((row,index)=><tr key={index}>
          <td><input type="date" value={row.date||""} onChange={(e)=>updateList("topups",index,"date",e.target.value)}/></td>
          <td><input value={row.reference||""} onChange={(e)=>updateList("topups",index,"reference",e.target.value)}/></td>
          <td><input type="number" value={row.rawAmount??""} onChange={(e)=>updateList("topups",index,"rawAmount",numValue(e.target.value))}/></td>
          <td><input type="number" value={row.operationalAmount??""} onChange={(e)=>updateList("topups",index,"operationalAmount",numValue(e.target.value))}/></td>
          <td><input type="number" value={row.incentiveAmount??""} onChange={(e)=>updateList("topups",index,"incentiveAmount",numValue(e.target.value))}/></td>
          <td><input value={row.receiptNo||""} onChange={(e)=>updateList("topups",index,"receiptNo",e.target.value)}/></td>
          <td><input value={row.evidenceLink||""} onChange={(e)=>updateList("topups",index,"evidenceLink",e.target.value)} placeholder="https://..."/></td>
          <td><button className="icon danger" type="button" onClick={()=>deleteList("topups",index)}><Trash2 size={14}/></button></td>
        </tr>)}{!data.topups.length&&<EmptyRow colSpan={8}/>}</tbody></table></div>
    </Section>

    <Section title="Rencana upload">
      <div className="lpdh-form-grid">
        <Field label="Tanggal upload" type="date" value={data.upload.date} onChange={(v)=>updateNested("upload","date",v)}/>
        <Field label="Jam upload" type="time" value={data.upload.time} onChange={(v)=>updateNested("upload","time",v)}/>
      </div>
    </Section>

    <div className="lpdh-sticky-save"><button className="primary" type="button" onClick={save} disabled={busy}><Save size={16}/> Simpan & Validasi</button></div>
  </div>;
}

function deriveNumbers(rows, base, overrideKey = "receiptNo") {
  const active = rows.map((row, index) => ({ row, index, base: String(row[overrideKey] || base || "").trim() })).filter((x) => x.base);
  const count = active.reduce((map, x) => ({ ...map, [x.base]: (map[x.base] || 0) + 1 }), {});
  const seen = {};
  return active.map((x) => {
    seen[x.base] = (seen[x.base] || 0) + 1;
    return {
      ...x.row,
      generatedNo: count[x.base] > 1 ? `${x.base}-${String(seen[x.base]).padStart(3, "0")}` : x.base,
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
  const groupInvoices = (rows) => Object.values((rows || []).reduce((groups, row) => {
    const no = String(row.invoiceNo || "").trim();
    if (!no) return groups;
    if (!groups[no]) groups[no] = { invoiceNo: no, rows: [] };
    groups[no].rows.push(row);
    return groups;
  }, {}));
  const rawInvoices = useMemo(() => groupInvoices(data.rawMaterials), [data.rawMaterials]);
  const operationalInvoices = useMemo(() => groupInvoices(data.operations), [data.operations]);
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
