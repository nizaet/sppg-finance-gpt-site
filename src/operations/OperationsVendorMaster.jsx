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
      setItems(data?.items || []);
      const next = {};
      const nextPhones = {};
      (data?.items || []).forEach((item, idx) => {
        next[rowKey(item, idx)] = item.lead_time_days_before_cooking == null ? "" : String(item.lead_time_days_before_cooking);
        nextPhones[item.code] = String(item.metadata?.whatsapp_phone || "");
      });
      setEdits(next);
      setPhoneEdits(nextPhones);
    } catch (err) {
      setError(err.message || "Gagal mengambil master vendor");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [activeSite]);

  const dirtyCount = useMemo(() => items.filter((item, idx) => {
    const current = item.lead_time_days_before_cooking == null ? "" : String(item.lead_time_days_before_cooking);
    return String(edits[rowKey(item, idx)] ?? current) !== current;
  }).length, [items, edits]);

  const phoneDirtyCount = useMemo(() => {
    const vendors = new Map();
    items.forEach((item) => vendors.set(item.code, String(item.metadata?.whatsapp_phone || "")));
    return Array.from(vendors.entries()).filter(([code, current]) => String(phoneEdits[code] ?? current).trim() !== current).length;
  }, [items, phoneEdits]);

  const saveLead = async (item, idx) => {
    const key = rowKey(item, idx);
    const raw = String(edits[key] ?? "").trim();
    const value = Number(raw);
    if (!raw || !Number.isInteger(value) || value < 0 || value > 30) {
      setError("Lead time harus bilangan bulat 0–30 hari.");
      return;
    }
    const oldValue = item.lead_time_days_before_cooking;
    if (Number(oldValue) === value) return;
    const scope = `${item.site_code || "GLOBAL"}${item.category_code ? ` / ${item.category_code}` : ""}`;
    if (!window.confirm(`Ubah lead time ${item.name} (${scope}) dari ${oldValue == null ? "belum diatur" : `H-${oldValue}`} menjadi H-${value}?\n\nHistori rule lama akan tetap disimpan.`)) return;

    setSaving(key);
    setError("");
    setMessage("");
    try {
      const result = await operationsApi.updateVendorLeadTime({
        vendor_code: item.code,
        site_code: item.site_code || null,
        category_code: item.category_code || null,
        lead_time_days_before_cooking: value,
      });
      setMessage(result.changed ? `Lead time ${item.name} berhasil diubah menjadi H-${value}. Histori rule lama dipertahankan.` : "Tidak ada perubahan lead time.");
      await load();
    } catch (err) {
      setError(err.message || "Gagal mengubah lead time");
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
          <p>YAYASAN dapat mengubah lead time dan nomor WhatsApp vendor. Nomor disimpan terpusat dan dipakai tombol kirim PO maupun laporan pembayaran.</p>
        </div>
        <div className="ops-inline-controls">
          <select value={activeSite} disabled={Boolean(fixedSite)} onChange={(e) => setSite(e.target.value)}><option value="">Semua site</option><option value="MAJA">MAJA</option><option value="CEMPLANG">CEMPLANG</option></select>
          <button type="button" onClick={load} disabled={loading}><RefreshCw size={15} /> Refresh</button>
        </div>
      </div>
      {error && <div className="ops-error">{error}</div>}
      {message && <div className="ops-success">{message}</div>}
      <div className="ops-summary-strip"><span>Rule aktif <strong>{items.length}</strong></span><span>Lead time belum disimpan <strong>{dirtyCount}</strong></span><span>Nomor belum disimpan <strong>{phoneDirtyCount}</strong></span></div>
      <div className="ops-table-wrap">
        <table className="ops-table">
          <thead><tr><th>Vendor</th><th>WhatsApp Vendor</th><th>Site</th><th>Kategori</th><th>Lead Time — EDIT</th><th>Payment Term</th><th>Via</th><th>Reimbursement</th><th>Efektif</th><th>Aksi</th></tr></thead>
          <tbody>
            {items.map((item, idx) => {
              const key = rowKey(item, idx);
              const current = item.lead_time_days_before_cooking == null ? "" : String(item.lead_time_days_before_cooking);
              const edit = String(edits[key] ?? current);
              const dirty = edit !== current;
              const currentPhone = String(item.metadata?.whatsapp_phone || "");
              const phoneEdit = String(phoneEdits[item.code] ?? currentPhone);
              const phoneDirty = phoneEdit.trim() !== currentPhone;
              return (
                <tr key={key}>
                  <td><strong>{item.name}</strong><div className="ops-muted">{item.code}</div></td>
                  <td>
                    <input type="tel" value={phoneEdit} onChange={(e) => setPhoneEdits((x) => ({ ...x, [item.code]: e.target.value }))} placeholder="contoh 0812... / +62812..." />
                    <div className="ops-muted">Disimpan sebagai nomor wa.me internasional.</div>
                  </td>
                  <td><strong>{item.site_code || "GLOBAL"}</strong></td>
                  <td>{item.category_code || (item.metadata?.categories || []).join(", ") || "Semua"}</td>
                  <td>
                    <div className="ops-row-actions">
                      <span>H-</span>
                      <input className="ops-qty-input" style={{width:80}} type="number" min="0" max="30" step="1" value={edit} onChange={(e) => setEdits((x) => ({ ...x, [key]: e.target.value }))} placeholder="hari" />
                    </div>
                    {dirty && <div className="ops-muted">Belum disimpan</div>}
                  </td>
                  <td>{item.payment_term_code || "Belum dikunci"}</td>
                  <td>{item.intermediary_code || "-"}</td>
                  <td>{item.internal_reimbursement ? "Ya" : "Tidak"}</td>
                  <td>{item.effective_from || "-"}</td>
                  <td>
                    <div className="ops-row-actions">
                      <button type="button" onClick={() => saveLead(item, idx)} disabled={!dirty || saving === key}><Save size={14} /> {saving === key ? "Menyimpan..." : "Lead Time"}</button>
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
