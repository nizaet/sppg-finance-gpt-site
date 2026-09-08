import React, { useEffect, useMemo, useRef, useState } from "react";
import { MessageCircle, RefreshCw, Save } from "lucide-react";
import { operationsApi } from "./apiClient";
import { useSiteState } from './useSiteState.js';
import OperationsSiteSwitcher from './OperationsSiteSwitcher.jsx';

function rowKey(item, idx) {
  return `${item.code}|${item.site_code || "GLOBAL"}|${item.category_code || "ALL"}|${idx}`;
}

export default function OperationsVendorMaster({ fixedSite = "", routeSite = '', onSiteChange }) {
  const [site, setSite] = useState(fixedSite || "");
  const activeSite = routeSite === 'ALL' ? '' : (routeSite || fixedSite || site);
  const [loadedAt, setLoadedAt] = useSiteState(activeSite, null);
  const loadRequests = useRef(new Map());
  const [items, setItems] = useSiteState(activeSite, []);
  const [vendorCatalog, setVendorCatalog] = useSiteState(activeSite, []);
  const [edits, setEdits] = useSiteState(activeSite, {});
  const [vendorEdits, setVendorEdits] = useSiteState(activeSite, {});
  const [phoneEdits, setPhoneEdits] = useSiteState(activeSite, {});
  const [loading, setLoading] = useSiteState(activeSite, false);
  const [saving, setSaving] = useSiteState(activeSite, "");
  const [savingPhone, setSavingPhone] = useSiteState(activeSite, "");
  const [error, setError] = useSiteState(activeSite, "");
  const [message, setMessage] = useSiteState(activeSite, "");

  const load = async () => {
    const requestId = (loadRequests.current.get(activeSite) || 0) + 1;
    loadRequests.current.set(activeSite, requestId);
    const isLatest = () => loadRequests.current.get(activeSite) === requestId;
    setLoading(true);
    setError("");
    try {
      const [data, catalogData] = await Promise.all([
        operationsApi.getReferenceVendors(activeSite),
        activeSite ? operationsApi.getReferenceVendors("") : Promise.resolve(null),
      ]);
      if (!isLatest()) return;
      const rows = data?.items || [];
      const catalogRows = catalogData?.items || rows;
      setItems(rows);
      setVendorCatalog(catalogRows);
      const next = {};
      const nextVendors = {};
      const nextPhones = {};
      rows.forEach((item, idx) => {
        const key = rowKey(item, idx);
        next[key] = item.lead_time_days_before_cooking == null ? "" : String(item.lead_time_days_before_cooking);
        nextVendors[key] = item.code;
      });
      catalogRows.forEach((item) => {
        if (item?.code && nextPhones[item.code] == null) nextPhones[item.code] = String(item.metadata?.whatsapp_phone || "");
      });
      setEdits(next);
      setVendorEdits(nextVendors);
      setPhoneEdits(nextPhones);
      setLoadedAt(new Date().toISOString());
    } catch (err) {
      if (isLatest()) setError(err.message || "Gagal mengambil master vendor");
    } finally {
      if (isLatest()) setLoading(false);
    }
  };

  useEffect(() => { if (!loadedAt) load(); }, [activeSite]);

  const vendorChoices = useMemo(() => {
    const map = new Map();
    vendorCatalog.forEach((item) => {
      if (item?.code) map.set(item.code, item.name || item.code);
    });
    return Array.from(map.entries()).map(([code, name]) => ({ code, name })).sort((a, b) => a.name.localeCompare(b.name, "id"));
  }, [vendorCatalog]);

  const dirtyCount = useMemo(() => items.filter((item, idx) => {
    const key = rowKey(item, idx);
    const currentLead = item.lead_time_days_before_cooking == null ? "" : String(item.lead_time_days_before_cooking);
    const leadDirty = String(edits[key] ?? currentLead) !== currentLead;
    const vendorDirty = String(vendorEdits[key] ?? item.code) !== String(item.code);
    return leadDirty || vendorDirty;
  }).length, [items, edits, vendorEdits]);

  const phoneDirtyCount = useMemo(() => {
    const vendors = new Map();
    vendorCatalog.forEach((item) => {
      if (item?.code && !vendors.has(item.code)) vendors.set(item.code, String(item.metadata?.whatsapp_phone || ""));
    });
    return Array.from(vendors.entries()).filter(([code, current]) => String(phoneEdits[code] ?? current).trim() !== current).length;
  }, [vendorCatalog, phoneEdits]);

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
      {!fixedSite && <OperationsSiteSwitcher title="Vendor & Lead Time" label="Pilih site vendor"
        sites={[["ALL", "Semua"], ["MAJA", "Maja"], ["CEMPLANG", "Cemplang"]]}
        activeSite={activeSite || 'ALL'} onChange={onSiteChange || (value => setSite(value === 'ALL' ? '' : value))} />}
      {loadedAt && <p className="ops-data-freshness">Data terakhir ditarik: {new Date(loadedAt).toLocaleString('id-ID', { timeZone: 'Asia/Jakarta' })}. Refresh untuk pembaruan terbaru.</p>}
      <div className="ops-module-header">
        <div>
          <span className="ops-kicker">MASTER VERSIONED</span>
          <h3>Vendor & Lead Time — EDITABLE</h3>
          <p>Vendor per site/kategori dan lead time disimpan di database versioned. Perubahan baru berlaku mulai hari ini tanpa menimpa histori rule sebelumnya.</p>
        </div>
        <div className="ops-inline-controls">
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
