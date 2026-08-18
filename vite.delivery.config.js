import runtimeConfig from "./vite.runtime.config.js";

function deliveryAlertActionControls() {
  return {
    name: "sppg-delivery-alert-actions",
    enforce: "post",
    transform(code, id) {
      if (id.includes("/src/operations/apiClient.js")) {
        if (code.includes("confirmPoDeliveryAlert")) return null;
        const marker = `  overridePoReminder: (payload) => request("/v1/po-reminders/override", { method: "POST", body: JSON.stringify(payload) }),`;
        const insertion = `  confirmPoDeliveryAlert: (payload) => request("/v1/po-delivery-alerts/confirm", { method: "POST", body: JSON.stringify(payload) }),\n`;
        if (!code.includes(marker)) {
          throw new Error("[delivery-alert-actions] Missing stable API insertion marker");
        }
        return { code: code.replace(marker, `${insertion}${marker}`), map: null };
      }

      if (!id.includes("/src/operations/OperationsPoPlanner.jsx")) return null;
      if (!code.includes(`data-delivery-alerts="v16"`)) return null;
      if (code.includes("confirmDeliveryAlert = async")) return null;

      let next = code;
      const returnAnchor = `  return (\n    <div className="ops-domain-stack">`;
      const helper = `  const refreshDeliveryAlerts = async () => {\n    const alertData = await operationsApi.getPoDeliveryAlerts({ site: activeSite, date: today(), minimumHour: 17 });\n    setDeliveryAlerts(alertData?.items || []);\n  };\n\n  const confirmDeliveryAlert = async (alert, action) => {\n    const labels = {\n      SENT_CONFIRMED: "PO sudah terkirim",\n      ARRIVED_MATCH: "Barang datang sesuai PO",\n      ARRIVED_MISMATCH: "Barang datang tidak sesuai",\n    };\n    const label = labels[action] || action;\n    const notePrompt = action === "ARRIVED_MATCH"\n      ? "Catatan penerimaan / penerima barang (opsional):"\n      : "Alasan / catatan wajib:";\n    const note = window.prompt(notePrompt, action === "SENT_CONFIRMED" ? "Sudah dikirim ke vendor" : "");\n    if (note === null) return;\n    if (action === "ARRIVED_MISMATCH" && !String(note || "").trim()) {\n      setError("Alasan wajib diisi kalau barang datang tidak sesuai.");\n      return;\n    }\n    const confirmText = action === "ARRIVED_MATCH"\n      ? \`Catat seluruh sisa item \${alert.poCode} sebagai BARANG DATANG SESUAI?\\n\\nStok akan bertambah sesuai sisa qty PO yang belum diterima.\`\n      : \`\${label} untuk \${alert.poCode}?\\n\\nCatatan: \${note || "-"}\`;\n    if (!window.confirm(confirmText)) return;\n    setActionId(alert.purchaseOrderId);\n    setError("");\n    setMessage("");\n    try {\n      const result = await operationsApi.confirmPoDeliveryAlert({\n        purchase_order_id: alert.purchaseOrderId,\n        action,\n        note: note || null,\n        actor: "operations-ui",\n      });\n      await refreshPurchaseOrders();\n      await refreshReminders();\n      await refreshDeliveryAlerts();\n      setMessage(result?.message || \`\${label} tersimpan.\`);\n    } catch (err) {\n      setError(err.message || \`Gagal menyimpan konfirmasi \${label}\`);\n    } finally {\n      setActionId(null);\n    }\n  };\n\n`;
      if (!next.includes(returnAnchor)) {
        throw new Error("[delivery-alert-actions] Missing return anchor");
      }
      next = next.replace(returnAnchor, `${helper}${returnAnchor}`);

      const alertNeedle = `{(alert.items || []).slice(0, 6).map((line) => <div className="ops-muted" key={line.itemName}>{line.message}</div>)}</div>)}</div>}`;
      const alertReplacement = `{(alert.items || []).slice(0, 6).map((line) => <div className="ops-muted" key={line.itemName}>{line.message}</div>)}<div className="ops-row-actions" data-delivery-alert-actions="v17"><button type="button" onClick={() => confirmDeliveryAlert(alert, "SENT_CONFIRMED")} disabled={actionId === alert.purchaseOrderId}><Send size={13} /> PO sudah terkirim</button><button className="ops-button-success" type="button" onClick={() => confirmDeliveryAlert(alert, "ARRIVED_MATCH")} disabled={actionId === alert.purchaseOrderId}><CheckCircle2 size={13} /> Barang datang sesuai</button><button type="button" onClick={() => confirmDeliveryAlert(alert, "ARRIVED_MISMATCH")} disabled={actionId === alert.purchaseOrderId}><XCircle size={13} /> Datang tidak sesuai</button></div></div>)}</div>}`;
      if (!next.includes(alertNeedle)) {
        throw new Error("[delivery-alert-actions] Missing alert render anchor");
      }
      next = next.replace(alertNeedle, alertReplacement);

      next = next.replaceAll("Untuk Di-PO Besok", "Info PO Besok — belum perlu dikirim hari ini");
      next = next.replaceAll("persiapan satu hari ke depan", "informasi tanggal pesan besok, bukan aksi hari ini");

      return { code: next, map: null };
    },
  };
}

export default {
  ...runtimeConfig,
  plugins: [...(runtimeConfig.plugins || []), deliveryAlertActionControls()],
};
