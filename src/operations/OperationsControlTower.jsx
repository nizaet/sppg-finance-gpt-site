import React, { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CalendarDays, CheckCircle2, RefreshCw, WalletCards } from "lucide-react";
import { operationsApi, hasOperationsBackend } from "./apiClient";
import { mockControlTower } from "./mockControlTower";
import "./operations.css";

const metricDefs = [
  ["poDueToday", "PO Hari Ini", CalendarDays],
  ["poOverdue", "PO Terlambat", AlertTriangle],
  ["paymentsDue", "Pembayaran Jatuh Tempo", WalletCards],
  ["reviewQueue", "Perlu Review", CheckCircle2],
];

const laneLabels = {
  procurement: "PO Vendor",
  payments: "Invoice & Pembayaran Vendor",
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

export default function OperationsControlTower({ date: initialDate, fixedSite = "" }) {
  const [date, setDate] = useState(initialDate || new Date().toISOString().slice(0, 10));
  const [data, setData] = useState(mockControlTower);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      if (!hasOperationsBackend) {
        const mockSites = fixedSite
          ? (mockControlTower.sites || []).filter((x) => String(x.siteLabel || "").toUpperCase().includes(fixedSite))
          : mockControlTower.sites;
        setData({ ...mockControlTower, date, sites: mockSites });
        return;
      }
      const tower = await operationsApi.getControlTower(date, fixedSite);
      setData(tower);
    } catch (err) {
      setError(err.message || "Gagal mengambil data Pusat Operasional");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [date, fixedSite]);

  const sites = useMemo(() => data?.sites || [], [data]);
  const visibleLaneNames = fixedSite ? ["procurement", "payments"] : Object.keys(laneLabels);
  const visibleMetrics = fixedSite ? metricDefs.filter(([key]) => key !== "reviewQueue") : metricDefs;

  return (
    <div className="ops-shell">
      <div className="ops-heading">
        <div>
          <span className="ops-kicker">PUSAT OPERASIONAL</span>
          <h2>Control Tower Hari Ini{fixedSite ? ` · ${fixedSite}` : ""}</h2>
          <p>{fixedSite ? "Kalkulator → PO vendor → invoice/pembayaran untuk dapur ini." : "Kalkulator → PO vendor → invoice/pembayaran → akuntan → maker & approval BGN."}</p>
        </div>
        <div className="ops-toolbar">
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <button type="button" onClick={load} disabled={loading}>
            <RefreshCw size={16} /> {loading ? "Memuat" : "Refresh"}
          </button>
        </div>
      </div>

      {!hasOperationsBackend && (
        <div className="ops-notice">
          Mode struktur/mock aktif. Pusat Resep, Master Harga, dan Kalkulator Maja/Cemplang tidak diubah.
        </div>
      )}
      {error && <div className="ops-error">{error}</div>}

      {sites.map((site) => (
        <section className="ops-site" key={site.siteId}>
          <div className="ops-site-title"><h3>{site.siteLabel}</h3><span>{date}</span></div>
          <div className="ops-metrics">
            {visibleMetrics.map(([key, label, Icon]) => (
              <Metric key={key} value={site.summary?.[key]} label={label} Icon={Icon} />
            ))}
          </div>
          <div className="ops-lanes">
            {visibleLaneNames.map((name) => (
              <Lane key={name} name={name} items={site.lanes?.[name] || []} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
