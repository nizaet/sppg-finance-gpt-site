import runtimeConfig from "./vite.runtime.config.js";

function deliveryAlertActionControls() {
  return {
    name: "sppg-delivery-alert-actions",
    enforce: "post",
    transform(code, id) {
      if (id.includes("/src/operations/apiClient.js")) {
        let apiCode = code
          .replace(
            "const REQUEST_TIMEOUT_MS = 20000;",
            "const REQUEST_TIMEOUT_MS = 60000;",
          )
          .replace(
            `if (err?.name === "AbortError") throw new Error("SPPG Core API terlalu lama merespons. Coba Refresh.");`,
            `if (err?.name === "AbortError") throw new Error(\`SPPG Core API terlalu lama merespons: \${path}. Coba Refresh.\`);`,
          )
          .replace("/v1/control-tower-v2?${q}", "/v1/control-tower?${q}");
        if (!apiCode.includes("confirmPoDeliveryAlert")) {
          const marker = `  overridePoReminder: (payload) => request("/v1/po-reminders/override", { method: "POST", body: JSON.stringify(payload) }),`;
          const insertion = `  confirmPoDeliveryAlert: (payload) => request("/v1/po-delivery-alerts/confirm", { method: "POST", body: JSON.stringify(payload) }),\n`;
          if (!apiCode.includes(marker)) {
            return apiCode === code ? null : { code: apiCode, map: null };
          }
          apiCode = apiCode.replace(marker, `${insertion}${marker}`);
        }
        return apiCode === code ? null : { code: apiCode, map: null };
      }

      if (!id.includes("/src/operations/OperationsPoPlanner.jsx")) return null;
      if (!code.includes("Peringatan barang belum datang")) return null;
      if (code.includes("confirmDeliveryAlert = async")) return null;

      let next = code;
      const helperAnchor = `  const updateDraftStockQty = (`;
      const itemListNeedle = `{(alert.items || []).slice(0, 6).map((line) => <div className="ops-muted" key={line.itemName}>{line.message}</div>)}`;
      if (!next.includes(helperAnchor) || !next.includes(itemListNeedle)) {
        return null;
      }

      const helper = `  const refreshDeliveryAlerts = async () => {\n    const alertData = await operationsApi.getPoDeliveryAlerts({ site: activeSite, date: today(), minimumHour: 17 });\n    setDeliveryAlerts(alertData?.items || []);\n  };\n\n  const confirmDeliveryAlert = async (alert, action) => {\n    const labels = {\n      SENT_CONFIRMED: "PO sudah terkirim",\n      ARRIVED_MATCH: "Barang datang sesuai PO",\n      ARRIVED_MISMATCH: "Barang datang tidak sesuai",\n    };\n    const label = labels[action] || action;\n    const notePrompt = action === "ARRIVED_MATCH"\n      ? "Catatan penerimaan / penerima barang (opsional):"\n      : "Alasan / catatan wajib:";\n    const note = window.prompt(notePrompt, action === "SENT_CONFIRMED" ? "Sudah dikirim ke vendor" : "");\n    if (note === null) return;\n    if (["SENT_CONFIRMED", "ARRIVED_MISMATCH"].includes(action) && !String(note || "").trim()) {\n      setError(action === "SENT_CONFIRMED" ? "Alasan/catatan wajib diisi untuk konfirmasi PO sudah terkirim." : "Alasan wajib diisi kalau barang datang tidak sesuai.");\n      return;\n    }\n    const confirmText = action === "ARRIVED_MATCH"\n      ? \`Catat seluruh sisa item \${alert.poCode} sebagai BARANG DATANG SESUAI?\\n\\nStok akan bertambah sesuai sisa qty PO yang belum diterima.\`\n      : \`\${label} untuk \${alert.poCode}?\\n\\nCatatan: \${note || "-"}\`;\n    if (!window.confirm(confirmText)) return;\n    setActionId(alert.purchaseOrderId);\n    setError("");\n    setMessage("");\n    try {\n      const result = await operationsApi.confirmPoDeliveryAlert({\n        purchase_order_id: alert.purchaseOrderId,\n        action,\n        note: note || null,\n        actor: "operations-ui",\n      });\n      await refreshPurchaseOrders();\n      await refreshReminders();\n      await refreshDeliveryAlerts();\n      setMessage(result?.message || \`\${label} tersimpan.\`);\n    } catch (err) {\n      setError(err.message || \`Gagal menyimpan konfirmasi \${label}\`);\n    } finally {\n      setActionId(null);\n    }\n  };\n\n`;
      next = next.replace(helperAnchor, `${helper}${helperAnchor}`);

      const actionButtons = `<div className="ops-row-actions" data-delivery-alert-actions="v19"><button type="button" onClick={() => confirmDeliveryAlert(alert, "SENT_CONFIRMED")} disabled={actionId === alert.purchaseOrderId}><Send size={13} /> PO sudah terkirim</button><button className="ops-button-success" type="button" onClick={() => confirmDeliveryAlert(alert, "ARRIVED_MATCH")} disabled={actionId === alert.purchaseOrderId}><CheckCircle2 size={13} /> Barang datang sesuai</button><button type="button" onClick={() => confirmDeliveryAlert(alert, "ARRIVED_MISMATCH")} disabled={actionId === alert.purchaseOrderId}>✕ Datang tidak sesuai</button></div>`;
      next = next.replace(itemListNeedle, `${itemListNeedle}${actionButtons}`);

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
