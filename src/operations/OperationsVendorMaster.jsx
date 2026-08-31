import React, { useEffect, useMemo, useState } from "react";
import { MessageCircle, RefreshCw, Save } from "lucide-react";
import { operationsApi } from "./apiClient";

function rowKey(item, idx) {
  return `${item.code}|${item.site_code || "GLOBAL"}|${item.category_code || "ALL"}|${idx}`;
}

export default function OperationsVendorMaster({ fixedSite = "" }) {
  const [site, setSite] = useState(fixedSite || "");
  const [items, setItems] = useState([]);
  const [edits, setEdits] = useState({});
  const [vendorEdits, setVendorEdits] = useState({});
  const [phoneEdits, setPhoneEdits] = useState({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState("");
  const [savingPhone, setSavingPhone] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (fixedSite && site !== fixedSite) setSite(fixedSite);
  }, [fixedSite, site]);

  const activeSite = fixedSite || site;

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await operationsApi.getReferenceVendors(activeSite);
      const rows = data?.items || [];
      setItems(rows);
      const next = {};
      const nextVendors = {};
      const nextPhones = {};
      rows.forEach((item, idx) => {
        const key = rowKey(item, idx);
        next[key] = item.lead_time_days_before_cooking == null ? "" : String(item.lead_time_days_before_cooking);
        nextVendors[key] = item.code;
        nextPhones[item.code] = String(item.metadata?.whatsapp_phone || "");
      });
      setEdits(next);
      setVendorEdits(nextVendors);
      setPhoneEdits(nextPhones);
    } catch (err) {
      setError(err.message || "Gagal mengambil master vendor");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [activeSite]);

  const vendorChoices = useMemo(() => {
    const map = new Map();
    items.forEach((item) => {
      if (item?.code) map.set(item.code, item.name || item.code);
    });
    return Array.from(map.entries()).map(([code, name]) => ({ code, name })).sort((a, b) => a.name.localeCompare(b.name, "id"));
  }, [items]);

  const dirtyCount = useMemo(() => items.filter((item, idx) => {
    const key = rowKey(item, idx);
    const currentLead = item.lead_time_days_before_cooking == null ? "" : String(item.lead_time_days_before_cooking);
    const leadDirty = String(edits[key] ?? currentLead) !== currentLead;
    const vendorDirty = String(vendorEdits[key] ?? item.code) !== String(item.code);
    return leadDirty || vendorDirty;
  }).length, [items, edits, vendorEdits]);

  const phoneDirtyCount = useMemo(() => {
    const vendors = new Map();
    items.forEach((item) => vendors.set(item.code, String(item.metadata?.whatsapp_phone || "")));
    return Array.from(vendors.entries()).filter(([code, current]) => String(phoneEdits[code] ?? current).trim() !== current).length;
  }, [items, phoneEdits]);

  const saveRule = async (item, idx) => {
    const key = rowKey(item, idx);
    const raw = String(edits[key] ?? "").trim();
    const value = Number(raw);
    const newVendor = String(vendorEdits[key] || item.code).trim().toUpperCase();
    if (!raw || !Number.isInteger(value) || value < 0 || value > 30) {
      setError("Lead time harus bilangan bulat 0–30 hari.");
      return;
    }
    if (!newVendor) {
      setError("Vendor wajib dipilih.");
      return;
    }
    const oldLead = item.lead_time_days_before_cooking;
    const leadDirty = Number(oldLead) !== value;
    const vendorDirty = newVendor !== String(item.code).toUpperCase();
    if (!leadDirty && !vendorDirty) return;

    const target = vendorChoices.find((row) => row.code === newVendor);
    const scope = `${item.site_code || "GLOBAL"}${item.category_code ? ` / ${item.category_code}` : ""}`;
    const oldLeadLabel = oldLead == null ? "belum diatur" : `H-${oldLead}`;
    const nextLeadLabel = `H-${value}`;
    const vendorText = vendorDirty ? `${item.name} → ${target?.name || newVendor}` : item.name;
    if (!window.confirm(`Simpan rule ${scope}?\n\nVendor: ${vendorText}\nLead time: ${oldLeadLabel} → ${nextLeadLabel}\n\nPerubahan berlaku mulai hari ini dan histori rule lama tetap disimpan.`)) return;

    setSaving(key);
    setError("");
    setMessage("");
    try {
      const result = await operationsApi.updateVendorLeadTime({
        vendor_code: item.code,
        new_vendor_code: newVendor,
        site_code: item.site_code || null,
        category_code: item.category_code || null,
        lead_time_days_before_cooking: value,
        note: "Updated vendor/lead time from Pusat Operasional",
      });
      const vendorLabel = target?.name || result.vendorCode || newVendor;
      if (result.vendorChanged) {
        setMessage(`Vendor ${scope} berhasil dipindah ke ${vendorLabel}, lead time ${nextLeadLabel}. Histori rule lama dipertahankan.`);
      } else if (result.changed) {
        setMessage(`Lead time ${item.name} berhasil diubah menjadi ${nextLeadLabel}. Histori rule lama dipertahankan.`);
      } else {
        setMessage("Tidak ada perubahan vendor atau lead time.");
      }
      await load();
    } catch (err) {
      setError(err.message || "Gagal mengubah vendor / lead time");
    } finally {
      setSaving("");
    }
  };

  const savePhone = async (item) => {
    const value = String(phoneEdits[item.code] || "").trim();
    if (!value) {
      setError("Nomor WhatsApp vendor wajib diisi.");
      return;
    }
    if (!window.confirm(`Simpan nomor WhatsApp ${item.name}: ${value}?`)) return;
    setSavingPhone(item.code);
    setError("");
    setMessage("");
    try {
      const result = await operationsApi.updateVendorWhatsApp(item.code, value);
      setMessage(`Nomor WhatsApp ${item.name} tersimpan: ${result.whatsappPhone}.`);
      await load();
    } catch (err) {
      setError(err.message || "Gagal menyimpan nomor WhatsApp vendor");
    } finally {
      setSavingPhone("");
    }
  };

  return (
    <section className="ops-module">
      <div className="ops-module-header">
        <div>
          <span className="ops-kicker">MASTER VERSIONED</span>
          <h3>Vendor & Lead Time — EDITABLE</h3>
          <p>Vendor per site/kategori dan lead time disimpan di database versioned. Perubahan baru berlaku mulai hari ini tanpa menimpa histori rule sebelumnya.</p>
        </div>
        <div className="ops-inline-controls">
          <select value={activeSite} disabled={Boolean(fixedSite)} onChange={(e) => setSite(e.target.value)}><option value="">Semua site</option><option value="MAJA">MAJA</option><option value="CEMPLANG">CEMPLANG</option></select>
          <button type="button" onClick={load} disabled={loading}><RefreshCw size={15} /> Refresh</button>
        </div>
      </div>
      {error && <div className="ops-error">{error}</div>}
      {message && <div className="ops-success">{message}</div>}
      <div className="ops-summary-strip"><span>Rule aktif <strong>{items.length}</strong></span><span>Vendor / lead belum disimpan <strong>{dirtyCount}</strong></span><span>Nomor belum disimpan <strong>{phoneDirtyCount}</strong></span></div>
      <div className="ops-table-wrap">
        <table className="ops-table">
          <thead><tr><th>Vendor — EDIT</th><th>WhatsApp Vendor</th><th>Site</th><th>Kategori</th><th>Lead Time — EDIT</th><th>Payment Term</th><th>Via</th><th>Reimbursement</th><th>Efektif</th><th>Aksi</th></tr></thead>
          <tbody>
            {items.map((item, idx) => {
              const key = rowKey(item, idx);
              const current = item.lead_time_days_before_cooking == null ? "" : String(item.lead_time_days_before_cooking);
              const edit = String(edits[key] ?? current);
              const selectedVendor = String(vendorEdits[key] ?? item.code);
              const leadDirty = edit !== current;
              const vendorDirty = selectedVendor !== String(item.code);
              const dirty = leadDirty || vendorDirty;
              const currentPhone = String(item.metadata?.whatsapp_phone || "");
              const phoneEdit = String(phoneEdits[item.code] ?? currentPhone);
              const phoneDirty = phoneEdit.trim() !== currentPhone;
              return (
                <tr key={key}>
                  <td>
                    <select value={selectedVendor} onChange={(e) => setVendorEdits((x) => ({ ...x, [key]: e.target.value }))}>
                      {vendorChoices.map((vendor) => <option key={vendor.code} value={vendor.code}>{vendor.name} ({vendor.code})</option>)}
                    </select>
                    {vendorDirty && <div className="ops-muted">Vendor baru belum disimpan</div>}
                  </td>
                  <td>
                    <input type="tel" value={phoneEdit} onChange={(e) => setPhoneEdits((x) => ({ ...x, [item.code]: e.target.value }))} placeholder="contoh 0812... / +62812..." />
                    <div className="ops-muted">Nomor mengikuti master vendor, bukan kategori.</div>
                  </td>
                  <td><strong>{item.site_code || "GLOBAL"}</strong></td>
                  <td>{item.category_code || (item.metadata?.categories || []).join(", ") || "Semua"}</td>
                  <td>
                    <div className="ops-row-actions">
                      <span>H-</span>
                      <input className="ops-qty-input" style={{width:80}} type="number" min="0" max="30" step="1" value={edit} onChange={(e) => setEdits((x) => ({ ...x, [key]: e.target.value }))} placeholder="hari" />
                    </div>
                    {leadDirty && <div className="ops-muted">Lead time baru belum disimpan</div>}
                  </td>
                  <td>{item.payment_term_code || "Belum dikunci"}</td>
                  <td>{item.intermediary_code || "-"}</td>
                  <td>{item.internal_reimbursement ? "Ya" : "Tidak"}</td>
                  <td>{item.effective_from || "-"}</td>
                  <td>
                    <div className="ops-row-actions">
                      <button type="button" onClick={() => saveRule(item, idx)} disabled={!dirty || saving === key}><Save size={14} /> {saving === key ? "Menyimpan..." : "Vendor & Lead"}</button>
                      <button type="button" onClick={() => savePhone(item)} disabled={!phoneDirty || savingPhone === item.code}><MessageCircle size={14} /> {savingPhone === item.code ? "Menyimpan..." : "Nomor WA"}</button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {!loading && items.length === 0 && <tr><td colSpan="10" className="ops-empty-cell">Belum ada vendor aktif.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}