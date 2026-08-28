export default function financeUiPlacementPlugin() {
  const foldCss = `
/* SPPG FINANCE FOLD FIX V2 */
.ops-accountant-unified,
.ops-payments-domain,
.ops-accountant-unified .ops-module-header,
.ops-accountant-unified .ops-table-wrap,
.ops-payments-domain .ops-table-wrap {
  min-width: 0;
  max-width: 100%;
}

.ops-calendar-scroll {
  display: block;
  width: 100%;
  max-width: 100%;
  overflow-x: auto !important;
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
  overscroll-behavior-x: contain;
  touch-action: pan-x pan-y;
  padding-bottom: 7px;
}

@media (max-width: 900px) {
  .ops-accountant-unified {
    overflow: hidden;
  }

  .ops-accountant-unified .ops-inline-controls {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 7px;
    width: 100%;
  }

  .ops-accountant-unified .ops-inline-controls select {
    grid-column: 1 / -1;
    width: 100% !important;
  }

  .ops-accountant-unified .ops-inline-controls button {
    width: 100%;
    min-width: 0;
    justify-content: center;
    white-space: normal;
  }

  .ops-accountant-unified .ops-summary-strip {
    gap: 6px;
  }

  .ops-accountant-unified .ops-summary-strip span {
    flex: 1 1 calc(50% - 6px);
    min-width: 0;
    justify-content: space-between;
    white-space: normal;
  }

  .ops-calendar-scroll {
    overflow-x: scroll !important;
    scrollbar-gutter: stable;
  }

  .ops-calendar-grid {
    min-width: 760px !important;
  }

  .ops-accountant-list-wrap {
    overflow: visible !important;
    border: 0 !important;
  }

  .ops-accountant-list-wrap .ops-table,
  .ops-accountant-list-wrap .ops-table tbody,
  .ops-accountant-list-wrap .ops-table tr,
  .ops-accountant-list-wrap .ops-table td {
    display: block;
    width: 100%;
    min-width: 0 !important;
  }

  .ops-accountant-list-wrap .ops-table {
    min-width: 0 !important;
  }

  .ops-accountant-list-wrap .ops-table thead {
    display: none;
  }

  .ops-accountant-list-wrap .ops-table tbody {
    display: grid;
    gap: 10px;
  }

  .ops-accountant-list-wrap .ops-table tr {
    border: 1px solid rgba(148, 163, 184, .24);
    border-radius: 12px;
    overflow: hidden;
  }

  .ops-accountant-list-wrap .ops-table td {
    display: grid;
    grid-template-columns: 106px minmax(0, 1fr);
    gap: 9px;
    align-items: start;
    padding: 8px 10px;
    white-space: normal !important;
    overflow-wrap: anywhere;
  }

  .ops-accountant-list-wrap .ops-table td::before {
    font-weight: 800;
    color: #64748b;
  }

  .ops-accountant-list-wrap .ops-table td:nth-child(1)::before { content: "Tanggal"; }
  .ops-accountant-list-wrap .ops-table td:nth-child(2)::before { content: "Site"; }
  .ops-accountant-list-wrap .ops-table td:nth-child(3)::before { content: "Kategori"; }
  .ops-accountant-list-wrap .ops-table td:nth-child(4)::before { content: "Invoice"; }
  .ops-accountant-list-wrap .ops-table td:nth-child(5)::before { content: "Nilai"; }
  .ops-accountant-list-wrap .ops-table td:nth-child(6)::before { content: "Status"; }
  .ops-accountant-list-wrap .ops-table td:nth-child(7)::before { content: "Maker"; }
  .ops-accountant-list-wrap .ops-table td:nth-child(8)::before { content: "File"; }
  .ops-accountant-list-wrap .ops-table td:nth-child(9)::before { content: "Aksi"; }
  .ops-accountant-list-wrap .ops-empty-cell {
    display: block !important;
    text-align: center !important;
  }
  .ops-accountant-list-wrap .ops-empty-cell::before { content: none !important; }

  .ops-payment-payables .ops-table-wrap,
  .ops-payment-history .ops-table-wrap {
    overflow: visible !important;
    border: 0 !important;
  }

  .ops-payment-payables .ops-table,
  .ops-payment-payables .ops-table tbody,
  .ops-payment-payables .ops-table tr,
  .ops-payment-payables .ops-table td,
  .ops-payment-history .ops-table,
  .ops-payment-history .ops-table tbody,
  .ops-payment-history .ops-table tr,
  .ops-payment-history .ops-table td {
    display: block;
    width: 100%;
    min-width: 0 !important;
  }

  .ops-payment-payables .ops-table,
  .ops-payment-history .ops-table {
    min-width: 0 !important;
  }

  .ops-payment-payables .ops-table thead,
  .ops-payment-history .ops-table thead {
    display: none;
  }

  .ops-payment-payables .ops-table tbody,
  .ops-payment-history .ops-table tbody {
    display: grid;
    gap: 10px;
  }

  .ops-payment-payables .ops-table tr,
  .ops-payment-history .ops-table tr {
    border: 1px solid rgba(148, 163, 184, .24);
    border-radius: 12px;
    overflow: hidden;
  }

  .ops-payment-payables .ops-table td,
  .ops-payment-history .ops-table td {
    display: grid;
    grid-template-columns: 104px minmax(0, 1fr);
    gap: 8px;
    padding: 8px 10px;
    white-space: normal !important;
    overflow-wrap: anywhere;
  }

  .ops-payment-payables .ops-table td::before,
  .ops-payment-history .ops-table td::before {
    font-weight: 800;
    color: #64748b;
  }

  .ops-payment-payables .ops-table td:nth-child(1)::before { content: "Vendor"; }
  .ops-payment-payables .ops-table td:nth-child(2)::before { content: "Site"; }
  .ops-payment-payables .ops-table td:nth-child(3)::before { content: "PO"; }
  .ops-payment-payables .ops-table td:nth-child(4)::before { content: "Invoice"; }
  .ops-payment-payables .ops-table td:nth-child(5)::before { content: "Distribusi"; }
  .ops-payment-payables .ops-table td:nth-child(6)::before { content: "Bruto"; }
  .ops-payment-payables .ops-table td:nth-child(7)::before { content: "Reject"; }
  .ops-payment-payables .ops-table td:nth-child(8)::before { content: "Netto"; }
  .ops-payment-payables .ops-table td:nth-child(9)::before { content: "Jatuh Tempo"; }
  .ops-payment-payables .ops-table td:nth-child(10)::before { content: "Status"; }

  .ops-payment-history .ops-table td:nth-child(1)::before { content: "Vendor"; }
  .ops-payment-history .ops-table td:nth-child(2)::before { content: "Site"; }
  .ops-payment-history .ops-table td:nth-child(3)::before { content: "Invoice"; }
  .ops-payment-history .ops-table td:nth-child(4)::before { content: "Nilai Invoice"; }
  .ops-payment-history .ops-table td:nth-child(5)::before { content: "Dibayar"; }
  .ops-payment-history .ops-table td:nth-child(6)::before { content: "Tanggal Bayar"; }
  .ops-payment-history .ops-table td:nth-child(7)::before { content: "Sumber"; }
  .ops-payment-history .ops-table td:nth-child(8)::before { content: "Status"; }

  .ops-payment-payables .ops-empty-cell,
  .ops-payment-history .ops-empty-cell {
    display: block !important;
    text-align: center !important;
  }
  .ops-payment-payables .ops-empty-cell::before,
  .ops-payment-history .ops-empty-cell::before { content: none !important; }

  .ops-payments-domain .ops-table-wrap:not(.ops-payment-payables .ops-table-wrap):not(.ops-payment-history .ops-table-wrap) {
    overflow-x: auto !important;
    -webkit-overflow-scrolling: touch;
    touch-action: pan-x pan-y;
  }
}
`;

  return {
    name: "sppg-finance-ui-placement-v2",
    // These replacements target raw JSX. Running post-transform means React has
    // already compiled the JSX and none of the button/section markers exist.
    enforce: "pre",
    transform(code, id) {
      let out = code;

      if (id.includes("/src/operations/AccountantUnifiedCalendar.jsx")) {
        out = out.replace(
          '<section className="ops-module">',
          '<section className="ops-module ops-accountant-unified">'
        );
        out = out.replace(
          /<button type="button" onClick=\{itemizeVendorPayments\} disabled=\{busy\|\|itemizeBusy\}>[\s\S]*?<\/button>/,
          ""
        );
        out = out.replace(
          '<div style={{ overflowX: "auto" }}><div style={{ minWidth: 980 }}>',
          '<div className="ops-calendar-scroll"><div className="ops-calendar-grid" style={{ minWidth: 980 }}>'
        );
        out = out.replace(
          '{viewMode === "list" && <div className="ops-table-wrap"><table className="ops-table">',
          '{viewMode === "list" && <div className="ops-table-wrap ops-accountant-list-wrap"><table className="ops-table">'
        );
      }

      if (id.includes("/src/operations/OperationsPayments.jsx")) {
        if (!out.includes('from "./accountantApi.js"')) {
          out = out.replace(
            'import { operationsApi } from "./apiClient";',
            'import { operationsApi } from "./apiClient";\nimport { accountantApi } from "./accountantApi.js";'
          );
        }

        if (!out.includes("const [itemizeBusy, setItemizeBusy]")) {
          out = out.replace(
            '  const [error, setError] = useState("");',
            '  const [error, setError] = useState("");\n  const [itemizeBusy, setItemizeBusy] = useState(false);'
          );
        }

        if (!out.includes("const itemizeVendorPayments = async")) {
          const handler = `  const itemizeVendorPayments = async () => {\n    if (!activeSite) {\n      setError("Pilih site sebelum merinci pembayaran vendor.");\n      return;\n    }\n    if (!window.confirm(\`Rincikan seluruh pembayaran vendor \${activeSite} menjadi pengeluaran per item? Total pembayaran tidak berubah.\`)) return;\n    setItemizeBusy(true);\n    setError("");\n    setActionMessage("");\n    try {\n      const result = await accountantApi.itemizeVendorPaymentFinance(activeSite);\n      setActionMessage(\`Rincian pembayaran vendor selesai: \${result.financeRows || 0} baris item dari \${result.paymentsProcessed || 0} pembayaran.\`);\n      await load();\n    } catch (err) {\n      setError(err.message || "Gagal merinci pembayaran vendor");\n    } finally {\n      setItemizeBusy(false);\n    }\n  };\n\n`;
          out = out.replace("  return (\n", handler + "  return (\n");
        }

        out = out.replace(
          '<div className="ops-domain-stack">',
          '<div className="ops-domain-stack ops-payments-domain">'
        );

        out = out.replace(
          /<section className="ops-module">(\s*<div className="ops-module-header">\s*<div>\s*<span className="ops-kicker">INVOICE \/ PAYABLE<\/span>)/,
          '<section className="ops-module ops-payment-payables">$1'
        );
        out = out.replace(
          /<section className="ops-module">(\s*<div className="ops-module-header">\s*<div>\s*<span className="ops-kicker">PAYMENT EVIDENCE<\/span>)/,
          '<section className="ops-module ops-payment-history">$1'
        );

        if (!out.includes('data-itemize-vendor-payments="v2"')) {
          const marker = '        <div className="ops-row-actions">\n          <button type="button" onClick={previewPayment}';
          out = out.replace(
            marker,
            '        <div className="ops-row-actions">\n          <button data-itemize-vendor-payments="v2" type="button" onClick={itemizeVendorPayments} disabled={loading || itemizeBusy || !activeSite}><RefreshCw size={14} /> {itemizeBusy ? "Merinci…" : "Rincikan Pembayaran Vendor"}</button>\n          <button type="button" onClick={previewPayment}'
          );
        }

        out = out.replace(
          "Pencatatan ini belum otomatis membuat pengeluaran Akuntan.",
          "Pengeluaran Akuntan dibuat otomatis per item setelah pembayaran PAID."
        );
      }

      if (id.includes("/src/operations/workspace.css") && !out.includes("SPPG FINANCE FOLD FIX V2")) {
        out += foldCss;
      }

      return out === code ? null : { code: out, map: null };
    },
  };
}
