import React, { useMemo, useState } from "react";
import {
  Calculator,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  Database,
  FileCheck2,
  FileSpreadsheet,
  Gauge,
  ReceiptText,
  School,
  Users,
  Wrench,
} from "lucide-react";
import "./lpdh.css";

const MODULES = [
  { id: "calculator", label: "Data Final Kalkulator", icon: Calculator, note: "Tarik hanya data perencanaan yang sudah berstatus FINAL." },
  { id: "beneficiaries", label: "Master Penerima", icon: School, note: "Sekolah dan Posyandu beserta kelompok sasaran, PIC, dan target PM." },
  { id: "volunteers", label: "Master Relawan", icon: Users, note: "Data relawan, tugas, status, dan tarif dasar." },
  { id: "operational", label: "Master Operasional", icon: Wrench, note: "Gas, listrik, air, APD, kebersihan, internet, ATK, dan item lainnya." },
  { id: "daily", label: "Operasional Harian", icon: Database, note: "Input jumlah aktual, harga, transaksi, dan kebutuhan bukti." },
  { id: "invoice", label: "Invoice & Bukti", icon: ReceiptText, note: "Preview dan siapkan invoice sebelum masuk ke LPDH." },
  { id: "ceiling", label: "Simulasi Pagu", icon: Gauge, note: "Pantau biaya bahan per porsi dan operasional per PM sebelum final." },
  { id: "generate", label: "Generate LPDH", icon: FileSpreadsheet, note: "Isi template resmi dengan rumus tetap hidup." },
];

const SITE_LABELS = { MAJA: "Maja", CEMPLANG: "Cemplang" };
const DATE_MODULES = new Set(["calculator", "daily", "invoice", "ceiling", "generate"]);

function todayJakarta() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Jakarta",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
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

function formatDateLabel(value) {
  const { year, month, day } = parseDateKey(value);
  if (!year || !month || !day) return value;
  return new Intl.DateTimeFormat("id-ID", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "Asia/Jakarta",
  }).format(new Date(Date.UTC(year, month - 1, day, 6)));
}

function CalendarPanel({ selectedDate, setSelectedDate, onOpenDaily }) {
  const [monthKey, setMonthKey] = useState(monthKeyFromDate(selectedDate));
  const [year, month] = monthKey.split("-").map(Number);
  const firstWeekday = new Date(year, month - 1, 1).getDay();
  const daysInMonth = new Date(year, month, 0).getDate();
  const monthLabel = new Intl.DateTimeFormat("id-ID", {
    month: "long",
    year: "numeric",
    timeZone: "Asia/Jakarta",
  }).format(new Date(Date.UTC(year, month - 1, 1, 6)));
  const today = todayJakarta();
  const cells = Array.from({ length: firstWeekday + daysInMonth }, (_, index) => (
    index < firstWeekday ? null : index - firstWeekday + 1
  ));

  const pickDay = (day) => {
    if (!day) return;
    setSelectedDate(`${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`);
  };

  return (
    <section className="lpdh-calendar-wrap">
      <div className="lpdh-calendar-toolbar">
        <div>
          <div className="lpdh-kicker">LAPORAN HARIAN</div>
          <h2>Kalender LPDH</h2>
          <p>Pilih tanggal pelayanan. Semua modul transaksi harian akan mengikuti tanggal ini.</p>
        </div>
        <div className="lpdh-calendar-month-nav">
          <button type="button" aria-label="Bulan sebelumnya" onClick={() => setMonthKey(shiftMonth(monthKey, -1))}><ChevronLeft size={18} /></button>
          <strong>{monthLabel}</strong>
          <button type="button" aria-label="Bulan berikutnya" onClick={() => setMonthKey(shiftMonth(monthKey, 1))}><ChevronRight size={18} /></button>
        </div>
      </div>

      <div className="lpdh-calendar-weekdays" aria-hidden="true">
        {["Min", "Sen", "Sel", "Rab", "Kam", "Jum", "Sab"].map((day) => <span key={day}>{day}</span>)}
      </div>
      <div className="lpdh-calendar-grid">
        {cells.map((day, index) => {
          if (!day) return <span key={`blank-${index}`} className="lpdh-calendar-empty" />;
          const dateKey = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
          const selected = dateKey === selectedDate;
          const isToday = dateKey === today;
          return (
            <button
              key={dateKey}
              type="button"
              className={`lpdh-calendar-day${selected ? " selected" : ""}${isToday ? " today" : ""}`}
              onClick={() => pickDay(day)}
            >
              <span className="lpdh-calendar-day-number">{day}</span>
              <span className="lpdh-calendar-day-status">{isToday ? "Hari ini" : "Belum diisi"}</span>
            </button>
          );
        })}
      </div>

      <div className="lpdh-selected-date">
        <div>
          <span>Tanggal kerja aktif</span>
          <strong>{formatDateLabel(selectedDate)}</strong>
        </div>
        <button type="button" onClick={onOpenDaily}>Isi laporan tanggal ini</button>
      </div>

      <div className="lpdh-calendar-legend">
        <span><i className="empty" /> Belum diisi</span>
        <span><i className="draft" /> Draft</span>
        <span><i className="ready" /> Siap generate</span>
        <span><i className="done" /> Sudah generate</span>
      </div>
    </section>
  );
}

function ModulePanel({ module, selectedDate, site }) {
  const Icon = module.icon;
  return (
    <section className="lpdh-panel">
      <div className="lpdh-panel-icon"><Icon size={22} /></div>
      <div>
        <div className="lpdh-kicker">MODUL • {SITE_LABELS[site] || site}</div>
        <h2>{module.label}</h2>
        <p>{module.note}</p>
        {DATE_MODULES.has(module.id) && (
          <div className="lpdh-date-context">
            <CalendarDays size={16} />
            <span>{formatDateLabel(selectedDate)}</span>
          </div>
        )}
        <div className="lpdh-stage-note">
          <ClipboardCheck size={16} />
          <span>Kerangka modul sudah aktif. Koneksi data dan import Excel dipasang pada tahap berikutnya.</span>
        </div>
      </div>
    </section>
  );
}

export default function LpdhWorkspace({ role, onLogout }) {
  const accountRole = String(role || "").toUpperCase();
  const [site, setSite] = useState(accountRole === "OWNER" ? "MAJA" : accountRole);
  const [active, setActive] = useState("calendar");
  const [selectedDate, setSelectedDate] = useState(todayJakarta());
  const module = useMemo(() => MODULES.find((item) => item.id === active), [active]);

  return (
    <main className="lpdh-page">
      <header className="lpdh-header">
        <div>
          <div className="lpdh-kicker">{accountRole === "OWNER" ? "YAYASAN • " : ""}SPPG {site}</div>
          <h1>LPDH & Administrasi {SITE_LABELS[site] || site}</h1>
          <p>{accountRole === "OWNER" ? "Akun YAYASAN dapat memeriksa MAJA dan CEMPLANG dari workspace yang sama." : "Workspace awal untuk menyiapkan data sampai menjadi Excel LPDH."}</p>
          {accountRole === "OWNER" && (
            <div style={{ display: "flex", gap: 8, marginTop: 14, flexWrap: "wrap" }} aria-label="Pilih dapur LPDH">
              {["MAJA", "CEMPLANG"].map((item) => (
                <button
                  key={item}
                  type="button"
                  className={site === item ? "lpdh-site-button active" : "lpdh-site-button"}
                  onClick={() => { setSite(item); setActive("calendar"); }}
                >
                  {SITE_LABELS[item]}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="lpdh-header-actions">
          <button type="button" className="lpdh-secondary" onClick={() => window.location.assign("/")}>Pilih aplikasi</button>
          <button type="button" className="lpdh-danger" onClick={onLogout}>Keluar</button>
        </div>
      </header>

      <div className="lpdh-layout">
        <nav className="lpdh-nav" aria-label="Menu LPDH">
          <button type="button" className={active === "calendar" ? "active" : ""} onClick={() => setActive("calendar")}>
            <CalendarDays size={17} /> Kalender LPDH
          </button>
          <button type="button" className={active === "dashboard" ? "active" : ""} onClick={() => setActive("dashboard")}>
            <FileCheck2 size={17} /> Dashboard
          </button>
          {MODULES.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.id} type="button" className={active === item.id ? "active" : ""} onClick={() => setActive(item.id)}>
                <Icon size={17} /> {item.label}
              </button>
            );
          })}
        </nav>

        <section className="lpdh-content">
          {active === "calendar" ? (
            <CalendarPanel
              selectedDate={selectedDate}
              setSelectedDate={setSelectedDate}
              onOpenDaily={() => setActive("daily")}
            />
          ) : active === "dashboard" ? (
            <>
              <div className="lpdh-summary">
                <div>
                  <div className="lpdh-kicker">STATUS V1</div>
                  <h2>LPDH {SITE_LABELS[site] || site} • {formatDateLabel(selectedDate)}</h2>
                  <p>{accountRole === "OWNER" ? "Pilih Maja atau Cemplang di atas. Data masing-masing dapur tetap dipisahkan." : "Site mengikuti akun login. Data MAJA dan CEMPLANG tidak dicampur di tampilan ini."}</p>
                </div>
                <div className="lpdh-badge">Tahap 1</div>
              </div>

              <div className="lpdh-grid">
                {MODULES.map((item) => {
                  const Icon = item.icon;
                  return (
                    <button key={item.id} type="button" className="lpdh-card" onClick={() => setActive(item.id)}>
                      <span className="lpdh-card-icon"><Icon size={20} /></span>
                      <strong>{item.label}</strong>
                      <span>{item.note}</span>
                    </button>
                  );
                })}
              </div>
            </>
          ) : (
            <ModulePanel module={module} selectedDate={selectedDate} site={site} />
          )}
        </section>
      </div>
    </main>
  );
}
