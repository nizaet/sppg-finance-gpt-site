import React, { useEffect, useMemo, useState } from "react";
import { CheckCircle2, FileSearch, Upload, X } from "lucide-react";
import { readSessionToken } from "../auth/session.js";

const API_BASE = import.meta.env.VITE_SPPG_CORE_API_URL || "https://sppg-finance-gpt-site-production-5b7d.up.railway.app";
const money = (v) => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(Number(v || 0));

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.includes(",") ? result.split(",", 2)[1] : result);
    };
    reader.onerror = () => reject(reader.error || new Error("Gagal membaca file"));
    reader.readAsDataURL(file);
  });
}

async function postJson(path, body) {
  const token = readSessionToken();
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(`SPPG Core API ${response.status}: ${detail || response.statusText}`);
  }
  return response.json();
}

function toLocalInput(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function toIsoJakarta(value) {
  if (!value) return null;
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return `${value}:00+07:00`;
  return value;
}

export default function VendorPaymentEvidenceModal({ item, onClose, onSaved }) {
  const [file, setFile] = useState(null);
  const [contentBase64, setContentBase64] = useState("");
  const [reading, setReading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [warnings, setWarnings] = useState([]);
  const [amount, setAmount] = useState(String(Number(item?.net_amount || 0)));
  const [paidAt, setPaidAt] = useState("");
  const [referenceNumber, setReferenceNumber] = useState("");
  const [beneficiaryName, setBeneficiaryName] = useState("");
  const [beneficiaryAccount, setBeneficiaryAccount] = useState("");
  const [sourceAccount, setSourceAccount] = useState("");
  const [remarks, setRemarks] = useState("");
  const [confidence, setConfidence] = useState(null);

  const source = String(item?.site || "").toUpperCase() === "MAJA" ? "Mobile BCA" : String(item?.site || "").toUpperCase() === "CEMPLANG" ? "myBCA" : "BCA";
  const paidAmountMatches = useMemo(() => Math.abs(Number(amount || 0) - Number(item?.net_amount || 0)) < 0.01, [amount, item]);

  useEffect(() => {
    const esc = (event) => { if (event.key === "Escape" && !saving && !reading) onClose?.(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose, saving, reading]);

  const inspectFile = async (selected = file) => {
    if (!selected) return setError("Pilih screenshot/PDF bukti transfer terlebih dahulu.");
    setReading(true); setError(""); setWarnings([]);
    try {
      const encoded = selected === file && contentBase64 ? contentBase64 : await fileToBase64(selected);
      setContentBase64(encoded);
      const data = await postJson("/v1/vendor-payments/evidence/inspect", {
        vendor_invoice_id: Number(item.vendor_invoice_id),
        file_name: selected.name,
        mime_type: selected.type || "image/jpeg",
        content_base64: encoded,
      });
      setAmount(String(data.amount ?? item.net_amount ?? ""));
      setPaidAt(toLocalInput(data.paidAt));
      setReferenceNumber(data.referenceNumber || "");
      setBeneficiaryName(data.beneficiaryName || "");
      setBeneficiaryAccount(data.beneficiaryAccount || "");
      setSourceAccount(data.sourceAccount || "");
      setRemarks(data.remarks || "");
      setConfidence(data.confidence ?? null);
      setWarnings(data.warnings || []);
    } catch (e) {
      setError(e.message || "Gagal membaca bukti transfer");
    } finally {
      setReading(false);
    }
  };

  const chooseFile = async (event) => {
    const selected = event.target.files?.[0] || null;
    setFile(selected); setContentBase64(""); setError(""); setWarnings([]);
    if (selected) await inspectFile(selected);
  };

  const commit = async () => {
    if (!file) return setError("Upload bukti transfer terlebih dahulu.");
    if (Number(amount) <= 0) return setError("Nominal transfer harus lebih dari 0.");
    const encoded = contentBase64 || await fileToBase64(file);
    if (!paidAmountMatches && !window.confirm(`Nominal bukti ${money(amount)} berbeda dari netto invoice ${money(item.net_amount)}. Tetap simpan pembayaran ini?`)) return;
    setSaving(true); setError("");
    try {
      const result = await postJson("/v1/vendor-payments/evidence/commit", {
        vendor_invoice_id: Number(item.vendor_invoice_id),
        file_name: file.name,
        mime_type: file.type || "image/jpeg",
        content_base64: encoded,
        amount: Number(amount),
        paid_at: toIsoJakarta(paidAt),
        reference_number: referenceNumber.trim() || null,
        beneficiary_name: beneficiaryName.trim() || null,
        beneficiary_account: beneficiaryAccount.trim() || null,
        source_account: sourceAccount.trim() || null,
        remarks: remarks.trim() || null,
        actor: "operator-ui",
      });
      await onSaved?.(result);
    } catch (e) {
      setError(e.message || "Gagal menyimpan pembayaran");
    } finally {
      setSaving(false);
    }
  };

  if (!item) return null;
  return (
    <div role="dialog" aria-modal="true" style={{ position: "fixed", inset: 0, zIndex: 9999, background: "rgba(15,23,42,.55)", display: "grid", placeItems: "center", padding: 18 }} onMouseDown={(e) => { if (e.target === e.currentTarget && !saving && !reading) onClose?.(); }}>
      <div style={{ width: "min(760px,96vw)", maxHeight: "92vh", overflow: "auto", background: "var(--ops-surface,#fff)", color: "inherit", borderRadius: 16, boxShadow: "0 24px 70px rgba(0,0,0,.28)", padding: 18 }}>
        <div className="ops-module-header" style={{ marginBottom: 10 }}>
          <div><span className="ops-kicker">BUKTI TRANSFER VENDOR</span><h3 style={{ margin: "4px 0" }}>Bayar {item.vendor_code} · {item.site}</h3><p style={{ margin: 0 }}>Upload bukti. Sistem membaca nominal, tanggal, penerima, rekening dan referensi lalu arsip asli ke Google Drive.</p></div>
          <button type="button" onClick={onClose} disabled={saving || reading} title="Tutup"><X size={18} /></button>
        </div>

        <div className="ops-summary-strip">
          <span>Invoice <strong>{item.invoice_number || item.po_code || `#${item.vendor_invoice_id}`}</strong></span>
          <span>Netto <strong>{money(item.net_amount)}</strong></span>
          <span>Sumber <strong>{source}</strong></span>
        </div>

        <label style={{ display: "block", margin: "12px 0" }}>Bukti transfer
          <input type="file" accept="image/jpeg,image/png,image/webp,application/pdf" onChange={chooseFile} disabled={saving || reading} style={{ display: "block", marginTop: 6 }} />
        </label>
        {file && <div className="ops-row-actions" style={{ marginBottom: 12 }}><button type="button" onClick={() => inspectFile()} disabled={reading || saving}><FileSearch size={15} /> {reading ? "Sedang membaca…" : "Baca Ulang Bukti"}</button><span className="ops-muted">{file.name}</span></div>}
        {confidence != null && <div className="ops-muted">Keyakinan pembacaan AI: {Math.round(Number(confidence || 0) * 100)}%</div>}
        {warnings.length > 0 && <div className="ops-error" style={{ marginTop: 10 }}>{warnings.map((w, i) => <div key={i}>• {w}</div>)}</div>}
        {error && <div className="ops-error" style={{ marginTop: 10 }}>{error}</div>}

        <div className="ops-form-grid" style={{ marginTop: 14 }}>
          <label>Nominal transfer<input type="number" min="0" value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
          <label>Tanggal & jam<input type="datetime-local" value={paidAt} onChange={(e) => setPaidAt(e.target.value)} /></label>
          <label>Sumber pembayaran<input value={source} readOnly /></label>
          <label>No. referensi<input value={referenceNumber} onChange={(e) => setReferenceNumber(e.target.value)} placeholder="Reference No / kode transaksi" /></label>
          <label>Nama penerima<input value={beneficiaryName} onChange={(e) => setBeneficiaryName(e.target.value)} /></label>
          <label>Rekening penerima<input value={beneficiaryAccount} onChange={(e) => setBeneficiaryAccount(e.target.value)} /></label>
          <label>Rekening sumber<input value={sourceAccount} onChange={(e) => setSourceAccount(e.target.value)} placeholder="boleh masked" /></label>
          <label>Remarks<input value={remarks} onChange={(e) => setRemarks(e.target.value)} /></label>
        </div>

        <div className="ops-row-actions" style={{ justifyContent: "flex-end", marginTop: 16 }}>
          <button type="button" onClick={onClose} disabled={saving || reading}>Batal</button>
          <button type="button" className="ops-button-primary" onClick={commit} disabled={saving || reading || !file || Number(amount) <= 0}><Upload size={15} /> {saving ? "Menyimpan…" : "Simpan PAID + Bukti"}</button>
        </div>
        <div className="ops-muted" style={{ marginTop: 8 }}><CheckCircle2 size={13} style={{ verticalAlign: "middle" }} /> Setelah tersimpan, invoice berubah hijau dan bukti tertaut ke pembayaran.</div>
      </div>
    </div>
  );
}
