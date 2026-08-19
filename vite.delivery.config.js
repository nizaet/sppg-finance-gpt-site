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
        let plannerCode = code;

        // Delivery alert confirmation: a successful server save must immediately
        // disappear even if slower secondary PO/reminder refreshes fail.
        const oldSequence = `      await refreshPurchaseOrders();\n      await refreshReminders();\n      await refreshDeliveryAlerts();\n      setMessage(result?.message || \`\${label} tersimpan.\`);`;
        if (plannerCode.includes(oldSequence)) {
          const newSequence = `      if (!result?.saved) throw new Error(result?.message || \`Konfirmasi \${label} belum tersimpan.\`);\n      // Confirmation is already committed on the server. Remove the resolved card\n      // immediately so a slower PO/reminder refresh cannot make it appear as if\n      // the button did nothing. The authoritative delivery-alert read runs first.\n      setDeliveryAlerts((current) => current.filter((row) => row.purchaseOrderId !== alert.purchaseOrderId));\n      try {\n        await refreshDeliveryAlerts();\n      } catch (alertRefreshError) {\n        console.warn("Delivery alert saved but alert refresh failed", alertRefreshError);\n      }\n      // PO/reminder refresh is secondary to the confirmation. Failure here must\n      // not resurrect a delivery alert that the backend has already resolved.\n      const secondaryRefresh = await Promise.allSettled([refreshPurchaseOrders(), refreshReminders()]);\n      const failedRefreshes = secondaryRefresh.filter((entry) => entry.status === "rejected");\n      setMessage((result?.message || \`\${label} tersimpan.\`) + (failedRefreshes.length ? " Data PO/pengingat akan diperbarui saat refresh berikutnya." : ""));`;
          plannerCode = plannerCode.replace(oldSequence, newSequence);
        }

        // Item-level PO coverage. One Telur PO must not block the remaining
        // KOPERASI items on the same vendor/date. Prefer persisted planning item
        // identity; fall back to canonicalized item name + unit for older POs.
        const updateDraftAnchor = `  const updateDraftItem = (planningItemId, patch) => {\n    setDraftItems((current) => current.map((item) => item.planning_snapshot_item_id === planningItemId ? { ...item, ...patch } : item));\n  };`;
        if (plannerCode.includes(updateDraftAnchor) && !plannerCode.includes("isItemCoveredByActivePo")) {
          const coverageHelper = `${updateDraftAnchor}\n\n  const isItemCoveredByActivePo = (item, forDate = distributionDate) => {\n    const planningId = Number(item?.planning_snapshot_item_id || 0);\n    const wantedName = normalize(item?.item_name);\n    const wantedUnit = normalizeUnit(item?.unit);\n    return purchaseOrders.some((po) => {\n      if (!isActivePurchaseOrder(po)) return false;\n      if (String(po.site || "").toUpperCase() !== String(activeSite || "").toUpperCase()) return false;\n      if (String(po.vendor_code || "").toUpperCase() !== String(item?.vendor_code || "").toUpperCase()) return false;\n      if (!coverageDatesFor(po).includes(String(forDate))) return false;\n      const ids = (po.planning_item_ids || []).map((value) => Number(value || 0));\n      if (planningId > 0 && ids.includes(planningId)) return true;\n      return (po.item_keys || []).some((key) => {\n        const separator = String(key || "").lastIndexOf("|");\n        const rawName = separator >= 0 ? String(key).slice(0, separator) : String(key || "");\n        const rawUnit = separator >= 0 ? String(key).slice(separator + 1) : "";\n        return normalize(rawName) === wantedName && normalizeUnit(rawUnit) === wantedUnit;\n      });\n    });\n  };`;
          plannerCode = plannerCode.replace(updateDraftAnchor, coverageHelper);
        }

        const oldVendorLines = `    const lines = draftItems.filter((item) => item.vendor_code === vendor && !item.excluded && Number(item.po_qty || 0) > 0 && !findActiveItemSplitPo(item, distributionDate));`;
        const newVendorLines = `    const lines = draftItems.filter((item) => item.vendor_code === vendor && !item.excluded && Number(item.po_qty || 0) > 0 && !isItemCoveredByActivePo(item, distributionDate));`;
        plannerCode = plannerCode.replace(oldVendorLines, newVendorLines);

        const oldVendorCode = `    const code = \`PO-\${activeSite}-\${distributionDate.replaceAll("-", "")}-\${vendor}\`;`;
        const newVendorCode = `    const baseCode = \`PO-\${activeSite}-\${distributionDate.replaceAll("-", "")}-\${vendor}\`;\n    const hasExistingVendorDatePo = purchaseOrders.some((po) => isActivePurchaseOrder(po) && String(po.vendor_code || "").toUpperCase() === String(vendor).toUpperCase() && coverageDatesFor(po).includes(String(distributionDate)));\n    const code = hasExistingVendorDatePo\n      ? \`\${baseCode}-TAMBAHAN-\${poItemSlug(lines[0]?.item_name)}\${lines.length > 1 ? `-${lines.length}` : ""}\`\n      : baseCode;`;
        plannerCode = plannerCode.replace(oldVendorCode, newVendorCode);

        // Range PO uses the same item-level rule. Existing coverage for one item
        // no longer blocks every other item on that date.
        plannerCode = plannerCode.replace(
          `selected: row.items.filter((item) => !item.excluded && Number(item.po_qty || 0) > 0 && !findActiveItemSplitPo(item, row.date)),`,
          `selected: row.items.filter((item) => !item.excluded && Number(item.po_qty || 0) > 0 && !isItemCoveredByActivePo(item, row.date)),`,
        );
        const existingRangeBlock = `    const existingCoverage = candidates\n      .map((row) => ({ date: row.date, po: activePoByVendorDate.get(\`\${rangeVendor}|\${row.date}\`) }))\n      .filter((row) => row.po);\n    if (existingCoverage.length) {\n      const labels = existingCoverage.map((row) => \`\${row.date}: \${row.po.po_code} (\${row.po.status})\`).join("; ");\n      setError(\`PO tidak dibuat ulang karena cakupan sudah ada: \${labels}. Buka PO tersebut untuk edit atau buat revisi, agar qty tidak tergandakan.\`);\n      return;\n    }\n`;
        plannerCode = plannerCode.replace(existingRangeBlock, "");

        const oldRangeCode = `        po_code: \`PO-\${activeSite}-\${codeDate}-\${rangeVendor}\`,`;
        const newRangeCode = `        po_code: purchaseOrders.some((po) => isActivePurchaseOrder(po) && String(po.vendor_code || "").toUpperCase() === String(rangeVendor).toUpperCase() && candidates.some((row) => coverageDatesFor(po).includes(String(row.date))))\n          ? \`PO-\${activeSite}-\${codeDate}-\${rangeVendor}-TAMBAHAN-\${poItemSlug(aggregateItems[0]?.item_name)}-\${aggregateItems.length}\`\n          : \`PO-\${activeSite}-\${codeDate}-\${rangeVendor}\`,`;
        plannerCode = plannerCode.replace(oldRangeCode, newRangeCode);

        // Never display a late CEMPLANG response after the selector has moved to
        // MAJA (or vice versa). The manual refresh button below then force-loads
        // the currently selected site.
        const reminderBucketAnchor = `  const reminderOverdue = reminders.filter((item) => String(item.po_date || "") < today() && item.reminder_status === "OVERDUE");`;
        if (plannerCode.includes(reminderBucketAnchor)) {
          plannerCode = plannerCode.replace(
            reminderBucketAnchor,
            `  const siteReminders = reminders.filter((item) => !item?.site || String(item.site).toUpperCase() === String(activeSite).toUpperCase());\n  const reminderOverdue = siteReminders.filter((item) => String(item.po_date || "") < today() && item.reminder_status === "OVERDUE");`,
          );
          plannerCode = plannerCode.replace(
            `  const reminderToday = reminders.filter((item) => String(item.po_date || "") === today());`,
            `  const reminderToday = siteReminders.filter((item) => String(item.po_date || "") === today());`,
          );
          plannerCode = plannerCode.replace(
            `  const reminderTomorrow = reminders.filter((item) => String(item.po_date || "") === shiftDate(today(), 1));`,
            `  const reminderTomorrow = siteReminders.filter((item) => String(item.po_date || "") === shiftDate(today(), 1));`,
          );
        }

        const reminderHeader = `<div><span className="ops-kicker">PENGINGAT PO BERDASARKAN LEAD TIME</span><h3>PO yang Harus Dikerjakan</h3><p>Kebutuhan berasal dari planning aktif setelah dikurangi stok proyeksi. Tanggal kirim PO mengikuti lead time vendor. PO yang sudah lewat tanggal pesan tetap muncul sebagai TERLAMBAT sampai selesai.</p></div>\n          <BellRing size={32} />`;
        const reminderHeaderWithRefresh = `<div><span className="ops-kicker">PENGINGAT PO BERDASARKAN LEAD TIME</span><h3>PO yang Harus Dikerjakan</h3><p>Kebutuhan berasal dari planning aktif setelah dikurangi stok proyeksi. Tanggal kirim PO mengikuti lead time vendor. PO yang sudah lewat tanggal pesan tetap muncul sebagai TERLAMBAT sampai selesai.</p><div className="ops-row-actions" data-po-reminder-refresh="v23"><button type="button" onClick={async () => { setError(""); try { await refreshReminders(); setMessage(\`Pengingat PO \${activeSite} diperbarui.\`); } catch (err) { setError(err.message || "Gagal refresh pengingat PO"); } }} disabled={loading}><RefreshCw size={14} /> Refresh Pengingat PO · {activeSite}</button></div></div>\n          <BellRing size={32} />`;
        plannerCode = plannerCode.replace(reminderHeader, reminderHeaderWithRefresh);

        return plannerCode === code ? null : { code: plannerCode, map: null };
      }

      return null;
    },
  };
}

export default {
  ...runtimeConfig,
  plugins: [...(runtimeConfig.plugins || []), deliveryApiClientCompatibility()],
};