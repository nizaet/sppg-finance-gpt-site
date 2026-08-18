import runtimeConfig from "./vite.runtime.config.js";

function deliveryApiClientCompatibility() {
  return {
    name: "sppg-delivery-api-client-compatibility",
    enforce: "post",
    transform(code, id) {
      if (!id.includes("/src/operations/apiClient.js")) return null;

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
    },
  };
}

export default {
  ...runtimeConfig,
  plugins: [...(runtimeConfig.plugins || []), deliveryApiClientCompatibility()],
};
