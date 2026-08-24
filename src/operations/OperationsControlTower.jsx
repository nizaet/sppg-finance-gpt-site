import React, { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CalendarDays, CheckCircle2, PackageCheck, RefreshCw, WalletCards } from "lucide-react";
import { operationsApi, hasOperationsBackend } from "./apiClient";
import { mockControlTower } from "./mockControlTower";
import "./operations.css";

const metricDefs = [
  ["poDueToday", "PO Harus Dikerjakan Hari Ini", CalendarDays],
  ["poOverdue", "PO Benar-benar Terlambat", AlertTriangle],
  ["poShortage", "PO Sudah Dilakukan · Cek Sisa", AlertTriangle],
  ["receiptsToday", "Barang Datang Hari Ini", PackageCheck],
  ["receivingIssues", "Penerimaan Ada Selisih", AlertTriangle],
  ["paymentsDue", "Pembayaran Jatuh Tempo", WalletCards],
  ["reviewQueue", "Perlu Review", CheckCircle2],
];

const laneLabels = {
  procurement: "PO Vendor — sama dengan Pengingat PO",
  receiving: "Penerimaan / Barang Datang — termasuk GPTS",
  payments: "Invoice & Pembayaran Vendor",
  accountant: "Akuntan",
  bgn: "Maker / Approval / BGN",
};

function siteCode(site) {
  const label = String(site?.siteLabel || "").toUpperCase();
  if (label.includes("CEMPLANG")) return "CEMPLANG";
  if (label.includes("MAJA")) return "MAJA";
  return "SITE";
}

function Metric({ value, label, Icon }) {
  return (
    <div className="ops-metric">
      <Icon size={18} />
      <div><strong>{Number(value || 0)}</strong><span>{label}</span></div>
    </div>
  );
}

function Lane({ name, items = [] }) {
  return (
    <section className="ops-lane">
      <header><h4>{laneLabels[name] || name}</h4><span>{items.length}</span></header>
      {items.length === 0 ? (
        <div className="ops-empty">Belum ada item aktif.</div>
      ) : (
        <div className="ops-list">
          {items.map((item, idx) => (
            <div className="ops-list-item" key={item.id || `${name}-${idx}`}>
              <div><strong>{item.title || item.vendor || item.status || "Item"}</strong>{item.subtitle && <span>{item.subtitle}</span>}</div>
              <span className={`ops-status ops-status-${String(item.severity || item.status || "info").toLowerCase()}`}>{item.badge || item.status || "INFO"}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function SitePanel({ site, date }) {
  const code = siteCode(site);
  const accent = code === "MAJA" ? "#0f5138" : "#174a7e";
  const soft = code === "MAJA" ? "#eaf6ef" : "#edf4fb";
  return (
    <section className="ops-site" style={{ borderTop: `6px solid ${accent}`, borderRadius: 14, overflow: "hidden" }}>
      <div className="ops-site-title" style={{ background: soft, padding: "14px 16px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ background: accent, color: "white", borderRadius: 999, padding: "5px 10px", fontWeight: 900, fontSize: 12 }}>{code}</span>
          <h3 style={{ margin: 0 }}>{site.siteLabel}</h3>
        </div>
        <span>{date}</span>
      </div>
      {site.procurementError && <div className="ops-error" style={{ margin: 12 }}>Pengingat PO gagal direkonsiliasi: {site.procurementError}</div>}
      <div className="ops-metrics">
        {metricDefs.map(([key, label, Icon]) => <Metric key={key} value={site.summary?.[key]} label={label} Icon={Icon} />)}
      </div>
      <div className="ops-lanes">
        {Object.keys(laneLabels).map((name) => <Lane key={name} name={name} items={site.lanes?.[name] || []} />)}
      </div>
    </section>
  );
}

export default function OperationsControlTower({ date: initialDate }) {
  const [date, setDate] = useState(initialDate || new Date().toISOString().slice(0, 10));
  const [data, setData] = useState(mockControlTower);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      if (!hasOperationsBackend) {
        setData({ ...mockControlTower, date });
        return;
      }
      setData(await operationsApi.getControlTower(date, ""));
    } catch (err) {
      setError(err.message || "Gagal mengambil data Pusat Operasional");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [date]);

  const sites = useMemo(() => {
    const rows = data?.sites || [];
    return [...rows].sort((a, b) => siteCode(a) === "MAJA" ? -1 : siteCode(b) === "MAJA" ? 1 : 0);
  }, [data]);

  const build = data?.buildInfo || {};
  const commit = String(build.commit || "");
  const buildLabel = build.branch || commit || build.service
    ? `${build.branch || "branch ?"} · ${commit ? commit.slice(0, 10) : "commit ?"}${build.service ? ` · ${build.service}` : ""}`
    : "build Railway belum melaporkan branch/commit";

  return (
    <div className="ops-shell">
      <div className="ops-heading">
        <div>
          <span className="ops-kicker">YAYASAN CONTROL TOWER — LIVE DOMAIN STATE</span>
          <h2>MAJA & CEMPLANG — Status Terpisah</h2>
          <p>PO dibaca dari mesin Pengingat PO/lead time yang sama. Penerimaan dibaca dari tabel yang sama dengan GPTS dan halaman Penerimaan. SENT tidak dianggap terlambat hanya karena tanggal distribusinya lewat.</p>
          <p className="ops-muted"><strong>Build:</strong> {buildLabel}</p>
        </div>
        <div className="ops-toolbar">
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <button type="button" onClick={load} disabled={loading}><RefreshCw size={16} /> {loading ? "Memuat" : "Refresh"}</button>
        </div>
      </div>

      {!hasOperationsBackend && <div className="ops-notice">Mode struktur/mock aktif.</div>}
      {error && <div className="ops-error">{error}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(520px,1fr))", gap: 18 }}>
        {sites.map((site) => <SitePanel key={site.siteId} site={site} date={date} />)}
      </div>
    </div>
  );
}
