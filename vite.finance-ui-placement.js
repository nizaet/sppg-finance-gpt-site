export default function financeUiPlacementPlugin() {
  return {
    name: "sppg-finance-ui-placement-v1",
    enforce: "post",
    transform(code, id) {
      let out = code;

      // This repair action belongs to Invoice & Pembayaran, not the
      // Accountant/BGN approval calendar.
      if (id.includes("/src/operations/AccountantUnifiedCalendar.jsx")) {
        out = out.replace(
          /<button type="button" onClick=\{itemizeVendorPayments\} disabled=\{busy\|\|itemizeBusy\}>[\s\S]*?<\/button>/,
          ""
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

        if (!out.includes('data-itemize-vendor-payments="v1"')) {
          const marker = '        <div className="ops-row-actions">\n          <button type="button" onClick={previewPayment}';
          out = out.replace(
            marker,
            '        <div className="ops-row-actions">\n          <button data-itemize-vendor-payments="v1" type="button" onClick={itemizeVendorPayments} disabled={loading || itemizeBusy || !activeSite}><RefreshCw size={14} /> {itemizeBusy ? "Merinci…" : "Rincikan Pembayaran Vendor"}</button>\n          <button type="button" onClick={previewPayment}'
          );
        }

        out = out.replace(
          "Pencatatan ini belum otomatis membuat pengeluaran Akuntan.",
          "Pengeluaran Akuntan dibuat otomatis per item setelah pembayaran PAID."
        );
      }

      return out === code ? null : { code: out, map: null };
    },
  };
}
