import React, { useEffect, useMemo, useState } from "react";
import { Calculator, CheckCircle2, ClipboardCopy, MessageCircle, RefreshCw } from "lucide-react";
import { operationsApi } from "./apiClient";
import VendorPaymentEvidenceModal from "./VendorPaymentEvidenceModal.jsx";

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
  const [vendorContacts, setVendorContacts] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [invoiceVendor, setInvoiceVendor] = useState("HOLIL");
  const [invoiceDateLabel, setInvoiceDateLabel] = useState(new Date().toISOString().slice(0, 10));
  const [invoiceText, setInvoiceText] = useState("");
  const [invoicePreview, setInvoicePreview] = useState(null);
  const [checkingInvoice, setCheckingInvoice] = useState(false);
  const [actionMessage, setActionMessage] = useState("");
  const [paymentInvoiceId, setPaymentInvoiceId] = useState("");
  const [paymentAmount, setPaymentAmount] = useState("");
  const [paymentSource, setPaymentSource] = useState("");
  const [paymentReference, setPaymentReference] = useState("");
  const [paymentEvidenceUri, setPaymentEvidenceUri] = useState("");
  const [paymentPreview, setPaymentPreview] = useState(null);
  const [savingPayment, setSavingPayment] = useState(false);
  const [editingPayable, setEditingPayable] = useState(null);
  const [payableEdit, setPayableEdit] = useState(null);
  const [savingPayableEdit, setSavingPayableEdit] = useState(false);
  const [paymentModalItem, setPaymentModalItem] = useState(null); // NATIVE_VENDOR_PAYMENT_EVIDENCE

  useEffect(() => {
    if (fixedSite && site !== fixedSite) setSite(fixedSite);
  }, [fixedSite, site]);

  const activeSite = fixedSite || site;

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const [payableData, paymentData, vendorData] = await Promise.all([
        operationsApi.getVendorPayables({ site: activeSite }),
        operationsApi.getVendorPayments({ site: activeSite }),
        operationsApi.getReferenceVendors(activeSite),
      ]);
      setPayables(payableData?.items || []);
      setPayments(paymentData?.items || []);
      const contacts = {};
      (vendorData?.items || []).forEach((item) => {
        if (item?.code) contacts[String(item.code).toUpperCase()] = String(item.metadata?.whatsapp_phone || "");
      });
      setVendorContacts(contacts);
    } catch (err) {
      setError(err.message || "Gagal mengambil invoice/pembayaran vendor");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [activeSite]);

  const outstanding = useMemo(
    () => payables.filter((x) => !CLOSED.has(String(x.payable_status || "UNPAID").toUpperCase()) && Number(x.net_amount || 0) > 0.01),
    [payables]
  );
  const noPaymentRequired = useMemo(() => payables.filter((x) => !CLOSED.has(String(x.payable_status || "UNPAID").toUpperCase()) && Number(x.net_amount || 0) <= 0.01), [payables]);
  const outstandingTotal = useMemo(
    () => outstanding.reduce((sum, x) => sum + Number(x.net_amount || 0), 0),
    [outstanding]
  );

  useEffect(() => {
    if (!paymentInvoiceId && outstanding.length) {
      setPaymentInvoiceId(String(outstanding[0].vendor_invoice_id));
      setPaymentAmount(String(Number(outstanding[0].net_amount || 0)));
    }
  }, [outstanding, paymentInvoiceId]);

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
    const phone = vendorContacts[invoiceVendor] || "";
    if (!phone) {
      setError(`Nomor WhatsApp ${invoiceVendor} belum tersimpan. Isi dahulu di menu Vendor & Lead Time.`);
      return;
    }
    window.open(`https://wa.me/${phone}?text=${encodeURIComponent(text)}`, "_blank", "noopener,noreferrer");
    setActionMessage(`WhatsApp ${invoiceVendor} dibuka dengan laporan pembayaran yang sudah dikoreksi.`);
  };

  const selectedPayable = outstanding.find((item) => String(item.vendor_invoice_id) === String(paymentInvoiceId));

  const selectPayable = (value) => {
    setPaymentInvoiceId(value);
    const payable = outstanding.find((item) => String(item.vendor_invoice_id) === String(value));
    setPaymentAmount(payable ? String(Number(payable.net_amount || 0)) : "");
    setPaymentPreview(null);
  };

  const paymentPayload = () => ({
    vendor_invoice_id: Number(paymentInvoiceId),
    amount: Number(paymentAmount),
    payment_source: paymentSource.trim() || null,
    reference_number: paymentReference.trim() || null,
    evidence_uri: paymentEvidenceUri.trim() || null,
    source_external_id: paymentReference.trim() ? `payment:${paymentReference.trim()}` : null,
  });

  const previewPayment = async () => {
    if (!paymentInvoiceId || Number(paymentAmount) <= 0) return;
    setSavingPayment(true);
    setError("");
    setActionMessage("");
    try {
      const preview = await operationsApi.confirmVendorPayment(paymentPayload(), false);
      setPaymentPreview(preview);
    } catch (err) {
      setError(err.message || "Gagal memeriksa pembayaran");
      setPaymentPreview(null);
    } finally {
      setSavingPayment(false);
    }
  };

  const commitPayment = async () => {
    if (!paymentPreview?.canCommit) return;
    if (!paymentReference.trim() && !paymentEvidenceUri.trim()) {
      setError("Isi minimal nomor referensi transfer atau tautan bukti pembayaran sebelum konfirmasi.");
      return;
    }
    if (!window.confirm(`Catat pembayaran ${selectedPayable?.vendor_code || "vendor"} sebesar ${money(paymentPreview.paymentAmount)}?\n\nStatus invoice akan berubah menjadi ${paymentPreview.payableStatusAfter}.`)) return;
    setSavingPayment(true);
    setError("");
    setActionMessage("");
    try {
      const result = await operationsApi.confirmVendorPayment(paymentPayload(), true);
      setActionMessage(`Pembayaran tercatat. Status tagihan: ${result.payableStatusAfter}. Pencatatan ini belum otomatis membuat pengeluaran Akuntan.`);
      setPaymentPreview(null);
      setPaymentReference("");
      setPaymentEvidenceUri("");
      await load();
      setPaymentInvoiceId("");
      setPaymentAmount("");
    } catch (err) {
      setError(err.message || "Gagal mencatat pembayaran");
    } finally {
      setSavingPayment(false);
    }
  };

  const openPayableEdit = (item) => {
    setEditingPayable(item);
    setPayableEdit({ invoice_number: item.invoice_number || "", invoice_date: item.invoice_date || "", due_date: item.due_date || "", gross_amount: String(Number(item.gross_amount || 0)), reject_deduction: String(Number(item.reject_deduction || 0)), correction_note: "" });
    setError("");
  };
  const savePayableEdit = async () => {
    if (!editingPayable || !payableEdit?.correction_note.trim()) return setError("Isi alasan koreksi agar jejak tagihan tetap jelas.");
    setSavingPayableEdit(true); setError("");
    try {
      await operationsApi.correctVendorPayable(editingPayable.vendor_invoice_id, { ...payableEdit, gross_amount: Number(payableEdit.gross_amount || 0), reject_deduction: Number(payableEdit.reject_deduction || 0), invoice_number: payableEdit.invoice_number.trim() || null, invoice_date: payableEdit.invoice_date || null, due_date: payableEdit.due_date || null });
      setActionMessage("Tagihan vendor dikoreksi. PO dan penerimaan barang tidak diubah.");
      setEditingPayable(null); setPayableEdit(null); await load();
    } catch (err) { setError(err.message || "Gagal mengoreksi tagihan vendor"); }
    finally { setSavingPayableEdit(false); }
  };
  const deleteRejectedPayable = async (item) => {
    if (!window.confirm(`Hapus tagihan reject/netto Rp0 ${item.vendor_code} · ${item.po_code || `#${item.vendor_invoice_id}`}?\n\nPO dan penerimaan barang tetap ada.`)) return;
    setSavingPayableEdit(true); setError("");
    try {
      await operationsApi.deleteRejectedVendorPayable(item.vendor_invoice_id);
      setActionMessage("Tagihan reject dihapus. PO dan receipt tidak berubah.");
      if (editingPayable?.vendor_invoice_id === item.vendor_invoice_id) { setEditingPayable(null); setPayableEdit(null); }
      await load();
    } catch (err) { setError(err.message || "Gagal menghapus tagihan reject"); }
    finally { setSavingPayableEdit(false); }
  };

  return (
    <div className="ops-domain-stack">
      {paymentModalItem && <VendorPaymentEvidenceModal
        item={paymentModalItem}
        onClose={() => setPaymentModalItem(null)}
        onSaved={async (result) => {
          setPaymentModalItem(null);
          setActionMessage(`Pembayaran tersimpan. Status tagihan: ${result.payableStatusAfter || result.reconciliationStatus || "PAID"}. Bukti sudah masuk Google Drive.`);
          await load();
        }}
      />}
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
            <span className="ops-kicker">TRANSFER + BUKTI</span>
            <h3>Catat Pembayaran Vendor</h3>
            <p>Pilih tagihan yang sudah direkonsiliasi, masukkan nilai transfer dan bukti. Sistem selalu preview sebelum mengubah status invoice. Bukti dapat berupa tautan Drive/foto yang sudah Anda simpan.</p>
          </div>
        </div>
        <div className="ops-form-grid">
          <label>Tagihan<select value={paymentInvoiceId} onChange={(e) => selectPayable(e.target.value)}><option value="">Pilih tagihan</option>{outstanding.map((item) => <option key={item.vendor_invoice_id} value={item.vendor_invoice_id}>{item.vendor_code} · {item.invoice_number || item.po_code || `#${item.vendor_invoice_id}`} · {money(item.net_amount)}</option>)}</select></label>
          <label>Nilai transfer<input type="number" min="0" step="1" value={paymentAmount} onChange={(e) => { setPaymentAmount(e.target.value); setPaymentPreview(null); }} /></label>
          <label>Sumber pembayaran<input type="text" value={paymentSource} onChange={(e) => setPaymentSource(e.target.value)} placeholder="contoh: BCA Operasional / Kas" /></label>
          <label>No. referensi transfer<input type="text" value={paymentReference} onChange={(e) => setPaymentReference(e.target.value)} placeholder="Nomor referensi dari bank" /></label>
          <label>Tautan bukti<input type="url" value={paymentEvidenceUri} onChange={(e) => setPaymentEvidenceUri(e.target.value)} placeholder="Link Drive/foto bukti transfer" /></label>
        </div>
        <div className="ops-row-actions">
          <button type="button" onClick={previewPayment} disabled={savingPayment || !paymentInvoiceId || Number(paymentAmount) <= 0}><Calculator size={14} /> {savingPayment ? "Memeriksa..." : "Preview Pembayaran"}</button>
          <button type="button" onClick={commitPayment} disabled={savingPayment || !paymentPreview?.canCommit}><CheckCircle2 size={14} /> Konfirmasi & Simpan</button>
        </div>
        {paymentPreview && (
          <div className="ops-summary-strip">
            <span>Vendor <strong>{paymentPreview.vendorCode}</strong></span>
            <span>Sisa sebelum <strong>{money(paymentPreview.remainingBefore)}</strong></span>
            <span>Dibayar <strong>{money(paymentPreview.paymentAmount)}</strong></span>
            <span>Sisa sesudah <strong>{money(paymentPreview.remainingAfter)}</strong></span>
            <span>Status setelah <strong>{paymentPreview.payableStatusAfter}</strong></span>
          </div>
        )}
        {!outstanding.length && <div className="ops-notice">Tidak ada tagihan outstanding yang dapat dibayar.</div>}
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
        {noPaymentRequired.length > 0 && <div className="ops-notice">{noPaymentRequired.length} tagihan netto Rp0 tidak dapat dibayar karena sudah habis oleh reject/potongan. Gunakan <strong>Koreksi</strong> bila angka tagihan salah.</div>}
        <div className="ops-table-wrap">
          <table className="ops-table">
            <thead><tr><th>Vendor</th><th>Site</th><th>PO</th><th>Invoice</th><th>Distribusi</th><th>Bruto</th><th>Reject</th><th>Netto</th><th>Jatuh Tempo</th><th>Status</th><th>Aksi</th></tr></thead>
            <tbody>
              {[...outstanding, ...noPaymentRequired].map((item) => (
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
                  <td>{Number(item.net_amount || 0) <= 0.01 ? "TIDAK ADA BAYAR" : (item.payable_status || "UNPAID")}</td>
                  <td>
                    {Number(item.net_amount || 0) > 0.01 && <button type="button" className="ops-button-primary" onClick={() => setPaymentModalItem(item)}>Bayar + Bukti</button>}
                    <button type="button" onClick={() => openPayableEdit(item)} style={{ marginLeft: Number(item.net_amount || 0) > 0.01 ? 6 : 0 }}>Koreksi</button>
                    {Number(item.net_amount || 0) <= 0.01 && <button type="button" className="danger" onClick={() => deleteRejectedPayable(item)} disabled={savingPayableEdit} style={{ marginLeft: 6 }}>Hapus</button>}
                  </td>
                </tr>
              ))}
              {!loading && outstanding.length + noPaymentRequired.length === 0 && <tr><td colSpan="11" className="ops-empty-cell">Tidak ada tagihan vendor outstanding.</td></tr>}
            </tbody>
          </table>
        </div>
        {editingPayable && payableEdit && <div className="ops-parse-result" style={{ marginTop: 14 }}>
          <div><strong>Koreksi tagihan {editingPayable.vendor_code} · {editingPayable.po_code || `#${editingPayable.vendor_invoice_id}`}</strong></div>
          <p className="ops-muted">Ubah angka invoice bila input salah atau ada perubahan item. PO dan receipt tetap tersimpan sebagai jejak asli.</p>
          <div className="ops-form-grid">
            <label>No. invoice<input value={payableEdit.invoice_number} onChange={(e) => setPayableEdit({ ...payableEdit, invoice_number: e.target.value })} /></label>
            <label>Tgl invoice<input type="date" value={payableEdit.invoice_date} onChange={(e) => setPayableEdit({ ...payableEdit, invoice_date: e.target.value })} /></label>
            <label>Jatuh tempo<input type="date" value={payableEdit.due_date} onChange={(e) => setPayableEdit({ ...payableEdit, due_date: e.target.value })} /></label>
            <label>Bruto<input type="number" min="0" value={payableEdit.gross_amount} onChange={(e) => setPayableEdit({ ...payableEdit, gross_amount: e.target.value })} /></label>
            <label>Reject/potongan<input type="number" min="0" value={payableEdit.reject_deduction} onChange={(e) => setPayableEdit({ ...payableEdit, reject_deduction: e.target.value })} /></label>
            <label>Netto hasil<input value={money(Math.max(Number(payableEdit.gross_amount || 0) - Number(payableEdit.reject_deduction || 0), 0))} readOnly /></label>
          </div>
          <label>Alasan koreksi<input value={payableEdit.correction_note} onChange={(e) => setPayableEdit({ ...payableEdit, correction_note: e.target.value })} placeholder="Contoh: item PO berubah, transfer lebih bayar, atau reject salah input" /></label>
          <div className="ops-row-actions" style={{ marginTop: 10 }}><button type="button" onClick={() => { setEditingPayable(null); setPayableEdit(null); }}>Batal</button><button type="button" onClick={savePayableEdit} disabled={savingPayableEdit}>{savingPayableEdit ? "Menyimpan…" : "Simpan Koreksi"}</button></div>
        </div>}
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
