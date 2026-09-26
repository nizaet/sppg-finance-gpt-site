import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle, ArrowLeft, ArrowRight, CalendarDays, Check, Clock3,
  PackageCheck, RefreshCw, ShoppingCart, Wallet, ClipboardList, ShieldCheck,
} from "lucide-react";
import { operationsApi, hasOperationsBackend } from "./apiClient";
import "./controlTowerDashboard.css";

const SITE_ORDER = ["MAJA", "CEMPLANG"];
const DATE_FMT = new Intl.DateTimeFormat("id-ID", { timeZone: "Asia/Jakarta", day: "numeric", month: "short" });
const WEEKDAY_FMT = new Intl.DateTimeFormat("id-ID", { timeZone: "Asia/Jakarta", weekday: "long" });

function dateKey(date = new Date()) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Jakarta", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(date).map(part => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}
function shiftDate(key, days) {
  const [year, month, day] = key.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day + days, 12));
  return date.toISOString().slice(0, 10);
}
function localDate(key) {
  const [year, month, day] = key.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day, 12));
}
function dateRangeLabel(from, through) {
  return `${DATE_FMT.format(localDate(from))} – ${DATE_FMT.format(localDate(through))}`;
}
function money(value) {
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(Number(value || 0));
}
function statusText(value) {
  const values = {
    SENT: "Terkirim", ACKNOWLEDGED: "Dikonfirmasi", PARTIAL_RECEIVED: "Diterima sebagian",
    RECEIVED: "Diterima", CLOSED: "Selesai", DRAFT: "Draft", FINALIZED: "Siap kirim",
    APPROVED: "Approved", REJECTED: "Ditolak", PENDING: "Menunggu approval", UNPAID: "Belum dibayar",
    CREATED: "Maker dibuat", PAID: "Dana masuk",
  };
  return values[String(value || "").toUpperCase()] || value || "Belum ada";
}
function poSummary(po) {
  const status = String(po.status || "").toUpperCase();
  if (status === "RECEIVED" || status === "CLOSED") return ["Diterima", "good"];
  if (status === "PARTIAL_RECEIVED") return ["Parsial · masih ada sisa", "warn"];
  if (status === "SENT" || status === "ACKNOWLEDGED") return ["Terkirim · menunggu barang", "wait"];
  if (status === "FINALIZED") return ["Siap dikirim", "wait"];
  return ["Draft · belum terkirim", "warn"];
}

function MetricCard({ icon: Icon, label, value, note, tone = "neutral" }) {
  return <div className={`ct-metric ct-metric-${tone}`}>
    <span className="ct-metric-icon"><Icon size={18} /></span>
    <div><span className="ct-metric-label">{label}</span><strong>{value}</strong><small>{note}</small></div>
  </div>;
}

function SiteDay({ site, day }) {
  const plan = day.planning || {};
  const procurement = day.procurement || {};
  const maker = day.maker || {};
  const accountant = day.accountant || {};
  const payments = day.payments || {};
  const planReady = plan.status === "READY";
  const attention = (procurement.notOrdered || 0) + (procurement.draft || 0) +
    (procurement.notArrived || 0) + (maker.notCreated || 0) +
    (maker.pendingApproval || 0) + (maker.rejected || 0) + (payments.due || 0);

  return <article className={`ct-site-day ct-site-${site.toLowerCase()}`}>
    <header className="ct-site-day-head">
      <span className={`ct-site-pill ct-site-pill-${site.toLowerCase()}`}>{site}</span>
      <span className={attention ? "ct-day-attention" : "ct-day-clear"}>
        {attention ? <><AlertCircle size={13} /> {attention} status untuk dicek</> : <><Check size={13} /> Aman</>}
      </span>
    </header>

    <div className="ct-stage-grid">
      <section className="ct-stage">
        <div className="ct-stage-title"><ClipboardList size={15} /><strong>Planning</strong></div>
        {planReady
          ? <><b>{plan.itemCount} bahan</b><small>{plan.items?.join(", ")}{plan.moreItems ? ` +${plan.moreItems}` : ""}</small></>
          : <span className="ct-state ct-state-muted">Belum ada planning aktif</span>}
      </section>

      <section className="ct-stage">
        <div className="ct-stage-title"><ShoppingCart size={15} /><strong>PO & Barang</strong></div>
        <div className="ct-chip-row">
          {procurement.notOrdered > 0 && <span className="ct-state ct-state-wait">Planning tanpa PO · {procurement.notOrdered} hari</span>}
          {procurement.draft > 0 && <span className="ct-state ct-state-warn">Draft · {procurement.draft}</span>}
          {procurement.sent > 0 && <span className="ct-state ct-state-wait">Menunggu barang · {procurement.sent}</span>}
          {procurement.partial > 0 && <span className="ct-state ct-state-warn">Parsial · {procurement.partial}</span>}
          {procurement.received > 0 && <span className="ct-state ct-state-good">Diterima · {procurement.received}</span>}
          {!procurement.poCount && !procurement.notOrdered && <span className="ct-state ct-state-muted">Belum ada PO terkait</span>}
        </div>
        {!!procurement.purchaseOrders?.length && <ul className="ct-detail-list">
          {procurement.purchaseOrders.map(po => {
            const [label, tone] = poSummary(po);
            return <li key={po.id}>
              <span><b>{po.vendor || "Vendor"}</b>{po.code && <small>{po.code}</small>}</span>
              <span className={`ct-po-state ct-po-${tone}`}>{label}</span>
            </li>;
          })}
        </ul>}
      </section>

      <section className="ct-stage">
        <div className="ct-stage-title"><ShieldCheck size={15} /><strong>Maker & Approval</strong></div>
        {maker.count > 0 ? <>
          <div className="ct-chip-row">
            {maker.notCreated > 0 && <span className="ct-state ct-state-alert">Belum dibuat · {maker.notCreated}</span>}
            {maker.pendingApproval > 0 && <span className="ct-state ct-state-warn">Pending · {maker.pendingApproval}</span>}
            {maker.approved > 0 && <span className="ct-state ct-state-wait">Approved · {maker.approved}</span>}
            {maker.paid > 0 && <span className="ct-state ct-state-good">Dana masuk · {maker.paid}</span>}
            {maker.rejected > 0 && <span className="ct-state ct-state-alert">Ditolak · {maker.rejected}</span>}
          </div>
          <ul className="ct-detail-list">
            {maker.items.map(item => <li key={item.id}>
              <span><b>{item.reference}</b><small>{money(item.amount)}</small></span>
              <span className={item.status === "PAID" ? "ct-po-state ct-po-good" : "ct-po-state ct-po-warn"}>{statusText(item.status)}</span>
            </li>)}
          </ul>
        </> : planReady
          ? <span className="ct-state ct-state-muted">Belum ada Maker untuk tanggal ini</span>
          : <span className="ct-state ct-state-muted">Tidak ada Maker terkait</span>}
        {accountant.submissions?.length > 0 && <small className="ct-submission-note">
          Akuntan: {accountant.submissions.map(item => `${item.code || "Submission"} · ${statusText(item.status)}${item.invoiceNumber ? ` · Invoice ${item.invoiceNumber}` : ""}`).join(" / ")}
        </small>}
      </section>

      <section className="ct-stage">
        <div className="ct-stage-title"><Wallet size={15} /><strong>Tagihan Vendor</strong></div>
        {payments.items?.length ? <ul className="ct-detail-list">
          {payments.items.map(item => <li key={item.id}>
            <span><b>{item.vendor} · {item.invoiceNumber || "Invoice"}</b><small>{money(item.amount)} · jatuh tempo {item.dueDate}</small></span>
            <span className={item.overdue ? "ct-po-state ct-po-warn" : "ct-po-state ct-po-wait"}>{item.overdue ? "Terlambat" : statusText(item.status)}</span>
          </li>)}
        </ul> : <span className="ct-state ct-state-muted">Tidak ada jatuh tempo pada hari ini</span>}
      </section>
    </div>
  </article>;
}

function DayCard({ day, sites }) {
  const date = localDate(day.date);
  const weekday = WEEKDAY_FMT.format(date);
  const current = day.date === dateKey(new Date());
  return <section className={`ct-day-card ${current ? "ct-day-today" : ""}`}>
    <header className="ct-day-heading">
      <div><span className="ct-weekday">{weekday}{current && <i>HARI INI</i>}</span><h3>{DATE_FMT.format(date)}</h3></div>
      <span className="ct-date-iso">{day.date}</span>
    </header>
    <div className="ct-day-sites">
      {sites.map(site => <SiteDay key={site.dbSite} site={site.dbSite} day={day.bySite[site.dbSite]} />)}
    </div>
  </section>;
}

export default function OperationsControlTower() {
  const [fromDate, setFromDate] = useState(() => dateKey(new Date()));
  const [siteFilter, setSiteFilter] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError(""); setData(null);
    try {
      if (!hasOperationsBackend) {
        setData(null);
        setError("Data Control Tower tidak tersedia. Hubungkan backend operasional untuk melihat laporan live.");
        return;
      }
      setData(await operationsApi.getControlTowerWeek(fromDate, siteFilter));
    } catch (err) {
      setError(err.message || "Gagal memuat review mingguan.");
    } finally { setLoading(false); }
  }, [fromDate, siteFilter]);

  useEffect(() => { load(); }, [load]);

  const displayedSites = useMemo(() => {
    const rows = data?.sites || [];
    return [...rows].sort((a, b) => SITE_ORDER.indexOf(a.dbSite) - SITE_ORDER.indexOf(b.dbSite));
  }, [data]);

  const dayRows = useMemo(() => {
    const byDate = new Map();
    for (const site of displayedSites) {
      for (const day of site.days || []) {
        if (!byDate.has(day.date)) byDate.set(day.date, { date: day.date, bySite: {} });
        byDate.get(day.date).bySite[site.dbSite] = day;
      }
    }
    return [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
  }, [displayedSites]);

  const totals = useMemo(() => {
    const result = { plans: 0, notOrdered: 0, waiting: 0, makers: 0, makerReview: 0, payments: 0, reviews: 0 };
    for (const site of displayedSites) {
      result.reviews += site.days?.[0]?.reviewCount || 0;
      for (const day of site.days || []) {
        if (day.planning?.status === "READY") result.plans++;
        result.notOrdered += day.procurement?.notOrdered || 0;
        result.waiting += day.procurement?.notArrived || 0;
        result.makers += day.maker?.count || 0;
        result.makerReview += (day.maker?.pendingApproval || 0) + (day.maker?.notCreated || 0) + (day.maker?.rejected || 0);
        result.payments += day.payments?.due || 0;
      }
    }
    return result;
  }, [displayedSites]);

  const throughDate = shiftDate(fromDate, 6);
  const build = data?.buildInfo || {};
  const buildText = build.commit ? `Diperbarui dari ${build.branch || "produksi"} · ${build.commit.slice(0, 8)}` : "Data operasional live";
  const shiftWeek = amount => setFromDate(value => shiftDate(value, amount * 7));

  return <main className="ct-dashboard">
    <header className="ct-header">
      <div>
        <span className="ct-eyebrow">REVIEW OPERASIONAL MINGGUAN</span>
        <h1>Control Tower</h1>
        <p>Planning, PO dan kedatangan barang, Maker, approval, serta tagihan vendor dalam satu tampilan.</p>
      </div>
      <div className="ct-toolbar">
        <div className="ct-site-filter" aria-label="Filter dapur">
          {[["", "Gabungan"], ["MAJA", "MAJA"], ["CEMPLANG", "Cemplang"]].map(([value, label]) =>
            <button type="button" key={value || "ALL"} className={siteFilter === value ? "active" : ""} onClick={() => setSiteFilter(value)}>{label}</button>
          )}
        </div>
        <div className="ct-date-controls">
          <button type="button" className="ct-icon-button" onClick={() => shiftWeek(-1)} aria-label="Minggu sebelumnya"><ArrowLeft size={17} /></button>
          <label><CalendarDays size={16} /><input type="date" value={fromDate} onChange={event => setFromDate(event.target.value)} /></label>
          <button type="button" className="ct-icon-button" onClick={() => shiftWeek(1)} aria-label="Minggu berikutnya"><ArrowRight size={17} /></button>
          <button type="button" className="ct-today-button" onClick={() => setFromDate(dateKey(new Date()))}>Hari ini</button>
          <button type="button" className="ct-refresh" onClick={load} disabled={loading}><RefreshCw size={15} className={loading ? "ct-spin" : ""} /> {loading ? "Memuat" : "Refresh"}</button>
        </div>
      </div>
    </header>

    <section className="ct-week-summary">
      <div className="ct-week-summary-title"><div><span className="ct-eyebrow">RENTANG REVIEW</span><h2>{dateRangeLabel(fromDate, throughDate)}</h2></div><span>{buildText}</span></div>
      <div className="ct-metrics">
        <MetricCard icon={ClipboardList} label="Hari dengan planning" value={data?.databaseReady ? totals.plans : "—"} note={`dari ${displayedSites.length * 7} hari dapur`} />
        <MetricCard icon={AlertCircle} label="Planning tanpa PO" value={data?.databaseReady ? totals.notOrdered : "—"} note="periksa sesuai lead time" tone="neutral" />
        <MetricCard icon={PackageCheck} label="PO menunggu barang" value={data?.databaseReady ? totals.waiting : "—"} note="terkirim atau diterima sebagian" tone={totals.waiting ? "warn" : "good"} />
        <MetricCard icon={ShieldCheck} label="Maker perlu dicek" value={data?.databaseReady ? totals.makerReview : "—"} note={`${totals.makers} Maker tercatat minggu ini`} tone={totals.makerReview ? "warn" : "neutral"} />
        <MetricCard icon={Wallet} label="Tagihan jatuh tempo" value={data?.databaseReady ? totals.payments : "—"} note="sesuai tanggal jatuh tempo" tone={totals.payments ? "alert" : "good"} />
        <MetricCard icon={Clock3} label="Antrian review" value={data?.databaseReady ? totals.reviews : "—"} note="item perlu konfirmasi" tone={totals.reviews ? "warn" : "good"} />
      </div>
    </section>

    {error && <div className="ct-error"><AlertCircle size={17} />{error}</div>}
    {data && !data.databaseReady && <div className="ct-error"><AlertCircle size={17} />Database operasional belum tersambung. Angka nol tidak ditampilkan sebagai data valid.</div>}
    {loading && !data && <div className="ct-loading"><RefreshCw size={18} className="ct-spin" /> Memuat data mingguan…</div>}

    <div className="ct-legend">
      <span><i className="ct-dot ct-dot-good" /> Sudah diterima</span>
      <span><i className="ct-dot ct-dot-wait" /> PO terkirim, barang belum lengkap</span>
      <span><i className="ct-dot ct-dot-warn" /> Draft, parsial, atau menunggu approval</span>
      <span><i className="ct-dot ct-dot-alert" /> Belum ada PO atau Maker</span>
    </div>

    <section className="ct-week-list">
      {data?.databaseReady && dayRows.map(day => <DayCard key={day.date} day={day} sites={displayedSites} />)}
      {data?.databaseReady && !dayRows.length && !loading && <div className="ct-empty">Belum ada data untuk rentang tanggal ini.</div>}
    </section>
    <footer className="ct-footer"><span>Belum ada PO belum tentu terlambat; cek tanggal pesan berdasarkan lead time. PO terkirim belum dihitung sebagai barang masuk.</span><span>Control Tower hanya membaca data operasional.</span></footer>
  </main>;
}
