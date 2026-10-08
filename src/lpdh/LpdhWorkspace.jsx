import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import InvoiceRecap from './InvoiceRecap.jsx';
import { savedDailyMatches, pendingReview } from './reviewSaveGate.mjs';
import { lpdhApi, downloadBase64 } from "./lpdhApi.js";
import { DailyPanel, MasterPanel, normalizeDaily, normalizeMasters, syncDailyMasterTargets, applyRoutineDaily } from "./LpdhForms.jsx";
import DocumentWorkspace from "../documents/DocumentWorkspace.jsx";
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

function ReviewPanel({ masters, daily, preview, serviceDate, referenceRows, activeSheet, setActiveSheet, onOpenIssue, site, onApprovalSaved }) {
  return <div className="lpdh-review">
    <div className="lpdh-review-head"><div><div className="lpdh-kicker">PREVIEW ISIAN TEMPLATE</div><h2>Workbook LPDH di dalam aplikasi</h2><p>Tab mengikuti urutan sheet Excel resmi. Nilai dan validasi diperiksa sebelum template diisi dan diunduh.</p>{preview?.previewSource === "CURRENT_FORM" && <p>Insentif Review hanya ditampilkan setelah Data Harian disimpan dan validasi diperbarui. Perubahan baru perlu Simpan &amp; Validasi kembali.</p>}</div>
      <div className={preview?.ready?"lpdh-readiness ready":"lpdh-readiness blocked"}>{preview?.ready?<FileCheck2 size={18}/>:<ClipboardCheck size={18}/>}<span>{preview?.ready?"SIAP UNDUH TERVALIDASI":`${preview?.errorCount ?? "-"} PERIKSA`}</span></div>
    </div>
    <div className="lpdh-sheet-tabs">{SHEET_ORDER.map((sheet)=><button key={sheet} className={activeSheet===sheet?"active":""} type="button" onClick={()=>setActiveSheet(sheet)}>{sheet}</button>)}</div>
    <LpdhSheets activeSheet={activeSheet} masters={masters} daily={daily} preview={preview} serviceDate={serviceDate} referenceRows={referenceRows} onOpenIssue={onOpenIssue} site={site} onApprovalSaved={onApprovalSaved}/>
  </div>;
}

function GeneratePanel({ site, serviceDate, preview, history, onRefresh, onGenerate, busy, finalPlan, onOpenIssue }) {
  return <div className="lpdh-stack">
    <section className="lpdh-form-section"><div className="lpdh-form-section-head"><div><h3>Isi Template & Unduh Excel LPDH</h3><p>Salinan template server diisi dari data terakhir yang disimpan. Rumus dan format tetap ikut. Unduhan DRAFT tidak mengunci data harian.</p></div><div className="lpdh-inline-actions"><button type="button" onClick={onRefresh}>Validasi ulang</button><button type="button" disabled={busy} onClick={()=>onGenerate(true)}>Isi Template & Unduh DRAFT</button><button type="button" className="primary" disabled={busy||!preview?.ready} onClick={()=>onGenerate(false)}>Unduh Excel Tervalidasi</button></div></div>
      <div className="lpdh-generate-gate">
        <div className={finalPlan?.payload?"ok":"bad"}><strong>1. Final Kalkulator</strong><span>{finalPlan?.payload?`${finalPlan.planName||"Rencana"} · revisi ${finalPlan.revision||1}`:"Belum final"}</span></div>
        <div className={preview?.effective?"ok":"bad"}><strong>2. Hari Pelayanan</strong><span>{preview?.effective?"Efektif":"Tidak efektif"}</span></div>
        <div className={preview?.errorCount===0?"ok":"bad"}><strong>3. G_CekPPK</strong><span>{preview?.errorCount===0?"26 pemeriksaan bersih":`${preview?.errorCount??"-"} perlu diperbaiki`}</span></div>
      </div>
      {!preview?.ready&&<div className="lpdh-note warn">DRAFT tetap dapat diunduh meski belum OK. Klik pemeriksaan untuk membuka isian terkait.{(preview?.checks||[]).filter(x=>!x.ok).map(x=><button type="button" className="lpdh-issue-link" key={x.no} onClick={()=>onOpenIssue(x)}>{x.no}. {x.check} · Buka isian</button>)}</div>}
    </section>
    <section className="lpdh-form-section"><div className="lpdh-form-section-head"><div><h3>Riwayat Excel Tervalidasi</h3><p>Jejak unduhan tervalidasi untuk {SITE_LABELS[site]}. Unduhan DRAFT tidak mengubah riwayat final.</p></div></div>
      <div className="lpdh-table-wrap"><table className="lpdh-data-table"><thead><tr><th>Tanggal Pelayanan</th><th>File</th><th>Status</th><th>Dibuat</th><th>Aktor</th></tr></thead><tbody>
        {(history||[]).map((x)=><tr key={x.id}><td>{x.service_date}</td><td>{x.filename}</td><td>{x.validation_status}</td><td>{String(x.generated_at||"").replace("T"," ").slice(0,19)}</td><td>{x.generated_by||""}</td></tr>)}
        {!history?.length&&<tr><td colSpan="5" className="lpdh-empty-cell">Belum ada unduhan tervalidasi.</td></tr>}
      </tbody></table></div>
    </section>
  </div>;
}

export default function LpdhWorkspace({ role, onLogout }) {
  const accountRole=String(role||"").toUpperCase();
  const requestedSite=typeof window!=="undefined" ? String(new URLSearchParams(window.location.search).get("site")||"").toUpperCase() : "";
  const initialSite=accountRole==="OWNER" && (requestedSite==="MAJA" || requestedSite==="CEMPLANG") ? requestedSite : (accountRole==="OWNER"?"MAJA":accountRole);
  const [site,setSite]=useState(initialSite);
  useEffect(()=>{document.title=`LPDH ${site==='CEMPLANG'?'Cemplang':'Maja'}`;for(const rel of ['icon','shortcut icon']){const link=document.querySelector(`link[rel='${rel}']`);if(link)link.href=`/favicon-lpdh-${site.toLowerCase()}.svg`; }},[site]);
  const requestedDate = new URLSearchParams(window.location.search).get("date") || "";
  const requestedTab = new URLSearchParams(window.location.search).get("tab") || "";
  const [selectedDate,setSelectedDate]=useState(/^\d{4}-\d{2}-\d{2}$/.test(requestedDate) && !Number.isNaN(Date.parse(requestedDate)) ? requestedDate : todayJakarta());
  const [effectiveMonth,setEffectiveMonth]=useState(monthKeyFromDate(todayJakarta()));
  const [effectiveDates,setEffectiveDates]=useState([]);
  const [calendarItems,setCalendarItems]=useState([]);
  const [masters,setMasters]=useState(normalizeMasters({}));
  const [daily,setDaily]=useState(normalizeDaily({},todayJakarta()));
  const [finalPlan,setFinalPlan]=useState(null);
  const [preview,setPreview]=useState(null);
  const [savedDaily,setSavedDaily]=useState(null);
  const dailySaved = savedDailyMatches(daily,savedDaily);
  const reviewPreview = dailySaved ? preview : pendingReview(preview);
  const reviewDaily = dailySaved ? daily : {...daily,incentive:{...daily.incentive,statementAmount:0,paidAmount:0}};
  const [referenceRows,setReferenceRows]=useState([]);
  const [history,setHistory]=useState([]);
  const [active,setActive]=useState(["documents", "daily"].includes(requestedTab) ? requestedTab : "calendar");
  const [activeSheet,setActiveSheet]=useState("Identitas");
  const [issueTarget,setIssueTarget]=useState(null);
  const openIssue=issue=>{
    const routes={1:['masters','identity',['SPPG','VA']],2:['service-days'],3:['daily','pm',['Produksi']],4:['daily','pm',['Distribusi','Fleet']],5:['daily','pm',['Alasan']],6:['masters','parameters',['Buffer']],7:['daily','pm',['BNBA','BAST']],8:['daily','pm',['Link BAST']],9:['daily','pm',['Target']],10:['masters','parameters',['Indeks']],11:['daily','raw',['Harga']],12:['daily','operations',['Harga']],13:['daily','proof',['Link']],14:['documents'],15:['documents'],16:['daily','volunteers',['Link']],17:['daily','incentive'],18:['daily','incentive'],19:['daily','incentive'],20:['daily','incentive',['Link']],21:['daily','balance',['Bukti']],22:['daily','balance'],23:['daily','balance',['Saldo VA']],24:['masters','signers'],25:['daily','upload'],26:['daily','balance']};
    const [page,tab,fields=[]]=routes[Number(issue.no)]||['review'];
    setIssueTarget({tab,fields,issue,token:Date.now()});setActive(page);
  };
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState(null);
  const dailyRead = useRef(0);
  const previewRead = useRef(0);
  const dailyRef = useRef(daily);
  const viewContext = useRef("");
  dailyRef.current = daily;
  viewContext.current = `${site}|${selectedDate}`;

  const flash=(text,type="success")=>{setMessage({text,type});window.clearTimeout(window.__lpdhFlash);window.__lpdhFlash=window.setTimeout(()=>setMessage(null),6000);};

  const loadEffective=useCallback(async(targetSite=site,month=effectiveMonth)=>{
    const r=await lpdhApi.getEffectiveDays(targetSite,month); setEffectiveDates((r.dates||[]).map(String)); return r;
  },[site,effectiveMonth]);

  const loadCalendar=useCallback(async(targetSite=site,month=effectiveMonth)=>{
    const r=await lpdhApi.calendar(targetSite,month); setCalendarItems(r.items||[]); return r;
  },[site,effectiveMonth]);

  const loadMasters=useCallback(async(targetSite=site)=>{
    const r=await lpdhApi.getMasters(targetSite);
    if (viewContext.current.startsWith(`${targetSite}|`)) setMasters(normalizeMasters(r.data||{}));
    return r;
  },[site]);

  const loadDaily=useCallback(async(targetSite=site,date=selectedDate)=>{
    const version = ++dailyRead.current;
    const r=await lpdhApi.getDaily(targetSite,date);
    if (version === dailyRead.current && viewContext.current === `${targetSite}|${date}`) { const next=normalizeDaily(r.data||{},date); setDaily(next); setSavedDaily(next._reviewValidated ? JSON.stringify(next) : null); setFinalPlan(r.finalPlan||null); }
    return r;
  },[site,selectedDate]);

  const refreshPreview=useCallback(async(targetSite=site,date=selectedDate,draft)=>{
    const version = ++previewRead.current;
    const r = draft === undefined ? await lpdhApi.preview(targetSite,date) : await lpdhApi.previewDraft(targetSite,date,draft);
    if (version === previewRead.current && viewContext.current === `${targetSite}|${date}`) setPreview(r);
    return r;
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

  const reloadMasterTargets=async()=>{
    const context = `${site}|${selectedDate}`;
    const result = await loadMasters(site);
    if (viewContext.current !== context) return;
    const next = syncDailyMasterTargets(dailyRef.current, normalizeMasters(result.data || {}), selectedDate);
    setDaily(next);
    await refreshPreview(site,selectedDate,next);
  };

  const changePanel=async(id)=>{
    if (busy) return;
    if (id !== "review" && id !== "generate") return setActive(id);
    const context = `${site}|${selectedDate}`;
    setBusy(true);
    try {
      await refreshPreview(site,selectedDate,id === "review" ? dailyRef.current : undefined);
      if (viewContext.current === context) setActive(id);
    } catch (error) { if (viewContext.current === context) flash(error.message || "Review gagal diperbarui", "error"); }
    finally { if (viewContext.current === context) setBusy(false); }
  };

  const saveEffective=async(month,dates)=>{
    setBusy(true); try{await lpdhApi.saveEffectiveDays(site,month,dates);setEffectiveDates(dates);flash(`${dates.length} Hari Pelayanan Efektif tersimpan.`);await Promise.all([refreshPreview(),loadCalendar(site,month)]);}catch(e){flash(e.message,"error");}finally{setBusy(false);}
  };

  const generate=async(draftOnly=false)=>{
    setBusy(true);
    try{
      const latest=await refreshPreview();
      if(!latest.ready&&!draftOnly){setActive("review");setActiveSheet("G_CekPPK");throw new Error(`Masih ada ${latest.errorCount} pemeriksaan yang harus diperbaiki.`);}
      const result=await lpdhApi.generate(site,selectedDate,draftOnly);
      downloadBase64(result.filename,result.mimeType,result.contentBase64);
      flash(`${result.filename} terisi dari template, rumus tetap aktif.${draftOnly?' DRAFT untuk pemeriksaan, bukan laporan final.':''}`);
      if(draftOnly)return;
      const [h]=await Promise.all([lpdhApi.history(site),loadCalendar(site,monthKeyFromDate(selectedDate))]);setHistory(h.items||[]);
      await loadDaily();
    }catch(e){flash(e.message||"Generate gagal","error");}
    finally{setBusy(false);}
  };

  const nav=[
    ["calendar","Kalender LPDH",CalendarDays],
    ["service-days","Hari Pelayanan Efektif",CalendarCheck2],
    ["masters","Master Data",FolderCog],
    ["documents","Buat Invoice & Kuitansi",ReceiptText],
    ["daily","Data Harian dari Dokumen",Files],
    ["review","Review LPDH / Sheet Excel",FileCheck2],
    ["generate","Unduh Excel & Riwayat",History],
    ["invoice-recap","Rekap Invoice",ReceiptText],
  ];

  return <main className="lpdh-page">
    {busy&&<div className="lpdh-busy"><Loader2 size={18}/><span>Memproses…</span></div>}
    <header className="lpdh-header"><div><div className="lpdh-kicker">{accountRole==="OWNER"?"YAYASAN · ":""}SPPG {site}</div><h1>LPDH & Administrasi {SITE_LABELS[site]}</h1><p>{formatDateLabel(selectedDate)} · data cloud per dapur dan per tanggal pelayanan.</p>
      {accountRole==="OWNER"&&<div className="lpdh-site-switch">{["MAJA","CEMPLANG"].map((item)=><button key={item} type="button" className={site===item?"active":""} onClick={()=>changeSite(item)}>{SITE_LABELS[item]}</button>)}</div>}
    </div><div className="lpdh-header-actions"><button type="button" onClick={()=>window.location.assign("/")}>Pilih aplikasi</button><button type="button" onClick={boot}><RefreshCw size={15}/> Refresh</button><button type="button" className="lpdh-danger" onClick={onLogout}>Keluar</button></div></header>

    {message&&<div className={`lpdh-flash ${message.type}`}>{message.text}</div>}

    <div className="lpdh-layout">
      <nav className="lpdh-nav" aria-label="Menu LPDH">{nav.map(([id,label,Icon])=><button key={id} type="button" className={active===id?"active":""} onClick={()=>changePanel(id)}><Icon size={17}/>{label}</button>)}
        <div className="lpdh-nav-date"><span>Tanggal aktif</span><input type="date" value={selectedDate} onChange={(e)=>setSelectedDate(e.target.value)}/><small>{effectiveDates.includes(selectedDate)?"HPE aktif":"Bukan HPE"}</small></div>
      </nav>

      <section className="lpdh-content">
        {active==='invoice-recap'&&<InvoiceRecap site={site} onOpen={date=>{setSelectedDate(date);setActive('documents');}}/>}
        {issueTarget&&<div className="lpdh-note warn" role="status">Pemeriksaan {issueTarget.issue.no}: {issueTarget.issue.check}. {issueTarget.issue.detail}<button type="button" onClick={()=>setIssueTarget(null)}>Tutup petunjuk</button></div>}
        {active==="calendar"&&<CalendarPanel selectedDate={selectedDate} setSelectedDate={setSelectedDate} effectiveDates={effectiveDates} calendarItems={calendarItems} onOpenDaily={()=>setActive("daily")} onOpenMaster={()=>setActive("service-days")}/>} 
        {active==="service-days"&&<ServiceDaysPanel site={site} effectiveDates={effectiveDates} monthKey={effectiveMonth} setMonthKey={(m)=>{setEffectiveMonth(m);loadEffective(site,m).catch((e)=>flash(e.message,"error"));}} onSave={saveEffective} busy={busy}/>}
        {active==="masters"&&<MasterPanel site={site} masters={masters} setMasters={setMasters} api={lpdhApi} onSaved={flash} onReload={reloadMasterTargets} issueTarget={issueTarget}/>}
        {active==="daily"&&(busy ? <div role="status">Memuat data tanggal ini…</div> : <DailyPanel dailySaved={dailySaved} onValidated={data=>{setDaily(data);setSavedDaily(JSON.stringify(data));}} site={site} serviceDate={selectedDate} masters={masters} daily={daily} setDaily={data=>setDaily({...data,_reviewValidated:false})} finalPlan={finalPlan} preview={preview} api={lpdhApi} onSaved={flash} issueTarget={issueTarget} onPreview={async(data)=>{await refreshPreview(site,selectedDate,data);await loadCalendar(site,monthKeyFromDate(selectedDate));}}/>)}
        {active==="documents"&&<DocumentWorkspace searchable site={site} serviceDate={selectedDate} onDateChange={setSelectedDate} onOpenDaily={()=>setActive("daily")} onRoutineDaily={async(result)=>{
          if(result.targetDailyStatus==="GENERATED") throw new Error("LPDH tanggal ini sudah digenerate. Buka Data Harian dan simpan sebagai draft dahulu, atau tarik dokumen per bagian tanpa isian PM.");
          const next=applyRoutineDaily(daily,result,masters,selectedDate);
          const key=`${site}|${selectedDate}`;
          if(viewContext.current!==key) throw new Error("Tanggal aktif berubah; tarik kembali untuk tanggal yang dipilih.");
          await lpdhApi.saveDaily(site,selectedDate,next,"DRAFT",{require_editable:true,expected_revision:result.targetDailyRevision});
          if(viewContext.current!==key) return;
          setDaily(next);
          flash(`Isian PM dari ${result.sourceDate} tersimpan sebagai draft; periksa realisasi hari ini. Bukti dan pembayaran lama tidak disalin.`);
        }} onFinalized={async()=>{await loadDaily();await refreshPreview();await loadCalendar(site,monthKeyFromDate(selectedDate));}}/>}
        {active==="review"&&!dailySaved&&<div className="lpdh-note warn" role="alert">Insentif Review masih Rp0. Klik Simpan &amp; Validasi di Data Harian agar nilai masuk ke Review. <button type="button" onClick={()=>setActive("daily")}>Buka Data Harian</button></div>}
        {active==="review"&&<ReviewPanel site={site} onApprovalSaved={async()=>{await loadDaily();await refreshPreview();}} masters={masters} daily={reviewDaily} preview={reviewPreview} serviceDate={selectedDate} referenceRows={referenceRows} activeSheet={activeSheet} setActiveSheet={setActiveSheet} onOpenIssue={openIssue}/>}
        {active==="generate"&&<GeneratePanel site={site} serviceDate={selectedDate} preview={preview} history={history} onRefresh={()=>refreshPreview()} onGenerate={generate} busy={busy} finalPlan={finalPlan} onOpenIssue={openIssue}/>}
      </section>
    </div>
  </main>;
}

