import React, { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CalendarDays, CheckCircle2, ClipboardList, PackageCheck, RefreshCw, WalletCards } from "lucide-react";
import { operationsApi, hasOperationsBackend } from "./apiClient";
import { mockControlTower } from "./mockControlTower";
import OperationsReviewQueue from "./OperationsReviewQueue.jsx";
import "./operations.css";

const metricDefs = [
  ["poDueToday", "PO Hari Ini", CalendarDays],
  ["poOverdue", "PO Terlambat", AlertTriangle],
  ["deliveriesExpected", "Kedatangan", PackageCheck],
  ["unresolvedRejects", "Reject Belum Selesai", ClipboardList],
  ["paymentsDue", "Pembayaran Jatuh Tempo", WalletCards],
  ["reviewQueue", "Perlu Review", CheckCircle2],
];

const laneLabels = {
  procurement: "PO & Supplier",
  receiving: "Penerimaan & Reject",
  payments: "Pembayaran Vendor",
  costing: "Actual Usage & Costing",
  accountant: "Akuntan",
  bgn: "Maker / Approval / BGN",
};

function Metric({ value, label, Icon }) {
  return (
    <div className="ops-metric">
      <Icon size={18} />
      <div>
        <strong>{Number(value || 0)}</strong>
        <span>{label}</span>
      </div>
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
              <div>
                <strong>{item.title || item.vendor || item.status || "Item"}</strong>
                {item.subtitle && <span>{item.subtitle}</span>}
              </div>
              <span className={`ops-status ops-status-${String(item.severity || item.status || "info").toLowerCase()}`}>
                {item.badge || item.status || "INFO"}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default function OperationsControlTower({ date: initialDate }) {
  const [date, setDate] = useState(initialDate || new Date().toISOString().slice(0, 10));
  const [data, setData] = useState(mockControlTower);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [schemaReady, setSchemaReady] = useState(null);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      if (!hasOperationsBackend) {
        setData({ ...mockControlTower, date });
        return;
      }
      const [tower, schema] = await Promise.all([
        operationsApi.getControlTower(date),
        operationsApi.getSchemaStatus().catch(() => null),
      ]);
      setData(tower);
      if (schema) setSchemaReady(Boolean(schema.schemaReady));
    } catch (err) {
      setError(err.message || "Gagal mengambil data Pusat Operasional");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [date]);

  const sites = useMemo(() => data?.sites || [], [data]);

  return (
    <div className="ops-shell">
      <div className="ops-heading">
        <div>
          <span className="ops-kicker">PUSAT OPERASIONAL</span>
          <h2>Control Tower Hari Ini</h2>
          <p>PO → penerimaan → pembayaran → costing → akuntan → BGN → settlement.</p>
        </div>
        <div className="ops-toolbar">
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <button type="button" onClick={load} disabled={loading}><RefreshCw size={16} /> {loading ? "Memuat" : "Refresh"}</button>
        </div>
      </div>

      {!hasOperationsBackend && (
        <div className="ops-notice">Mode struktur/mock aktif. Kalkulator Maja dan Cemplang tidak diubah. Data live akan aktif setelah SPPG Core API dikonfigurasi.</div>
      )}
      {schemaReady === false && <div className="ops-error">Database terhubung, tetapi schema SPPG Core belum lengkap.</div>}
      {schemaReady === true && <div className="ops-success">Backend live · PostgreSQL schema siap.</div>}
      {error && <div className="ops-error">{error}</div>}

      {sites.map((site) => (
        <section className="ops-site" key={site.siteId}>
          <div className="ops-site-title"><h3>{site.siteLabel}</h3><span>{date}</span></div>
          <div className="ops-metrics">
            {metricDefs.map(([key, label, Icon]) => <Metric key={key} value={site.summary?.[key]} label={label} Icon={Icon} />)}
          </div>
          <div className="ops-lanes">
            {Object.keys(laneLabels).map((name) => <Lane key={name} name={name} items={site.lanes?.[name] || []} />)}
          </div>
        </section>
      ))}

      <OperationsReviewQueue />
    </div>
  );
}
