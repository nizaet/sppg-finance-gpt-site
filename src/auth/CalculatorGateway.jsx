import React from "react";
import { Calculator, ExternalLink, ShieldCheck } from "lucide-react";

const LABELS = {
  MAJA: "Kalkulator SPPG Maja",
  CEMPLANG: "Kalkulator SPPG Cemplang",
};

function CalculatorCard({ site, url }) {
  const ready = Boolean(String(url || "").trim());
  return (
    <section style={{
      background: "#fff", border: "1px solid #d7e2dc", borderRadius: 16,
      padding: 24, maxWidth: 520, width: "100%", boxShadow: "0 12px 30px rgba(15,61,46,.08)"
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ width: 44, height: 44, borderRadius: 12, display: "grid", placeItems: "center", background: "#e8f5ee", color: "#0f5138" }}>
          <Calculator size={22} />
        </div>
        <div>
          <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: ".08em", color: "#28705a" }}>{site}</div>
          <h2 style={{ margin: "2px 0 0", fontSize: 22 }}>{LABELS[site]}</h2>
        </div>
      </div>
      <p style={{ color: "#5d6b65", lineHeight: 1.5 }}>
        Akun {site} hanya memiliki akses ke kalkulator dapur ini. Pusat Operasional dan aplikasi Akuntan hanya untuk OWNER.
      </p>
      {ready ? (
        <button
          type="button"
          onClick={() => window.location.assign(url)}
          style={{ border: 0, borderRadius: 10, padding: "12px 16px", background: "#0f5138", color: "white", fontWeight: 800, cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 8 }}
        >
          <ExternalLink size={16} /> Buka {LABELS[site]}
        </button>
      ) : (
        <div style={{ padding: 14, borderRadius: 10, background: "#fff8e6", color: "#805d00", border: "1px solid #f2d58b" }}>
          URL kalkulator {site} belum diisi di Railway. OWNER perlu mengisi <strong>SPPG_{site}_CALCULATOR_URL</strong>.
        </div>
      )}
    </section>
  );
}

export default function CalculatorGateway({ role, config }) {
  const normalizedRole = String(role || "").toUpperCase();
  const sites = normalizedRole === "OWNER" ? ["MAJA", "CEMPLANG"] : [normalizedRole];
  return (
    <main style={{ minHeight: "calc(100vh - 52px)", background: "#f3f7f4", padding: 32 }}>
      <div style={{ maxWidth: 1120, margin: "0 auto" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 24, color: "#0f5138" }}>
          <ShieldCheck size={20} />
          <strong>Akses Kalkulator SPPG</strong>
        </div>
        <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
          {sites.filter((x) => LABELS[x]).map((site) => (
            <CalculatorCard key={site} site={site} url={config?.calculatorUrls?.[site]} />
          ))}
        </div>
      </div>
    </main>
  );
}
