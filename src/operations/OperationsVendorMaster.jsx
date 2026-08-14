import React, { useEffect, useMemo, useState } from "react";
import { RefreshCw, Save } from "lucide-react";
import { operationsApi } from "./apiClient";

function rowKey(item, idx) {
  return `${item.code}|${item.site_code || "GLOBAL"}|${item.category_code || "ALL"}|${idx}`;
}

export default function OperationsVendorMaster({ fixedSite = "" }) {
  const [site, setSite] = useState(fixedSite || "");
  const [items, setItems] = useState([]);
  const [edits, setEdits] = useState({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState("");
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
      (data?.items || []).forEach((item, idx) => {
        next[rowKey(item, idx)] = item.lead_time_days_before_cooking == null ? "" : String(item.lead_time_days_before_cooking);
      });
      setEdits(next);
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

  return (
    <section className="ops-module">
      <div className="ops-module-header">
        <div>
          <span className="ops-kicker">MASTER VERSIONED</span>
          <h3>Vendor & Lead Time — EDITABLE</h3>
          <p>Lead time boleh diubah OWNER. Perubahan dibuat sebagai rule efektif baru sehingga histori PO lama tidak ikut berubah.</p>
        </div>
        <div className="ops-inline-controls">
          <select value={activeSite} disabled={Boolean(fixedSite)} onChange={(e) => setSite(e.target.value)}><option value="">Semua site</option><option value="MAJA">MAJA</option><option value="CEMPLANG">CEMPLANG</option></select>
          <button type="button" onClick={load} disabled={loading}><RefreshCw size={15} /> Refresh</button>
        </div>
      </div>
      {error && <div className="ops-error">{error}</div>}
      {message && <div className="ops-success">{message}</div>}
      <div className="ops-summary-strip"><span>Rule aktif <strong>{items.length}</strong></span><span>Belum disimpan <strong>{dirtyCount}</strong></span></div>
      <div className="ops-table-wrap">
        <table className="ops-table">
          <thead><tr><th>Vendor</th><th>Site</th><th>Kategori</th><th>Lead Time — EDIT</th><th>Payment Term</th><th>Via</th><th>Reimbursement</th><th>Efektif</th><th>Aksi</th></tr></thead>
          <tbody>
            {items.map((item, idx) => {
              const key = rowKey(item, idx);
              const current = item.lead_time_days_before_cooking == null ? "" : String(item.lead_time_days_before_cooking);
              const edit = String(edits[key] ?? current);
              const dirty = edit !== current;
              return (
                <tr key={key}>
                  <td><strong>{item.name}</strong><div className="ops-muted">{item.code}</div></td>
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
                  <td><button type="button" onClick={() => saveLead(item, idx)} disabled={!dirty || saving === key}><Save size={14} /> {saving === key ? "Menyimpan..." : "Simpan"}</button></td>
                </tr>
              );
            })}
            {!loading && items.length === 0 && <tr><td colSpan="9" className="ops-empty-cell">Belum ada vendor aktif.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}
