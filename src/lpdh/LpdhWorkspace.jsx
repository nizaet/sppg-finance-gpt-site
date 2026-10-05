import React, { useMemo, useState } from "react";
import {
  Calculator,
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

function ModulePanel({ module }) {
  const Icon = module.icon;
  return (
    <section className="lpdh-panel">
      <div className="lpdh-panel-icon"><Icon size={22} /></div>
      <div>
        <div className="lpdh-kicker">MODUL</div>
        <h2>{module.label}</h2>
        <p>{module.note}</p>
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
  const [active, setActive] = useState("dashboard");
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
                  onClick={() => { setSite(item); setActive("dashboard"); }}
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
          {active === "dashboard" ? (
            <>
              <div className="lpdh-summary">
                <div>
                  <div className="lpdh-kicker">STATUS V1</div>
                  <h2>Kerangka LPDH aktif untuk {SITE_LABELS[site] || site}</h2>
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
            <ModulePanel module={module} />
          )}
        </section>
      </div>
    </main>
  );
}
