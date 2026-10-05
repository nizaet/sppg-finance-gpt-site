import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  CalendarCheck2,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  FileCheck2,
  FileSpreadsheet,
  Files,
  FolderCog,
  History,
  Loader2,
  ReceiptText,
  RefreshCw,
  Save,
} from "lucide-react";
import "./lpdh.css";
import { lpdhApi, downloadBase64 } from "./lpdhApi.js";
import { DailyPanel, DocumentsPanel, MasterPanel, normalizeDaily, normalizeMasters } from "./LpdhForms.jsx";
import LpdhSheets, { SHEET_ORDER } from "./LpdhSheets.jsx";

const SITE_LABELS = { MAJA: "Maja", CEMPLANG: "Cemplang" };

function todayJakarta() {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Jakarta", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const get = (type) => parts.find((item) => item.type === type)?.value || "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

function parseDateKey(value) {
  const [year, month, day] = String(value || "").split("-").map(Number);
  return { year, month, day };
}

function monthKeyFromDate(value) {
  const { year, month } = parseDateKey(value);
  return `${year}-${String(month).padStart(2, "0")}`;
}

function shiftMonth(monthKey, delta) {
  const [year, month] = monthKey.split("-").map(Number);
  const date = new Date(year, month - 1 + delta, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function dateKey(year, month, day) {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function weekdayServiceDates(monthKey) {
  const [year, month] = monthKey.split("-").map(Number);
  const daysInMonth = new Date(year, month, 0).getDate();
  const result = [];
  for (let day = 1; day <= daysInMonth; day += 1) {
    const weekday = new Date(year, month - 1, day).getDay();
    if (weekday >= 1 && weekday <= 5) result.push(dateKey(year, month, day));
  }
  return result;
}

function formatDateLabel(value) {
  const { year, month, day } = parseDateKey(value);
  if (!year || !month || !day) return value;
  return new Intl.DateTimeFormat("id-ID", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "Asia/Jakarta" }).format(new Date(Date.UTC(year, month - 1, day, 6)));
}

function monthLabel(monthKey) {
  const [year, month] = monthKey.split("-").map(Number);
  return new Intl.DateTimeFormat("id-ID", { month: "long", year: "numeric", timeZone: "Asia/Jakarta" }).format(new Date(Date.UTC(year, month - 1, 1, 6)));
}

function MonthGrid({ monthKey, selectedDate, effectiveDates = [], calendarItems = [], onSelect, mode = "report" }) {
  const [year, month] = monthKey.split("-").map(Number);
  const firstWeekday = new Date(year, month - 1, 1).getDay();
  const daysInMonth = new Date(year, month, 0).getDate();
  const effective = useMemo(() => new Set(effectiveDates), [effectiveDates]);
  const statusMap = useMemo(() => Object.fromEntries((calendarItems || []).map((item) => [item.serviceDate, item])), [calendarItems]);
  const today = todayJakarta();
  const cells = Array.from({ length: firstWeekday + daysInMonth }, (_, index) => index < firstWeekday ? null : index - firstWeekday + 1);

  return <>
    <div className="lpdh-calendar-weekdays" aria-hidden="true">{["Min","Sen","Sel","Rab","Kam","Jum","Sab"].map((d)=><span key={d}>{d}</span>)}</div>
    <div className="lpdh-calendar-grid">
      {cells.map((day,index)=>{
        if(!day) return <span className="lpdh-calendar-empty" key={`blank-${index}`}/>;
        const key=dateKey(year,month,day); const isEffective=effective.has(key); const selected=selectedDate===key; const isToday=today===key;
        const weekend=[0,6].includes(new Date(year,month-1,day).getDay());
        const item=statusMap[key] || {};
        const reportStatus=item.status || "EMPTY";
        const statusLabel=reportStatus==="GENERATED"?"Sudah generate":reportStatus==="READY"?"Siap generate":reportStatus==="DRAFT"?"Draft":item.finalized?"Final kalkulator":"Belum diisi";
        return <button key={key} type="button" onClick={()=>onSelect(key)}
          className={`lpdh-calendar-day ${selected?"selected":""} ${isToday?"today":""} ${isEffective?"effective":"non-effective"} ${mode==="master"?"service-toggle":""} status-${String(reportStatus).toLowerCase()}`}>
          <span className="lpdh-calendar-day-number">{day}</span>
          <span className="lpdh-calendar-day-status">{mode==="master" ? (isEffective?"Pelayanan efektif":weekend?"Akhir pekan":"Tidak efektif") : (isEffective?statusLabel:"Tidak efektif")}</span>
        </button>;
      })}
    </div>
  </>;
}

function CalendarPanel({ selectedDate, setSelectedDate, effectiveDates, calendarItems, onOpenDaily, onOpenMaster }) {
  const [monthKey,setMonthKey]=useState(monthKeyFromDate(selectedDate));
  useEffect(()=>setMonthKey(monthKeyFromDate(selectedDate)),[selectedDate]);
  const isEffective=effectiveDates.includes(selectedDate);
  return <section className="lpdh-calendar-wrap">
    <div className="lpdh-calendar-toolbar"><div><div className="lpdh-kicker">LAPORAN HARIAN</div><h2>Kalender LPDH</h2><p>Pilih tanggal. Data setiap hari tersimpan terpisah dan hanya Hari Pelayanan Efektif yang dapat digenerate.</p></div>
      <div className="lpdh-calendar-month-nav"><button onClick={()=>setMonthKey(shiftMonth(monthKey,-1))}><ChevronLeft size={18}/></button><strong>{monthLabel(monthKey)}</strong><button onClick={()=>setMonthKey(shiftMonth(monthKey,1))}><ChevronRight size={18}/></button></div>
    </div>
    <MonthGrid monthKey={monthKey} selectedDate={selectedDate} effectiveDates={effectiveDates} calendarItems={calendarItems} onSelect={setSelectedDate}/>
    <div className="lpdh-selected-date"><div><span>Tanggal aktif</span><strong>{formatDateLabel(selectedDate)}</strong><small>{isEffective?"Hari Pelayanan Efektif":"Bukan Hari Pelayanan Efektif"}</small></div>
      <div className="lpdh-inline-actions"><button type="button" onClick={onOpenMaster}>Atur HPE</button><button type="button" className="primary" onClick={onOpenDaily}>Buka Data Harian</button></div>
    </div>
  </section>;
}

function ServiceDaysPanel({ site, effectiveDates, monthKey, setMonthKey, onSave, busy }) {
  const [draft,setDraft]=useState(effectiveDates);
  useEffect(()=>setDraft(effectiveDates),[effectiveDates,monthKey,site]);
  const toggle=(key)=>setDraft((current)=>current.includes(key)?current.filter((x)=>x!==key):[...current,key].sort());
  const monthDates=draft.filter((x)=>x.startsWith(`${monthKey}-`));
  const chooseWeekdays=()=>{
    const keep=draft.filter((x)=>!x.startsWith(`${monthKey}-`));
    setDraft([...keep,...weekdayServiceDates(monthKey)].sort());
  };
  const clearMonth=()=>setDraft(draft.filter((x)=>!x.startsWith(`${monthKey}-`)));
  return <section className="lpdh-calendar-wrap">
    <div className="lpdh-calendar-toolbar"><div><div className="lpdh-kicker">MASTER BULANAN · {SITE_LABELS[site]}</div><h2>Hari Pelayanan Efektif</h2><p>Klik tanggal untuk aktif/nonaktif. Gunakan Senin–Jumat sebagai dasar, lalu matikan libur nasional, cuti bersama, atau pengecualian lokal.</p></div>
      <div className="lpdh-calendar-month-nav"><button onClick={()=>setMonthKey(shiftMonth(monthKey,-1))}><ChevronLeft size={18}/></button><strong>{monthLabel(monthKey)}</strong><button onClick={()=>setMonthKey(shiftMonth(monthKey,1))}><ChevronRight size={18}/></button></div></div>
    <div className="lpdh-effective-actions"><button className="primary" type="button" onClick={chooseWeekdays}>Pilih Senin–Jumat</button><button type="button" onClick={clearMonth}>Kosongkan bulan</button><span>{monthDates.length} hari efektif</span></div>
    <MonthGrid monthKey={monthKey} effectiveDates={draft} onSelect={toggle} mode="master"/>
    <div className="lpdh-sticky-save"><button type="button" className="primary" disabled={busy} onClick={()=>onSave(monthKey,monthDates)}><Save size={16}/> Simpan HPE {monthLabel(monthKey)}</button></div>
  </section>;
}

function ReviewPanel({ masters, daily, preview, serviceDate, referenceRows, activeSheet, setActiveSheet }) {
  return <div className="lpdh-review">
    <div className="lpdh-review-head"><div><div className="lpdh-kicker">PREVIEW SEBELUM GENERATE</div><h2>Workbook LPDH di dalam aplikasi</h2><p>Tab mengikuti urutan sheet Excel resmi. Nilai dan validasi diperiksa di sini sebelum file dibuat.</p></div>
      <div className={preview?.ready?"lpdh-readiness ready":"lpdh-readiness blocked"}>{preview?.ready?<FileCheck2 size={18}/>:<ClipboardCheck size={18}/>}<span>{preview?.ready?"SIAP GENERATE":`${preview?.errorCount ?? "-"} PERIKSA`}</span></div>
    </div>
    <div className="lpdh-sheet-tabs">{SHEET_ORDER.map((sheet)=><button key={sheet} className={activeSheet===sheet?"active":""} type="button" onClick={()=>setActiveSheet(sheet)}>{sheet}</button>)}</div>
    <LpdhSheets activeSheet={activeSheet} masters={masters} daily={daily} preview={preview} serviceDate={serviceDate} referenceRows={referenceRows}/>
  </div>;
}

function GeneratePanel({ site, serviceDate, preview, history, onRefresh, onGenerate, busy, finalPlan }) {
  return <div className="lpdh-stack">
    <section className="lpdh-form-section"><div className="lpdh-form-section-head"><div><h3>Generate LPDH Excel</h3><p>File hanya dapat dibuat bila seluruh G_CekPPK berstatus OK.</p></div><div className="lpdh-inline-actions"><button type="button" onClick={onRefresh}><RefreshCw size={15}/> Validasi ulang</button><button type="button" className="primary" disabled={busy||!preview?.ready} onClick={onGenerate}><FileSpreadsheet size={15}/> Generate Excel</button></div></div>
      <div className="lpdh-generate-gate">
        <div className={finalPlan?.payload?"ok":"bad"}><strong>1. Final Kalkulator</strong><span>{finalPlan?.payload?`${finalPlan.planName||"Rencana"} · revisi ${finalPlan.revision||1}`:"Belum final"}</span></div>
        <div className={preview?.effective?"ok":"bad"}><strong>2. Hari Pelayanan</strong><span>{preview?.effective?"Efektif":"Tidak efektif"}</span></div>
        <div className={preview?.errorCount===0?"ok":"bad"}><strong>3. G_CekPPK</strong><span>{preview?.errorCount===0?"26 pemeriksaan bersih":`${preview?.errorCount??"-"} perlu diperbaiki`}</span></div>
      </div>
      {!preview?.ready&&<div className="lpdh-note warn">Generate terkunci. Buka Review LPDH → G_CekPPK untuk melihat tepatnya kesalahan mana yang harus diperbaiki.</div>}
    </section>
    <section className="lpdh-form-section"><div className="lpdh-form-section-head"><div><h3>Riwayat Generate</h3><p>Jejak file yang pernah dibuat untuk {SITE_LABELS[site]}.</p></div></div>
      <div className="lpdh-table-wrap"><table className="lpdh-data-table"><thead><tr><th>Tanggal Pelayanan</th><th>File</th><th>Status</th><th>Dibuat</th><th>Aktor</th></tr></thead><tbody>
        {(history||[]).map((x)=><tr key={x.id}><td>{x.service_date}</td><td>{x.filename}</td><td>{x.validation_status}</td><td>{String(x.generated_at||"").replace("T"," ").slice(0,19)}</td><td>{x.generated_by||""}</td></tr>)}
        {!history?.length&&<tr><td colSpan="5" className="lpdh-empty-cell">Belum ada file yang digenerate.</td></tr>}
      </tbody></table></div>
    </section>
  </div>;
}

export default function LpdhWorkspace({ role, onLogout }) {
  const accountRole=String(role||"").toUpperCase();
  const requestedSite=typeof window!=="undefined" ? String(new URLSearchParams(window.location.search).get("site")||"").toUpperCase() : "";
  const initialSite=accountRole==="OWNER" && (requestedSite==="MAJA" || requestedSite==="CEMPLANG") ? requestedSite : (accountRole==="OWNER"?"MAJA":accountRole);
  const [site,setSite]=useState(initialSite);
  const [selectedDate,setSelectedDate]=useState(todayJakarta());
  const [effectiveMonth,setEffectiveMonth]=useState(monthKeyFromDate(todayJakarta()));
  const [effectiveDates,setEffectiveDates]=useState([]);
  const [calendarItems,setCalendarItems]=useState([]);
  const [masters,setMasters]=useState(normalizeMasters({}));
  const [daily,setDaily]=useState(normalizeDaily({},todayJakarta()));
  const [finalPlan,setFinalPlan]=useState(null);
  const [preview,setPreview]=useState(null);
  const [referenceRows,setReferenceRows]=useState([]);
  const [history,setHistory]=useState([]);
  const [active,setActive]=useState("calendar");
  const [activeSheet,setActiveSheet]=useState("Identitas");
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState(null);

  const flash=(text,type="success")=>{setMessage({text,type});window.clearTimeout(window.__lpdhFlash);window.__lpdhFlash=window.setTimeout(()=>setMessage(null),6000);};

  const loadEffective=useCallback(async(targetSite=site,month=effectiveMonth)=>{
    const r=await lpdhApi.getEffectiveDays(targetSite,month); setEffectiveDates((r.dates||[]).map(String)); return r;
  },[site,effectiveMonth]);

  const loadCalendar=useCallback(async(targetSite=site,month=effectiveMonth)=>{
    const r=await lpdhApi.calendar(targetSite,month); setCalendarItems(r.items||[]); return r;
  },[site,effectiveMonth]);

  const loadMasters=useCallback(async(targetSite=site)=>{
    const r=await lpdhApi.getMasters(targetSite); setMasters(normalizeMasters(r.data||{})); return r;
  },[site]);

  const loadDaily=useCallback(async(targetSite=site,date=selectedDate)=>{
    const r=await lpdhApi.getDaily(targetSite,date); setDaily(normalizeDaily(r.data||{},date)); setFinalPlan(r.finalPlan||null); return r;
  },[site,selectedDate]);

  const refreshPreview=useCallback(async(targetSite=site,date=selectedDate)=>{
    const r=await lpdhApi.preview(targetSite,date); setPreview(r); return r;
  },[site,selectedDate]);

  const boot=useCallback(async()=>{
    setBusy(true);
    try{
      const month=monthKeyFromDate(selectedDate); setEffectiveMonth(month);
      const results=await Promise.allSettled([loadMasters(site),loadDaily(site,selectedDate),loadEffective(site,month),loadCalendar(site,month),lpdhApi.reference(site),lpdhApi.history(site)]);
      if(results[4].status==="fulfilled") setReferenceRows(results[4].value.rows||[]);
      if(results[5].status==="fulfilled") setHistory(results[5].value.items||[]);
      try{await refreshPreview(site,selectedDate);}catch{}
      const rejected=results.find((x)=>x.status==="rejected");
      if(rejected) throw rejected.reason;
    }catch(err){flash(err.message||"Gagal memuat LPDH","error");}
    finally{setBusy(false);}
  },[site,selectedDate,loadMasters,loadDaily,loadEffective,loadCalendar,refreshPreview]);

  useEffect(()=>{boot();},[site,selectedDate]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(()=>{
    const month=monthKeyFromDate(selectedDate);
    if(month!==effectiveMonth){setEffectiveMonth(month);Promise.all([loadEffective(site,month),loadCalendar(site,month)]).catch((e)=>flash(e.message,"error"));}
  },[selectedDate]);

  const changeSite=(next)=>{setSite(next);setActive("calendar");setPreview(null);};

  const saveEffective=async(month,dates)=>{
    setBusy(true); try{await lpdhApi.saveEffectiveDays(site,month,dates);setEffectiveDates(dates);flash(`${dates.length} Hari Pelayanan Efektif tersimpan.`);await Promise.all([refreshPreview(),loadCalendar(site,month)]);}catch(e){flash(e.message,"error");}finally{setBusy(false);}
  };

  const generate=async()=>{
    setBusy(true);
    try{
      const latest=await refreshPreview();
      if(!latest.ready){setActive("review");setActiveSheet("G_CekPPK");throw new Error(`Masih ada ${latest.errorCount} pemeriksaan yang harus diperbaiki.`);}
      const result=await lpdhApi.generate(site,selectedDate);
      downloadBase64(result.filename,result.mimeType,result.contentBase64);
      flash(`${result.filename} berhasil dibuat dengan rumus workbook tetap aktif.`);
      const [h]=await Promise.all([lpdhApi.history(site),loadCalendar(site,monthKeyFromDate(selectedDate))]);setHistory(h.items||[]);
      await loadDaily();
    }catch(e){flash(e.message||"Generate gagal","error");}
    finally{setBusy(false);}
  };

  const nav=[
    ["calendar","Kalender LPDH",CalendarDays],
    ["service-days","Hari Pelayanan Efektif",CalendarCheck2],
    ["masters","Master Data",FolderCog],
    ["daily","Input Harian",Files],
    ["documents","Vendor · Invoice & Kuitansi",ReceiptText],
    ["review","Review LPDH / Sheet Excel",FileCheck2],
    ["generate","Generate & Riwayat",History],
  ];

  return <main className="lpdh-page">
    {busy&&<div className="lpdh-busy"><Loader2 size={18}/><span>Memproses…</span></div>}
    <header className="lpdh-header"><div><div className="lpdh-kicker">{accountRole==="OWNER"?"YAYASAN · ":""}SPPG {site}</div><h1>LPDH & Administrasi {SITE_LABELS[site]}</h1><p>{formatDateLabel(selectedDate)} · data cloud per dapur dan per tanggal pelayanan.</p>
      {accountRole==="OWNER"&&<div className="lpdh-site-switch">{["MAJA","CEMPLANG"].map((item)=><button key={item} type="button" className={site===item?"active":""} onClick={()=>changeSite(item)}>{SITE_LABELS[item]}</button>)}</div>}
    </div><div className="lpdh-header-actions"><button type="button" onClick={()=>window.location.assign("/")}>Pilih aplikasi</button><button type="button" onClick={boot}><RefreshCw size={15}/> Refresh</button><button type="button" className="lpdh-danger" onClick={onLogout}>Keluar</button></div></header>

    {message&&<div className={`lpdh-flash ${message.type}`}>{message.text}</div>}

    <div className="lpdh-layout">
      <nav className="lpdh-nav" aria-label="Menu LPDH">{nav.map(([id,label,Icon])=><button key={id} type="button" className={active===id?"active":""} onClick={()=>setActive(id)}><Icon size={17}/>{label}</button>)}
        <div className="lpdh-nav-date"><span>Tanggal aktif</span><input type="date" value={selectedDate} onChange={(e)=>setSelectedDate(e.target.value)}/><small>{effectiveDates.includes(selectedDate)?"HPE aktif":"Bukan HPE"}</small></div>
      </nav>

      <section className="lpdh-content">
        {active==="calendar"&&<CalendarPanel selectedDate={selectedDate} setSelectedDate={setSelectedDate} effectiveDates={effectiveDates} calendarItems={calendarItems} onOpenDaily={()=>setActive("daily")} onOpenMaster={()=>setActive("service-days")}/>} 
        {active==="service-days"&&<ServiceDaysPanel site={site} effectiveDates={effectiveDates} monthKey={effectiveMonth} setMonthKey={(m)=>{setEffectiveMonth(m);loadEffective(site,m).catch((e)=>flash(e.message,"error"));}} onSave={saveEffective} busy={busy}/>}
        {active==="masters"&&<MasterPanel site={site} masters={masters} setMasters={setMasters} api={lpdhApi} onSaved={flash} onReload={()=>loadMasters(site)}/>}
        {active==="daily"&&<DailyPanel site={site} serviceDate={selectedDate} masters={masters} daily={daily} setDaily={setDaily} finalPlan={finalPlan} preview={preview} api={lpdhApi} onSaved={flash} onPreview={async()=>{await refreshPreview();await loadCalendar(site,monthKeyFromDate(selectedDate));}}/>} 
        {active==="documents"&&<DocumentsPanel serviceDate={selectedDate} daily={daily} preview={preview} masters={masters} onMessage={flash}/>}
        {active==="review"&&<ReviewPanel masters={masters} daily={daily} preview={preview} serviceDate={selectedDate} referenceRows={referenceRows} activeSheet={activeSheet} setActiveSheet={setActiveSheet}/>}
        {active==="generate"&&<GeneratePanel site={site} serviceDate={selectedDate} preview={preview} history={history} onRefresh={refreshPreview} onGenerate={generate} busy={busy} finalPlan={finalPlan}/>}
      </section>
    </div>
  </main>;
}
