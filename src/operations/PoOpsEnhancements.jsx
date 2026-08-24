import React, { useMemo, useState } from "react";
import { CalendarDays, RefreshCw, XCircle } from "lucide-react";
import { operationsApi } from "./apiClient";

const today = () => new Date().toISOString().slice(0, 10);
const qty = (v) => Number(v || 0).toLocaleString("id-ID", { maximumFractionDigits: 4 });
const WHATSAPP_PO_STATUSES = new Set(["FINALIZED", "SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED"]);
const REVISABLE_PO_STATUSES = new Set(["FINALIZED", "SENT", "ACKNOWLEDGED"]);
const CANCELLABLE_PO_STATUSES = new Set(["DRAFT", "FINALIZED", "SENT", "ACKNOWLEDGED"]);

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

function activePoRows(rows) {
  return (rows || []).filter((po) => !["CANCELLED", "SUPERSEDED", "HISTORICAL_IMPORTED"].includes(String(po?.status || "").toUpperCase()));
}

function reminderDistributionDates(rows) {
  const dates = new Set();
  (rows || []).forEach((row) => {
    [row?.distribution_date, ...(row?.distribution_dates || [])].filter(Boolean).forEach((value) => dates.add(String(value).slice(0, 10)));
    (row?.requirement_details || []).forEach((detail) => {
      if (detail?.distribution_date) dates.add(String(detail.distribution_date).slice(0, 10));
    });
  });
  return Array.from(dates).filter((value) => /^\d{4}-\d{2}-\d{2}$/.test(value)).sort();
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  area.remove();
}

function localPoMessage(po) {
  const lines = [
    `🛒 *PO SPPG ${po.site || "-"}*`,
    `👤 *Vendor:* ${po.vendor_code || "-"}`,
    `📅 *Distribusi:* ${coverageLabel(po)}`,
    `🍳 *Masak:* ${po.cooking_date || "-"}`,
    `🧾 *No. PO:* ${po.po_code || "-"}`,
    "",
    "📦 *DAFTAR PESANAN*",
    "",
  ];
  (po.items || []).forEach((item, index) => lines.push(`   ${index + 1}. *${item.item_name || "Barang"}* : ${qty(item.po_qty)} ${item.unit || ""}`.trimEnd()));
  lines.push("", "Mohon dibantu disiapkan sesuai daftar di atas ya Pak. 🙏", "Mohon konfirmasi jika ada barang yang kosong atau harganya berubah.", "Terima kasih.");
  return lines.join("\n");
}

export default function PoOpsEnhancements({
  mode,
  activeSite,
  reminders = [],
  setReminders,
  setRemindersPulled,
  setPurchaseOrders,
  setPoListLoaded,
  setDeliveryAlerts,
}) {
  const [progress, setProgress] = useState({ active: false, percent: 0, label: "Siap" });
  const [localError, setLocalError] = useState("");
  const [calendarMonth, setCalendarMonth] = useState(today().slice(0, 7));
  const [calendarPos, setCalendarPos] = useState([]);
  const [calendarPo, setCalendarPo] = useState(null);
  const [calendarAction, setCalendarAction] = useState("");

  const refreshActualPo = async () => {
    const bounds = monthBounds(calendarMonth || today().slice(0, 7));
    const result = await operationsApi.getPurchaseOrders({
      site: activeSite,
      limit: 500,
      fromDate: bounds.first,
      toDate: bounds.last,
    });
    setPurchaseOrders?.(activePoRows(result?.items || []));
    setPoListLoaded?.(true);
  };

  const refreshDelivery = async () => {
    const result = await operationsApi.getPoDeliveryAlerts({ site: activeSite, date: today(), minimumHour: 17 });
    setDeliveryAlerts?.(result?.items || []);
  };

  const refreshReminderFromCalculator = async (progressLabel = "Menyinkronkan revisi Kalkulator") => {
    let sourceRows = reminders;
    if (!sourceRows.length) {
      const discovered = await operationsApi.getPoReminders({ site: activeSite, date: today(), horizonDays: 2 });
      sourceRows = discovered?.items || [];
    }
    const distributionDates = reminderDistributionDates(sourceRows);
    if (distributionDates.length) {
      setProgress({ active: true, percent: 45, label: `${progressLabel} · ${distributionDates.length} tanggal` });
      await Promise.all(distributionDates.map((distributionDate) => operationsApi.syncCalculatorPlanning({
        site: activeSite,
        distributionDate,
        deactivateMissing: true,
      })));
    }
    return operationsApi.getPoReminders({ site: activeSite, date: today(), horizonDays: 2, refresh: true });
  };

  const syncReminderStages = async () => {
    setLocalError("");
    setProgress({ active: true, percent: 15, label: `Menarik pengingat lengkap ${activeSite}` });
    try {
      // Refresh every Calculator distribution date represented by the current
      // queue before recalculating it. This replaces stale PostgreSQL planning
      // snapshots when an ingredient was edited or removed in the Calculator.
      const result = await refreshReminderFromCalculator();
      const rows = (result?.items || []).filter((row) => !row?.site || String(row.site).toUpperCase() === String(activeSite).toUpperCase());
      setReminders?.(rows);
      setRemindersPulled?.(true);
      setProgress({ active: false, percent: 100, label: "Pengingat lengkap tersinkron" });
    } catch (err) {
      setProgress({ active: false, percent: 100, label: "Sinkron pengingat gagal" });
      setLocalError(`Data sebelumnya tetap ditampilkan. ${err.message || "Gagal menarik pengingat"}`);
    }
  };

  const syncAllBlocks = async () => {
    setLocalError("");
    const failures = [];
    setProgress({ active: true, percent: 5, label: `Memulai sinkron ${activeSite}` });
    try { setProgress({ active: true, percent: 15, label: "1/4 · PO Aktual" }); await refreshActualPo(); }
    catch (err) { failures.push(`PO Aktual: ${err.message || "gagal"}`); }
    try { setProgress({ active: true, percent: 35, label: "2/4 · Barang belum datang" }); await refreshDelivery(); }
    catch (err) { failures.push(`Barang belum datang: ${err.message || "gagal"}`); }
    try {
      setProgress({ active: true, percent: 60, label: "3/4 · Pengingat lengkap" });
      const reminderResult = await refreshReminderFromCalculator("3/4 · Sinkron planning Kalkulator");
      const rows = (reminderResult?.items || []).filter((row) => !row?.site || String(row.site).toUpperCase() === String(activeSite).toUpperCase());
      setReminders?.(rows);
      setRemindersPulled?.(true);
    } catch (err) { failures.push(`Pengingat (data sebelumnya dipertahankan): ${err.message || "gagal"}`); }
    try { setProgress({ active: true, percent: 85, label: "4/4 · Kalender PO" }); await refreshCalendar(); }
    catch (err) { failures.push(`Kalender PO: ${err.message || "gagal"}`); }
    setProgress({ active: false, percent: 100, label: failures.length ? "Sinkron selesai sebagian" : "Semua blok tersinkron" });
    if (failures.length) setLocalError(failures.join("; "));
  };

  const refreshCalendar = async () => {
    const bounds = monthBounds(calendarMonth);
    const result = await operationsApi.getPurchaseOrders({ site: activeSite, includeArchived: true, fromDate: bounds.first, toDate: bounds.last, limit: 500 });
    const rows = result?.items || [];
    setCalendarPos(rows);
    setPurchaseOrders?.(activePoRows(rows));
    setPoListLoaded?.(true);
  };

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
    } catch (err) { setLocalError(err.message || "Gagal membuka PO dari kalender"); }
  };

  const refreshCurrentCalendarPo = async (poId = calendarPo?.id) => {
    await refreshCalendar();
    if (!poId) return;
    try { setCalendarPo(await operationsApi.getPurchaseOrder(poId)); }
    catch { setCalendarPo(null); }
  };

  const copyCalendarPo = async () => {
    if (!calendarPo) return;
    setCalendarAction("copy"); setLocalError("");
    try {
      let text = localPoMessage(calendarPo);
      try {
        const preview = await operationsApi.getPoWhatsAppPreview({ purchaseOrderId: calendarPo.id });
        text = preview?.message || preview?.text || preview?.whatsapp_message || preview?.whatsappText || text;
      } catch {}
      await copyText(text);
    } catch (err) { setLocalError(err.message || "Gagal copy PO"); }
    finally { setCalendarAction(""); }
  };

  const openCalendarWhatsApp = async () => {
    if (!calendarPo) return;
    setCalendarAction("wa"); setLocalError("");
    try {
      const preview = await operationsApi.getPoWhatsAppPreview({ purchaseOrderId: calendarPo.id });
      const text = preview?.message || preview?.text || preview?.whatsapp_message || preview?.whatsappText || localPoMessage(calendarPo);
      const direct = preview?.whatsapp_url || preview?.whatsappUrl || preview?.url;
      if (direct) { window.open(direct, "_blank", "noopener,noreferrer"); return; }
      const phone = String(preview?.whatsapp_phone || preview?.whatsappPhone || preview?.phone || "").replace(/[^0-9]/g, "").replace(/^0/, "62");
      if (!phone) throw new Error("Nomor WhatsApp vendor belum tersimpan.");
      window.open(`https://wa.me/${phone}?text=${encodeURIComponent(text)}`, "_blank", "noopener,noreferrer");
    } catch (err) { setLocalError(err.message || "Gagal membuka WhatsApp vendor"); }
    finally { setCalendarAction(""); }
  };

  const markCalendarSent = async () => {
    if (!calendarPo || !window.confirm(`Tandai ${calendarPo.po_code} sudah dikirim ke vendor?`)) return;
    setCalendarAction("sent"); setLocalError("");
    try { await operationsApi.markPurchaseOrderSent(calendarPo.id); await refreshCurrentCalendarPo(calendarPo.id); }
    catch (err) { setLocalError(err.message || "Gagal menandai PO terkirim"); }
    finally { setCalendarAction(""); }
  };

  const reviseCalendarPo = async () => {
    if (!calendarPo || !window.confirm(`Buat revisi baru dari ${calendarPo.po_code}?`)) return;
    setCalendarAction("revise"); setLocalError("");
    try {
      const result = await operationsApi.revisePurchaseOrder(calendarPo.id);
      await refreshCalendar();
      const nextId = result?.id || result?.purchase_order_id || result?.purchaseOrderId;
      if (nextId) setCalendarPo(await operationsApi.getPurchaseOrder(nextId));
      else await refreshCurrentCalendarPo(calendarPo.id);
    } catch (err) { setLocalError(err.message || "Gagal membuat revisi PO"); }
    finally { setCalendarAction(""); }
  };

  const cancelCalendarPo = async () => {
    if (!calendarPo || !window.confirm(`Batalkan ${calendarPo.po_code}?`)) return;
    setCalendarAction("cancel"); setLocalError("");
    try { await operationsApi.cancelPurchaseOrder(calendarPo.id); setCalendarPo(null); await refreshCalendar(); }
    catch (err) { setLocalError(err.message || "Gagal membatalkan PO"); }
    finally { setCalendarAction(""); }
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
          <button className="ops-button-primary" type="button" onClick={syncReminderStages} disabled={progress.active}><RefreshCw size={14} /> Tarik / Sinkron Pengingat</button>
          <button type="button" onClick={refreshDelivery} disabled={progress.active}><RefreshCw size={14} /> Refresh Barang Datang</button>
        </div>
        {progressUi}
        {localError && <div className="ops-error">{localError}</div>}
      </div>
    );
  }

  const calendarStatus = String(calendarPo?.status || "").toUpperCase();

  return (
    <div data-po-actual-calendar="v25" className="ops-draft-group">
      <div className="ops-draft-group-head">
        <div>
          <strong>Kalender PO Aktual</strong>
          <span>PO aktual pada tanggal distribusi. Klik PO untuk melihat detail dan menjalankan aksi yang sama seperti mode list.</span>
        </div>
        <div className="ops-row-actions" data-po-actual-refresh="v25">
          <button type="button" onClick={refreshActualPo} disabled={progress.active}><RefreshCw size={14} /> Refresh PO Aktual</button>
          <button className="ops-button-primary" type="button" onClick={syncAllBlocks} disabled={progress.active}><RefreshCw size={14} /> Sinkron Semua Blok</button>
        </div>
      </div>

      {progressUi}
      {localError && <div className="ops-error">{localError}</div>}

      <div className="ops-row-actions" style={{ marginTop: 10 }}>
        <label>Bulan <input type="month" value={calendarMonth} onChange={(e) => setCalendarMonth(e.target.value)} /></label>
        <button type="button" onClick={refreshCalendar}><CalendarDays size={14} /> Refresh Kalender</button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(7,minmax(0,1fr))", gap: 6, marginTop: 10 }}>
        {["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"].map((day) => <strong key={day} className="ops-muted" style={{ textAlign: "center" }}>{day}</strong>)}
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
          <div className="ops-module" style={{ width: "min(900px,96vw)", maxHeight: "88vh", overflow: "auto" }} onClick={(e) => e.stopPropagation()}>
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
            <div className="ops-row-actions" style={{ marginTop: 10, flexWrap: "wrap" }}>
              <button type="button" onClick={copyCalendarPo} disabled={Boolean(calendarAction)}>Copy PO</button>
              {WHATSAPP_PO_STATUSES.has(calendarStatus) && <button type="button" onClick={openCalendarWhatsApp} disabled={Boolean(calendarAction)}>WhatsApp Vendor</button>}
              {REVISABLE_PO_STATUSES.has(calendarStatus) && <button type="button" onClick={reviseCalendarPo} disabled={Boolean(calendarAction)}>Buat Revisi</button>}
              {calendarStatus === "FINALIZED" && <button type="button" onClick={markCalendarSent} disabled={Boolean(calendarAction)}>Tandai Terkirim</button>}
              {CANCELLABLE_PO_STATUSES.has(calendarStatus) && <button type="button" onClick={cancelCalendarPo} disabled={Boolean(calendarAction)}>Batalkan</button>}
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
                  <div className="ops-notice" key={`${day.distribution_date}-${index}`}>Masak <strong>{String(day.cooking_date || calendarPo.cooking_date || "-")}</strong> → distribusi <strong>{String(day.distribution_date || "-")}</strong></div>
                ))}
              </div>
            </>}
          </div>
        </div>
      )}
    </div>
  );
}
