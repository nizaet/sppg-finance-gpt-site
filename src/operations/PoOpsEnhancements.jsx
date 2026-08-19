import React, { useEffect, useMemo, useState } from "react";
import { CalendarDays, RefreshCw, XCircle } from "lucide-react";
import { operationsApi } from "./apiClient";

const today = () => new Date().toISOString().slice(0, 10);
const qty = (v) => Number(v || 0).toLocaleString("id-ID", { maximumFractionDigits: 4 });

function shiftDate(value, days) {
  const result = new Date(`${value}T12:00:00`);
  result.setDate(result.getDate() + days);
  return result.toISOString().slice(0, 10);
}

function compactTimestamp(value) {
  if (!value) return "";
  return String(value).replace("T", " ").replace(/\.\d+Z$/, " WIB");
}

function coverageDatesFor(po) {
  const dates = Array.isArray(po?.coverage_dates) ? po.coverage_dates.filter(Boolean) : [];
  if (dates.length) return dates.map(String).sort();
  return po?.distribution_date ? [String(po.distribution_date)] : [];
}

function coverageLabel(po) {
  const dates = coverageDatesFor(po);
  if (!dates.length) return "-";
  if (dates.length === 1) return dates[0];
  return `${dates[0]} s.d. ${dates[dates.length - 1]}`;
}

function reminderKey(row) {
  return row?.reminder_key || [row?.site, row?.vendor_code, row?.po_date, row?.procurement_bucket, ...(row?.distribution_dates || [])].join("|");
}

function mergeReminderRows(baseRows, extraRows) {
  const merged = new Map();
  [...(baseRows || []), ...(extraRows || [])].forEach((row) => merged.set(reminderKey(row), row));
  return Array.from(merged.values());
}

function monthBounds(value) {
  const [year, month] = String(value || today().slice(0, 7)).split("-").map(Number);
  const lastDay = new Date(year, month, 0).getDate();
  const mm = String(month).padStart(2, "0");
  return {
    year,
    month,
    lastDay,
    first: `${year}-${mm}-01`,
    last: `${year}-${mm}-${String(lastDay).padStart(2, "0")}`,
  };
}

export default function PoOpsEnhancements({
  mode,
  activeSite,
  setReminders,
  setPurchaseOrders,
  setDeliveryAlerts,
}) {
  const [progress, setProgress] = useState({ active: false, percent: 0, label: "Siap" });
  const [localError, setLocalError] = useState("");
  const [calendarMonth, setCalendarMonth] = useState(today().slice(0, 7));
  const [calendarPos, setCalendarPos] = useState([]);
  const [calendarPo, setCalendarPo] = useState(null);

  const refreshActualPo = async () => {
    const result = await operationsApi.getPurchaseOrders({
      site: activeSite,
      limit: 80,
      fromDate: shiftDate(today(), -1),
      toDate: shiftDate(today(), 7),
    });
    setPurchaseOrders?.(result?.items || []);
  };

  const refreshDelivery = async () => {
    const result = await operationsApi.getPoDeliveryAlerts({ site: activeSite, date: today(), minimumHour: 17 });
    setDeliveryAlerts?.(result?.items || []);
  };

  const syncReminderStages = async () => {
    setLocalError("");
    setProgress({ active: true, percent: 5, label: `Menyiapkan pengingat ${activeSite}` });
    let collected = [];
    const failures = [];
    const stages = [
      { date: today(), start: 15, end: 55, label: "Terlambat + hari ini" },
      { date: shiftDate(today(), 1), start: 65, end: 100, label: "Pengingat besok" },
    ];

    for (const stage of stages) {
      setProgress({ active: true, percent: stage.start, label: `Menarik ${stage.label}` });
      try {
        const result = await operationsApi.getPoReminders({ site: activeSite, date: stage.date, horizonDays: 1 });
        const rows = (result?.items || []).filter((row) => !row?.site || String(row.site).toUpperCase() === String(activeSite).toUpperCase());
        collected = mergeReminderRows(collected, rows);
        setReminders?.(collected);
      } catch (err) {
        failures.push(`${stage.label}: ${err.message || "gagal"}`);
      }
      setProgress({ active: true, percent: stage.end, label: `${stage.label} selesai` });
    }

    setProgress({ active: false, percent: 100, label: failures.length ? "Selesai sebagian" : "Sinkron selesai" });
    if (failures.length) setLocalError(failures.join("; "));
  };

  const syncAllBlocks = async () => {
    setLocalError("");
    const failures = [];
    setProgress({ active: true, percent: 5, label: `Memulai sinkron ${activeSite}` });

    try {
      setProgress({ active: true, percent: 15, label: "1/4 · PO Aktual" });
      await refreshActualPo();
    } catch (err) {
      failures.push(`PO Aktual: ${err.message || "gagal"}`);
    }

    try {
      setProgress({ active: true, percent: 35, label: "2/4 · Barang belum datang" });
      await refreshDelivery();
    } catch (err) {
      failures.push(`Barang belum datang: ${err.message || "gagal"}`);
    }

    let collected = [];
    try {
      setProgress({ active: true, percent: 55, label: "3/4 · Terlambat + hari ini" });
      const current = await operationsApi.getPoReminders({ site: activeSite, date: today(), horizonDays: 1 });
      collected = mergeReminderRows(collected, current?.items || []);
      setReminders?.(collected);
    } catch (err) {
      failures.push(`Pengingat hari ini: ${err.message || "gagal"}`);
    }

    try {
      setProgress({ active: true, percent: 80, label: "4/4 · Pengingat besok" });
      const tomorrow = await operationsApi.getPoReminders({ site: activeSite, date: shiftDate(today(), 1), horizonDays: 1 });
      collected = mergeReminderRows(collected, tomorrow?.items || []);
      setReminders?.(collected);
    } catch (err) {
      failures.push(`Pengingat besok: ${err.message || "gagal"}`);
    }

    setProgress({ active: false, percent: 100, label: failures.length ? "Sinkron selesai sebagian" : "Semua blok tersinkron" });
    if (failures.length) setLocalError(failures.join("; "));
  };

  const refreshCalendar = async () => {
    const bounds = monthBounds(calendarMonth);
    const result = await operationsApi.getPurchaseOrders({
      site: activeSite,
      includeArchived: true,
      fromDate: bounds.first,
      toDate: bounds.last,
      limit: 500,
    });
    setCalendarPos(result?.items || []);
  };

  useEffect(() => {
    if (mode !== "calendar") return undefined;
    let cancelled = false;
    const bounds = monthBounds(calendarMonth);
    operationsApi.getPurchaseOrders({
      site: activeSite,
      includeArchived: true,
      fromDate: bounds.first,
      toDate: bounds.last,
      limit: 500,
    }).then((result) => {
      if (!cancelled) setCalendarPos(result?.items || []);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [mode, activeSite, calendarMonth]);

  const calendarCells = useMemo(() => {
    const bounds = monthBounds(calendarMonth);
    const firstWeekDay = (new Date(bounds.year, bounds.month - 1, 1).getDay() + 6) % 7;
    const cells = Array(firstWeekDay).fill(null);
    for (let day = 1; day <= bounds.lastDay; day += 1) cells.push(String(day).padStart(2, "0"));
    while (cells.length % 7) cells.push(null);
    return cells;
  }, [calendarMonth]);

  const poByDate = useMemo(() => {
    const mapped = new Map();
    calendarPos.forEach((po) => coverageDatesFor(po).forEach((dateValue) => {
      const key = String(dateValue);
      if (!mapped.has(key)) mapped.set(key, []);
      mapped.get(key).push(po);
    }));
    return mapped;
  }, [calendarPos]);

  const openCalendarPo = async (po) => {
    try {
      const detail = await operationsApi.getPurchaseOrder(po.id);
      setCalendarPo({ ...po, ...detail });
    } catch (err) {
      setLocalError(err.message || "Gagal membuka PO dari kalender");
    }
  };

  const progressUi = progress.percent > 0 ? (
    <div data-po-sync-progress="v25" style={{ marginTop: 8 }}>
      <div className="ops-muted">{progress.label} · {progress.percent}%</div>
      <div style={{ height: 10, borderRadius: 999, background: "rgba(127,127,127,.22)", overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${progress.percent}%`, background: "currentColor", transition: "width .25s ease" }} />
      </div>
    </div>
  ) : null;

  if (mode === "reminder") {
    return (
      <div data-po-staged-sync="v25" style={{ marginTop: 10 }}>
        <div className="ops-row-actions">
          <button className="ops-button-primary" type="button" onClick={syncReminderStages} disabled={progress.active}>
            <RefreshCw size={14} /> Tarik / Sinkron Pengingat
          </button>
          <button type="button" onClick={refreshDelivery} disabled={progress.active}>
            <RefreshCw size={14} /> Refresh Barang Datang
          </button>
        </div>
        {progressUi}
        {localError && <div className="ops-error">Sinkron selesai sebagian: {localError}</div>}
      </div>
    );
  }

  return (
    <div data-po-actual-calendar="v25" className="ops-draft-group">
      <div className="ops-draft-group-head">
        <div>
          <strong>Kalender PO Aktual</strong>
          <span>PO aktual pada tanggal distribusi. Klik PO untuk melihat dibuat, pesan/kirim, masak, dan distribusi untuk kapan.</span>
        </div>
        <div className="ops-row-actions" data-po-actual-refresh="v25">
          <button type="button" onClick={refreshActualPo} disabled={progress.active}><RefreshCw size={14} /> Refresh PO Aktual</button>
          <button className="ops-button-primary" type="button" onClick={syncAllBlocks} disabled={progress.active}><RefreshCw size={14} /> Sinkron Semua Blok</button>
        </div>
      </div>

      {progressUi}
      {localError && <div className="ops-error">Sinkron selesai sebagian: {localError}</div>}

      <div className="ops-row-actions" style={{ marginTop: 10 }}>
        <label>Bulan <input type="month" value={calendarMonth} onChange={(e) => setCalendarMonth(e.target.value)} /></label>
        <button type="button" onClick={refreshCalendar}><CalendarDays size={14} /> Refresh Kalender</button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(7,minmax(0,1fr))", gap: 6, marginTop: 10 }}>
        {["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"].map((day) => (
          <strong key={day} className="ops-muted" style={{ textAlign: "center" }}>{day}</strong>
        ))}
        {calendarCells.map((day, index) => {
          const dateValue = day ? `${calendarMonth}-${day}` : "";
          const dayPos = dateValue ? (poByDate.get(dateValue) || []) : [];
          return (
            <div key={`${calendarMonth}-${index}`} style={{ minHeight: 86, border: "1px solid rgba(127,127,127,.25)", borderRadius: 8, padding: 6, opacity: day ? 1 : 0.25 }}>
              {day && <>
                <strong>{Number(day)}</strong>
                {dayPos.map((po) => (
                  <button key={`${po.id}-${dateValue}`} type="button" onClick={() => openCalendarPo(po)} style={{ display: "block", width: "100%", marginTop: 5, textAlign: "left", whiteSpace: "normal" }}>
                    <strong>{po.vendor_code}</strong>
                    <div className="ops-muted">{po.po_code}</div>
                    <div className="ops-muted">PO dibuat {compactTimestamp(po.created_at).slice(0, 10)}</div>
                  </button>
                ))}
              </>}
            </div>
          );
        })}
      </div>

      {calendarPo && (
        <div data-po-calendar-popup="v25" style={{ position: "fixed", inset: 0, zIndex: 10000, background: "rgba(0,0,0,.55)", display: "flex", alignItems: "center", justifyContent: "center", padding: 18 }} onClick={() => setCalendarPo(null)}>
          <div className="ops-module" style={{ width: "min(760px,96vw)", maxHeight: "88vh", overflow: "auto" }} onClick={(e) => e.stopPropagation()}>
            <div className="ops-draft-group-head">
              <div><strong>{calendarPo.po_code} · Rev {calendarPo.revision_no}</strong><span>{calendarPo.vendor_code} · {calendarPo.status}</span></div>
              <button type="button" onClick={() => setCalendarPo(null)}><XCircle size={14} /> Tutup</button>
            </div>
            <div className="ops-summary-strip">
              <span>PO dibuat <strong>{compactTimestamp(calendarPo.created_at) || "-"}</strong></span>
              <span>Jadwal pesan/kirim <strong>{calendarPo.scheduled_order_date || "Lead time belum diatur"}</strong></span>
              <span>Masak <strong>{calendarPo.cooking_date || "-"}</strong></span>
              <span>Distribusi <strong>{coverageLabel(calendarPo)}</strong></span>
              <span>Status <strong>{calendarPo.status}</strong></span>
            </div>
            <h4>Pesanan</h4>
            <div className="ops-table-wrap">
              <table className="ops-table"><thead><tr><th>Barang</th><th>Qty</th><th>Unit</th></tr></thead><tbody>
                {(calendarPo.items || []).map((item, index) => <tr key={item.id || index}><td>{item.item_name}</td><td>{qty(item.po_qty)}</td><td>{item.unit || "-"}</td></tr>)}
              </tbody></table>
            </div>
            {(calendarPo.coverage || []).length > 0 && <>
              <h4>Masak untuk kapan</h4>
              <div className="ops-coverage-grid">
                {calendarPo.coverage.map((day, index) => (
                  <div className="ops-notice" key={`${day.distribution_date}-${index}`}>
                    Masak <strong>{String(day.cooking_date || calendarPo.cooking_date || "-")}</strong> → distribusi <strong>{String(day.distribution_date || "-")}</strong>
                  </div>
                ))}
              </div>
            </>}
          </div>
        </div>
      )}
    </div>
  );
}
