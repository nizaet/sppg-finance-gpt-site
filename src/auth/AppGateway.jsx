import React from "react";
import { Calculator, FileSpreadsheet, LogOut } from "lucide-react";

const SITE_LABELS = { MAJA: "Maja", CEMPLANG: "Cemplang" };

function ChoiceCard({ icon, eyebrow, title, description, actionLabel, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        width: "100%",
        textAlign: "left",
        border: "1px solid #d7e2dc",
        borderRadius: 18,
        background: "#ffffff",
        padding: 24,
        cursor: "pointer",
        boxShadow: "0 12px 30px rgba(15,61,46,.07)",
        color: "#173128",
      }}
    >
      <div style={{ width: 46, height: 46, borderRadius: 13, display: "grid", placeItems: "center", background: "#e8f5ee", color: "#0f5138", marginBottom: 18 }}>
        {icon}
      </div>
      <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: ".08em", color: "#28705a" }}>{eyebrow}</div>
      <h2 style={{ margin: "6px 0 8px", fontSize: 22 }}>{title}</h2>
      <p style={{ margin: 0, color: "#5d6b65", lineHeight: 1.55 }}>{description}</p>
      <div style={{ marginTop: 18, fontWeight: 800, color: "#0f5138" }}>{actionLabel} →</div>
    </button>
  );
}

export default function AppGateway({ role, config, onLogout }) {
  const site = String(role || "").toUpperCase();
  const label = SITE_LABELS[site] || site;

  const openCalculator = () => {
    const url = config?.calculatorUrls?.[site] || `/dapur/${site.toLowerCase()}`;
    window.location.assign(url);
  };

  const openLpdh = () => {
    window.location.assign("/lpdh");
  };

  return (
    <main style={{ minHeight: "100vh", background: "#f3f7f4", padding: "32px 20px", fontFamily: "Inter, system-ui, sans-serif" }}>
      <div style={{ maxWidth: 980, margin: "0 auto" }}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap", marginBottom: 26 }}>
          <div>
            <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: ".08em", color: "#28705a" }}>SPPG {site}</div>
            <h1 style={{ margin: "5px 0 7px", color: "#173128", fontSize: "clamp(26px, 5vw, 38px)" }}>Pilih aplikasi</h1>
            <p style={{ margin: 0, color: "#5d6b65" }}>Login {label} yang sama dipakai untuk Kalkulator dan administrasi LPDH.</p>
          </div>
          <button
            type="button"
            onClick={onLogout}
            style={{ border: "1px solid #d7e2dc", borderRadius: 10, background: "#fff", padding: "10px 14px", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 7, color: "#6c2e2e", fontWeight: 700 }}
          >
            <LogOut size={16} /> Keluar
          </button>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 18 }}>
          <ChoiceCard
            icon={<Calculator size={23} />}
            eyebrow="PERENCANAAN"
            title="Kalkulator Menu"
            description="Buka kalkulator dapur yang sudah berjalan untuk perencanaan menu, bahan, kuantitas, harga, dan realisasi."
            actionLabel="Buka Kalkulator"
            onClick={openCalculator}
          />
          <ChoiceCard
            icon={<FileSpreadsheet size={23} />}
            eyebrow="ADMINISTRASI"
            title="LPDH & Administrasi"
            description="Kelola master penerima, relawan, operasional, invoice, kontrol pagu, bukti, dan generator Excel LPDH."
            actionLabel="Buka LPDH"
            onClick={openLpdh}
          />
        </div>
      </div>
    </main>
  );
}
