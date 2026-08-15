import React, { useEffect, useMemo, useState } from "react";
import { Calculator, ClipboardCopy, MessageCircle, RefreshCw } from "lucide-react";
import { operationsApi } from "./apiClient";

const money = (v) => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(Number(v || 0));
const qty = (v) => Number(v || 0).toLocaleString("id-ID", { maximumFractionDigits: 4 });
const CLOSED = new Set(["PAID", "RECONCILED", "CLOSED", "CANCELLED", "CANCELED"]);
const VENDORS = ["HOLIL", "WIKIAN", "HAJI_BADRI", "RUMAH_DUTA_PANGAN", "HERU", "DEDE", "KOPERASI"];

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  document.body.removeChild(area);
}

export default function OperationsPayments({ fixedSite = "" }) {
  const [site, setSite] = useState(fixedSite || "");
  const [payables, setPayables] = useState([]);
  const [payments, setPayments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [invoiceVendor, setInvoiceVendor] = useState("HOLIL");
  const [invoiceDateLabel, setInvoiceDateLabel] = useState(new Date().toISOString().slice(0, 10));
  const [invoiceText, setInvoiceText] = useState("");
  const [invoicePreview, setInvoicePreview] = useState(null);
  const [checkingInvoice, setCheckingInvoice] = useState(false);
  const [actionMessage, setActionMessage] = useState("");

  useEffect(() => {
    if (fixedSite && site !== fixedSite) setSite(fixedSite);
  }, [fixedSite, site]);

  const activeSite = fixedSite || site;

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const [payableData, paymentData] = await Promise.all([
        operationsApi.getVendorPayables({ site: activeSite }),
        operationsApi.getVendorPayments({ site: activeSite }),
      ]);
      setPayables(payableData?.items || []);
      setPayments(paymentData?.items || []);
    } catch (err) {
      setError(err.message || "Gagal mengambil invoice/pembayaran vendor");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [activeSite]);

  const outstanding = useMemo(
    () => payables.filter((x) => !CLOSED.has(String(x.payable_status || "UNPAID").toUpperCase())),
    [payables]
  );
  const outstandingTotal = useMemo(
    () => outstanding.reduce((sum, x) => sum + Number(x.net_amount || 0), 0),
    [outstanding]
  );

  const checkInvoice = async () => {
    if (!activeSite || !invoiceText.trim()) return;
    setCheckingInvoice(true);
    setError("");
    setActionMessage("");
    setInvoicePreview(null);
    try {
      const data = await operationsApi.parseVendorInvoice({
        site: activeSite,
        vendor_code: invoiceVendor,
        invoice_date_label: invoiceDateLabel,
        text: invoiceText,
      });
      setInvoicePreview(data);
    } catch (err) {
      setError(err.message || "Gagal memeriksa invoice vendor");
    } finally {
      setCheckingInvoice(false);
    }
  };

  const copyPaymentDraft = async () => {
    const text = invoicePreview?.paymentDraft || "";
    if (!text) return;
    await copyText(text);
    setActionMessage("Laporan pembayaran sudah disalin. Tinggal paste ke WhatsApp atau arsip manual.");
  };

  const openPaymentDraftWhatsApp = () => {
    const text = invoicePreview?.paymentDraft || "";
    if (!text) return;
    window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank", "noopener,noreferrer");
    setActionMessage("WhatsApp dibuka dengan laporan pembayaran siap diteruskan. Pilih tujuan yang benar sebelum kirim.");
  };

  return (
    <div className="ops-domain-stack">
      <section className="ops-module">
        <div className="ops-module-header">
          <div>
            <span className="ops-kicker">CEK INVOICE MANUAL</span>
            <h3>Tempel Invoice Vendor & Cek Aritmatika</h3>
            <p>Mode ini hanya membaca teks yang Anda tempel. Sistem memeriksa qty × harga, total baris, total bruto, rijek/potongan dan netto. Tidak otomatis menandai lunas atau membuat transaksi keuangan.</p>
          </div>
        </div>

        <div className="ops-form-grid">
          <label>Site<select value={activeSite} disabled={Boolean(fixedSite)} onChange={(e) => setSite(e.target.value)}><option value="">Pilih site</option><option value="MAJA">Maja</option><option value="CEMPLANG">Cemplang</option></select></label>
          <label>Vendor<select value={invoiceVendor} onChange={(e) => setInvoiceVendor(e.target.value)}>{VENDORS.map((v) => <option key={v} value={v}>{v}</option>)}</select></label>
          <label>Tanggal Tagihan<input type="text" value={invoiceDateLabel} onChange={(e) => setInvoiceDateLabel(e.target.value)} placeholder="10 Agustus 2026" /></label>
        </div>
        <textarea
          className="ops-chat-input"
          rows={9}
          value={invoiceText}
          onChange={(e) => setInvoiceText(e.target.value)}
          placeholder={'Contoh:\nWortel 79x9500=750.500\nJeruk Medan 165x14000=2.310.000\nTotal Rp. 3.060.500\nriject jeruk 6kg'}
        />
        <div className="ops-chat-actions">
          <button type="button" onClick={checkInvoice} disabled={checkingInvoice || !activeSite || !invoiceText.trim()}><Calculator size={15} /> {checkingInvoice ? "Menghitung..." : "Cek Invoice"}</button>
        </div>

        {actionMessage && <div className="ops-success">{actionMessage}</div>}
        {invoicePreview && (
          <div className="ops-parse-result">
            <div><Calculator size={16} /><strong>Hasil cek invoice</strong></div>
            <div className="ops-summary-strip">
              <span>Total tertulis <strong>{invoicePreview.declaredTotal == null ? "-" : money(invoicePreview.declaredTotal)}</strong></span>
              <span>Hasil hitung bruto <strong>{money(invoicePreview.grossAmount)}</strong></span>
              <span>Potongan rijek <strong>{money(invoicePreview.rejectDeduction)}</strong></span>
              <span>Netto dibayar <strong>{money(invoicePreview.netAmount)}</strong></span>
              <span>Status <strong>{invoicePreview.canCommit ? "ARITMATIKA OK" : "PERLU CEK"}</strong></span>
            </div>
            {(invoicePreview.warnings || []).length > 0 && (
              <div className="ops-error">{invoicePreview.warnings.map((w, i) => <div key={i}>• {w}</div>)}</div>
            )}
            <div className="ops-table-wrap">
              <table className="ops-table">
                <thead><tr><th>Item</th><th>Qty Invoice</th><th>Harga Vendor</th><th>Total Tertulis</th><th>Hasil Hitung</th><th>Rijek</th><th>Netto Baris</th><th>Cek</th></tr></thead>
                <tbody>
                  {(invoicePreview.items || []).map((item, index) => (
                    <tr key={`${item.item_name}-${index}`}>
                      <td><strong>{item.item_name}</strong><div className="ops-muted">{item.reported_item_name}</div></td>
                      <td>{qty(item.invoiced_qty)} {item.unit || ""}</td>
                      <td>{money(item.vendor_cost_price)}</td>
                      <td>{money(item.declared_line_total)}</td>
                      <td>{money(item.computed_line_total)}</td>
                      <td>{qty(item.rejected_qty)} {item.unit || ""}<div className="ops-muted">{money(item.reject_amount)}</div></td>
                      <td><strong>{money(item.net_line_total)}</strong></td>
                      <td>{item.line_total_matches ? "✓" : "⚠"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="ops-row-actions">
              <button type="button" onClick={copyPaymentDraft}><ClipboardCopy size={14} /> Copy Laporan Pembayaran</button>
              <button type="button" onClick={openPaymentDraftWhatsApp}><MessageCircle size={14} /> Buka di WhatsApp</button>
            </div>
            <div className="ops-muted">Laporan ini masih rancangan pembayaran. Status PAID hanya boleh berubah setelah ada bukti transfer/pembayaran.</div>
          </div>
        )}
      </section>

      <section className="ops-module">
        <div className="ops-module-header">
          <div>
            <span className="ops-kicker">INVOICE / PAYABLE</span>
            <h3>Tagihan Vendor Tercatat</h3>
            <p>Invoice adalah kewajiban. Bruto, reject, netto dan status payable tetap terpisah dari bukti pembayaran.</p>
          </div>
          <div className="ops-inline-controls">
            <select value={activeSite} disabled={Boolean(fixedSite)} onChange={(e) => setSite(e.target.value)}><option value="">Semua site</option><option value="MAJA">Maja</option><option value="CEMPLANG">Cemplang</option></select>
            <button type="button" onClick={load} disabled={loading}><RefreshCw size={15} /> Refresh</button>
          </div>
        </div>
        {error && <div className="ops-error">{error}</div>}
        <div className="ops-summary-strip">
          <span>Outstanding <strong>{outstanding.length}</strong></span>
          <span>Total netto <strong>{money(outstandingTotal)}</strong></span>
        </div>
        <div className="ops-table-wrap">
          <table className="ops-table">
            <thead><tr><th>Vendor</th><th>Site</th><th>PO</th><th>Invoice</th><th>Distribusi</th><th>Bruto</th><th>Reject</th><th>Netto</th><th>Jatuh Tempo</th><th>Status</th></tr></thead>
            <tbody>
              {outstanding.map((item) => (
                <tr key={item.vendor_invoice_id}>
                  <td><strong>{item.vendor_code}</strong></td>
                  <td>{item.site || "-"}</td>
                  <td>{item.po_code || "-"}</td>
                  <td>{item.invoice_number || "-"}</td>
                  <td>{item.distribution_date || "-"}</td>
                  <td>{money(item.gross_amount)}</td>
                  <td>{money(item.reject_deduction)}</td>
                  <td><strong>{money(item.net_amount)}</strong></td>
                  <td>{item.due_date || "Belum ditetapkan"}</td>
                  <td>{item.payable_status || "UNPAID"}</td>
                </tr>
              ))}
              {!loading && outstanding.length === 0 && <tr><td colSpan="10" className="ops-empty-cell">Tidak ada tagihan vendor outstanding.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="ops-module">
        <div className="ops-module-header">
          <div>
            <span className="ops-kicker">PAYMENT EVIDENCE</span>
            <h3>Riwayat Pembayaran</h3>
            <p>Baris di bawah berasal dari record pembayaran aplikasi maupun GPTS. Adanya invoice atau permintaan bayar tidak dianggap sebagai pembayaran.</p>
          </div>
        </div>
        <div className="ops-table-wrap">
          <table className="ops-table">
            <thead><tr><th>Vendor</th><th>Site</th><th>Invoice</th><th>Nilai Invoice</th><th>Dibayar</th><th>Tanggal Bayar</th><th>Sumber</th><th>Status</th></tr></thead>
            <tbody>
              {payments.map((item) => (
                <tr key={item.id}>
                  <td><strong>{item.vendor_code}</strong></td>
                  <td>{item.site || "-"}</td>
                  <td>{item.invoice_number || "-"}</td>
                  <td>{money(item.net_amount)}</td>
                  <td><strong>{money(item.amount)}</strong></td>
                  <td>{item.paid_at || "-"}</td>
                  <td>{item.payment_source || "-"}</td>
                  <td>{item.payment_status}</td>
                </tr>
              ))}
              {!loading && payments.length === 0 && <tr><td colSpan="8" className="ops-empty-cell">Belum ada bukti pembayaran vendor yang tercatat.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
