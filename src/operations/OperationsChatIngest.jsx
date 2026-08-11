import React, { useState } from "react";
import { Send, Sparkles } from "lucide-react";
import { operationsApi } from "./apiClient";
import "./chat.css";

export default function OperationsChatIngest() {
  const [text, setText] = useState("");
  const [site, setSite] = useState("");
  const [vendor, setVendor] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    if (!text.trim()) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const data = await operationsApi.parseMessage({
        text,
        context_site: site || null,
        context_vendor: vendor || null,
        source_type: "MANUAL_CHAT",
        stage: true,
      });
      setResult(data);
    } catch (err) {
      setError(err.message || "Gagal memproses pesan");
    } finally {
      setLoading(false);
    }
  };

  const parsed = result?.parsed;

  return (
    <section className="ops-module">
      <div className="ops-module-header">
        <div>
          <span className="ops-kicker">CHAT → STAGING</span>
          <h3>Input Chat Operasional</h3>
          <p>Tempel pesan WhatsApp/chat. Parser mengklasifikasikan dulu; event masuk staging/review, bukan langsung ke ledger.</p>
        </div>
      </div>

      <div className="ops-form-grid">
        <label>Context Site<select value={site} onChange={(e) => setSite(e.target.value)}><option value="">Deteksi otomatis</option><option value="MAJA">Maja</option><option value="CEMPLANG">Cemplang</option></select></label>
        <label>Context Vendor<input value={vendor} onChange={(e) => setVendor(e.target.value.toUpperCase())} placeholder="HOLIL / WIKIAN / DEDE..." /></label>
      </div>

      <textarea className="ops-chat-input" value={text} onChange={(e) => setText(e.target.value)} placeholder="Contoh: Pak Holil untuk Maja besok wortel 80 kg..." rows={7} />
      <div className="ops-chat-actions"><button type="button" onClick={submit} disabled={loading || !text.trim()}><Send size={16} /> {loading ? "Memproses..." : "Parse & Masukkan Staging"}</button></div>

      {error && <div className="ops-error">{error}</div>}
      {parsed && (
        <div className="ops-parse-result">
          <div><Sparkles size={17} /><strong>{parsed.event_type}</strong></div>
          <dl>
            <dt>Site</dt><dd>{parsed.site || "Belum terdeteksi"}</dd>
            <dt>Vendor</dt><dd>{parsed.vendor || "Belum terdeteksi"}</dd>
            <dt>Confidence</dt><dd>{Math.round(Number(parsed.confidence || 0) * 100)}%</dd>
            <dt>Review</dt><dd>{parsed.requires_confirmation ? "Wajib review" : "Tidak wajib"}</dd>
            <dt>Staging ID</dt><dd>{result.eventId || "-"}</dd>
          </dl>
          <div className="ops-muted">Raw: {parsed.raw_text}</div>
        </div>
      )}
    </section>
  );
}
