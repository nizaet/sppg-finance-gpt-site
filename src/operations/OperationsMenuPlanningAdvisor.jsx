import React, { useState } from "react";
import { CalendarDays, ChevronDown, CircleCheck, CircleAlert, RefreshCw, Scale, ShieldCheck, Sparkles } from "lucide-react";
import { operationsApi } from "./apiClient";

function todayJakarta() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Jakarta", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}
function formatDate(value) {
  if (!value) return "-";
  const parsed = new Date(`${String(value).slice(0, 10)}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? String(value) : new Intl.DateTimeFormat("id-ID", { weekday: "long", day: "numeric", month: "short" }).format(parsed);
}
function money(value) {
  return value === null || value === undefined ? "Belum dapat dihitung" : new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(Number(value));
}
function number(value) { return value === null || value === undefined ? "-" : new Intl.NumberFormat("id-ID", { maximumFractionDigits: 3 }).format(Number(value)); }

function DayCard({ day }) {
  const isExisting = day.state === "EXISTING";
  const isReady = day.state === "PROPOSED_DRAFT";
  return <article className={`weekly-menu-day ${isExisting ? "existing" : isReady ? "ready" : "needs-data"}`}>
    <div className="weekly-menu-day-head">
      <div><span className="weekly-menu-date">{formatDate(day.date)}</span><h4>{day.menuTitle || "Belum bisa dibuat"}</h4></div>
      <span className={`weekly-menu-status ${isExisting ? "existing" : isReady ? "ready" : "missing"}`}>{isExisting ? "SUDAH ADA" : isReady ? "DRAFT" : "PERLU DATA"}</span>
    </div>
    {day.recipeNames?.length > 0 && <p className="weekly-menu-recipes">{day.recipeNames.join(" · ")}</p>}
    {day.fruitNames?.length > 0 && <p className="weekly-menu-fruit">Buah: {day.fruitNames.join(", ")}</p>}
    <div className="weekly-menu-metrics">
      <span><small>Target PM</small><strong>{number(day.targetPm)}</strong></span>
      <span><small>Estimasi total</small><strong>{money(day.estimatedTotal)}</strong></span>
      <span><small>Biaya / PM</small><strong>{money(day.estimatedPerPm)}</strong></span>
      <span><small>Pagu / PM</small><strong>{money(day.paguPerPm)}</strong></span>
    </div>
    {day.withinPagu !== null && <div className={`weekly-menu-pagu ${day.withinPagu ? "pass" : "over"}`}>{day.withinPagu ? <CircleCheck size={15} /> : <CircleAlert size={15} />}{day.withinPagu ? "Masuk pagu berdasarkan harga planning" : "Melebihi pagu — jangan dipindahkan ke Kalkulator"}</div>}
    {day.sourceTemplate && <p className="weekly-menu-source">Pola sumber: {formatDate(day.sourceTemplate.distributionDate)} · {day.sourceTemplate.daysSinceLastPlanned !== null && day.sourceTemplate.daysSinceLastPlanned !== undefined ? `terakhir dipakai ${day.sourceTemplate.daysSinceLastPlanned} hari lalu` : `snapshot #${day.sourceTemplate.snapshotId}`}</p>}
    {(day.materials?.length > 0 || day.dataGaps?.length > 0) && <details className="weekly-menu-details">
      <summary><ChevronDown size={15} /> Bahan & perhitungan</summary>
      {day.materials?.length > 0 && <div className="weekly-menu-materials">{day.materials.map((item, index) => <div key={`${item.itemName}-${index}`}><strong>{item.itemName || "Tanpa nama"}</strong><span>{number(item.quantity ?? item.plannedQty)} {item.unit || ""} × {money(item.planningPrice)}</span><b>{money(item.estimatedLineTotal)}</b></div>)}</div>}
      {day.dataGaps?.length > 0 && <ul className="weekly-menu-gaps">{day.dataGaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul>}
    </details>}
  </article>;
}

export default function OperationsMenuPlanningAdvisor() {
  const [site, setSite] = useState("MAJA");
  const [weekStart, setWeekStart] = useState(todayJakarta);
  const [days, setDays] = useState("7");
  const [targetPm, setTargetPm] = useState("");
  const [paguPerPm, setPaguPerPm] = useState("");
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const buildDraft = async () => {
    setLoading(true); setError("");
    try {
      const data = await operationsApi.getWeeklyMenuDraft({ site, weekStart, days: Number(days), targetPm, paguPerPm });
      setDraft(data);
      if (!targetPm && data.targetPm) setTargetPm(String(data.targetPm));
      if (!paguPerPm && data.paguPerPm) setPaguPerPm(String(data.paguPerPm));
    } catch (err) { setDraft(null); setError(err.message || "Gagal membuat draft menu mingguan."); }
    finally { setLoading(false); }
  };

  return <section className="ops-module menu-advisor weekly-menu-planner">
    <div className="ops-module-header">
      <div><span className="ops-kicker">DRAFT SAJA · TIDAK MENYIMPAN</span><h3><Sparkles size={21} /> Rencana Menu Mingguan</h3><p>Mengisi hari yang belum ada planning dari pola menu, bahan, bumbu, harga, dan porsi historis Calculator.</p></div>
    </div>
    <div className="menu-advisor-boundary"><ShieldCheck size={19} /><div><strong>Belum mengubah apa pun.</strong> Hasil ini hanya DRAFT; tidak membuat Kalkulator, PO, penerimaan, pembayaran, atau Excel.</div></div>
    <div className="weekly-menu-form">
      <label>Site<select value={site} onChange={(event) => setSite(event.target.value)}><option value="MAJA">MAJA</option><option value="CEMPLANG">CEMPLANG</option></select></label>
      <label>Mulai minggu<input type="date" value={weekStart} onChange={(event) => setWeekStart(event.target.value)} /></label>
      <label>Jumlah hari<select value={days} onChange={(event) => setDays(event.target.value)}><option value="5">5 hari</option><option value="6">6 hari</option><option value="7">7 hari</option></select></label>
      <label>Target PM<input type="number" min="1" placeholder="Ambil dari histori" value={targetPm} onChange={(event) => setTargetPm(event.target.value)} /></label>
      <label>Pagu per PM<input type="number" min="1" placeholder="Rp, ambil dari histori" value={paguPerPm} onChange={(event) => setPaguPerPm(event.target.value)} /></label>
      <button type="button" onClick={buildDraft} disabled={loading}><RefreshCw size={16} className={loading ? "ops-spin" : ""} />{loading ? "Menyusun…" : "Buat DRAFT Mingguan"}</button>
    </div>
    <p className="weekly-menu-form-help">Kosongkan Target PM atau Pagu/PM bila ingin mengambil nilai dari planning historis terakhir. Jika tidak tersedia, asisten akan menandainya sebagai data wajib.</p>
    {error && <div className="ops-error">{error}</div>}
    {!draft && !loading && <div className="ops-empty weekly-menu-empty"><CalendarDays size={20} /> Tentukan minggu, target PM dan pagu bila ada, lalu buat DRAFT.</div>}
    {draft && <>
      <div className="weekly-menu-summary">
        <span><small>Hari sudah ada</small><strong>{draft.summary?.existingDays || 0}</strong></span>
        <span><small>Draft hari kosong</small><strong>{draft.summary?.proposedDays || 0}</strong></span>
        <span><small>Perlu data</small><strong>{draft.summary?.needsDataDays || 0}</strong></span>
        <span><small>Total draft</small><strong>{money(draft.summary?.totalEstimatedSpend)}</strong></span>
        <span className={draft.summary?.allProposedWithinPagu ? "ok" : ""}><small>Status pagu</small><strong>{draft.summary?.allProposedWithinPagu === null ? "Belum lengkap" : draft.summary?.allProposedWithinPagu ? "Masuk pagu" : "Ada yang lewat"}</strong></span>
      </div>
      <div className="weekly-menu-rules"><Scale size={17} /><div><strong>Aturan yang dipakai</strong><span>{draft.rulesApplied?.join(" ")}</span></div></div>
      <div className="weekly-menu-days">{draft.days?.map((day) => <DayCard key={day.date} day={day} />)}</div>
    </>}
  </section>;
}
