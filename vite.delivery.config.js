import runtimeConfig from "./vite.runtime.config.js";

function deliveryApiClientCompatibility() {
  return {
    name: "sppg-delivery-api-client-compatibility",
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
          if (apiCode.includes(marker)) apiCode = apiCode.replace(marker, `${insertion}${marker}`);
        }

        return apiCode === code ? null : { code: apiCode, map: null };
      }

      if (id.includes("/src/operations/OperationsPoPlanner.jsx")) {
        const oldSequence = `      await refreshPurchaseOrders();\n      await refreshReminders();\n      await refreshDeliveryAlerts();\n      setMessage(result?.message || \`\${label} tersimpan.\`);`;
        if (!code.includes(oldSequence)) return null;

        const newSequence = `      if (!result?.saved) throw new Error(result?.message || \`Konfirmasi \${label} belum tersimpan.\`);\n      // Confirmation is already committed on the server. Remove the resolved card\n      // immediately so a slower PO/reminder refresh cannot make it appear as if\n      // the button did nothing. The authoritative delivery-alert read runs first.\n      setDeliveryAlerts((current) => current.filter((row) => row.purchaseOrderId !== alert.purchaseOrderId));\n      try {\n        await refreshDeliveryAlerts();\n      } catch (alertRefreshError) {\n        console.warn("Delivery alert saved but alert refresh failed", alertRefreshError);\n      }\n      // PO/reminder refresh is secondary to the confirmation. Failure here must\n      // not resurrect a delivery alert that the backend has already resolved.\n      const secondaryRefresh = await Promise.allSettled([refreshPurchaseOrders(), refreshReminders()]);\n      const failedRefreshes = secondaryRefresh.filter((entry) => entry.status === "rejected");\n      setMessage((result?.message || \`\${label} tersimpan.\`) + (failedRefreshes.length ? " Data PO/pengingat akan diperbarui saat refresh berikutnya." : ""));`;

        const plannerCode = code.replace(oldSequence, newSequence);
        return { code: plannerCode, map: null };
      }

      return null;
    },
  };
}

export default {
  ...runtimeConfig,
  plugins: [...(runtimeConfig.plugins || []), deliveryApiClientCompatibility()],
};
