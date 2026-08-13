import React, { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { operationsApi } from "./apiClient";

const money = (v) => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(Number(v || 0));
const CLOSED = new Set(["PAID", "RECONCILED", "CLOSED", "CANCELLED", "CANCELED"]);

export default function OperationsPayments({ fixedSite = "" }) {
  const [site, setSite] = useState(fixedSite || "");
  const [payables, setPayables] = useState([]);
  const [payments, setPayments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

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

  return (
    <div className="ops-domain-stack">
      <section className="ops-module">
        <div className="ops-module-header">
          <div>
            <span className="ops-kicker">INVOICE / PAYABLE</span>
            <h3>Tagihan Vendor</h3>
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
            <p>Baris di bawah hanya berasal dari record pembayaran. Adanya invoice atau permintaan bayar tidak dianggap sebagai pembayaran.</p>
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
