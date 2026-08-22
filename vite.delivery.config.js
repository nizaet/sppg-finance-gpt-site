import runtimeConfig from "./vite.runtime.config.js";

function deliveryApiClientCompatibility() {
  return {
    name: "sppg-delivery-api-client-compatibility",
    enforce: "pre",
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

        const apiMarker = `  overridePoReminder: (payload) => request("/v1/po-reminders/override", { method: "POST", body: JSON.stringify(payload) }),`;
        if (!apiCode.includes("confirmPoDeliveryAlert")) {
          const insertion = `  confirmPoDeliveryAlert: (payload) => request("/v1/po-delivery-alerts/confirm", { method: "POST", body: JSON.stringify(payload) }),\n`;
          if (apiCode.includes(apiMarker)) apiCode = apiCode.replace(apiMarker, `${insertion}${apiMarker}`);
        }
        if (!apiCode.includes("getPoReceivingConfirmation")) {
          const insertion = `  getPoReceivingConfirmation: (purchaseOrderId) => request(\`/v1/purchase-orders/\${encodeURIComponent(purchaseOrderId)}/receiving-confirmation\`),\n  confirmPoReceiving: (purchaseOrderId, payload) => request(\`/v1/purchase-orders/\${encodeURIComponent(purchaseOrderId)}/receiving-confirmation\`, { method: "POST", body: JSON.stringify(payload) }),\n`;
          if (apiCode.includes(apiMarker)) apiCode = apiCode.replace(apiMarker, `${insertion}${apiMarker}`);
        }

        return apiCode === code ? null : { code: apiCode, map: null };
      }

      if (id.includes("/src/operations/OperationsPoPlanner.jsx")) {
        let plannerCode = code;

        const importAnchor = `import PoQtyMath from "./PoQtyMath.jsx";`;
        if (!plannerCode.includes(importAnchor)) {
          throw new Error("[po-delivery] PoQtyMath import anchor missing");
        }
        if (!plannerCode.includes("PoOpsEnhancements")) {
          plannerCode = plannerCode.replace(importAnchor, `${importAnchor}\nimport PoOpsEnhancements from "./PoOpsEnhancements.jsx";`);
        }
        if (!plannerCode.includes("PoReceivingConfirm")) {
          const anchor = `import PoOpsEnhancements from "./PoOpsEnhancements.jsx";`;
          if (!plannerCode.includes(anchor)) throw new Error("[po-receiving] PoOpsEnhancements import anchor missing");
          plannerCode = plannerCode.replace(anchor, `${anchor}\nimport PoReceivingConfirm from "./PoReceivingConfirm.jsx";`);
        }

        const oldSequence = `      await refreshPurchaseOrders();\n      await refreshReminders();\n      await refreshDeliveryAlerts();\n      setMessage(result?.message || \`\${label} tersimpan.\`);`;
        if (plannerCode.includes(oldSequence)) {
          const newSequence = `      if (!result?.saved) throw new Error(result?.message || \`Konfirmasi \${label} belum tersimpan.\`);\n      setDeliveryAlerts((current) => current.filter((row) => row.purchaseOrderId !== alert.purchaseOrderId));\n      if (action === "ARRIVED_MATCH" && result?.receiptId) {\n        window.dispatchEvent(new CustomEvent("sppg:goods-receipt-saved", { detail: { site: activeSite, purchaseOrderId: alert.purchaseOrderId, receiptId: result.receiptId } }));\n      }\n      try { await refreshDeliveryAlerts(); } catch (alertRefreshError) { console.warn("Delivery alert saved but alert refresh failed", alertRefreshError); }\n      const secondaryRefresh = await Promise.allSettled([refreshPurchaseOrders(), refreshReminders()]);\n      const failedRefreshes = secondaryRefresh.filter((entry) => entry.status === "rejected");\n      setMessage((result?.message || \`\${label} tersimpan.\`) + (failedRefreshes.length ? " Data PO/pengingat akan diperbarui saat refresh berikutnya." : ""));`;
          plannerCode = plannerCode.replace(oldSequence, newSequence);
        }

        const updateDraftAnchor = `  const updateDraftItem = (planningItemId, patch) => {\n    setDraftItems((current) => current.map((item) => item.planning_snapshot_item_id === planningItemId ? { ...item, ...patch } : item));\n  };`;
        if (plannerCode.includes(updateDraftAnchor) && !plannerCode.includes("isItemCoveredByActivePo")) {
          const coverageHelper = `${updateDraftAnchor}\n\n  const isItemCoveredByActivePo = (item, forDate = distributionDate) => {\n    const planningId = Number(item?.planning_snapshot_item_id || 0);\n    const wantedName = normalize(item?.item_name);\n    const wantedUnit = normalizeUnit(item?.unit);\n    return purchaseOrders.some((po) => {\n      if (!isActivePurchaseOrder(po)) return false;\n      if (String(po.site || "").toUpperCase() !== String(activeSite || "").toUpperCase()) return false;\n      if (String(po.vendor_code || "").toUpperCase() !== String(item?.vendor_code || "").toUpperCase()) return false;\n      if (!coverageDatesFor(po).includes(String(forDate))) return false;\n      const ids = (po.planning_item_ids || []).map((value) => Number(value || 0));\n      if (planningId > 0 && ids.includes(planningId)) return true;\n      return (po.item_keys || []).some((key) => {\n        const separator = String(key || "").lastIndexOf("|");\n        const rawName = separator >= 0 ? String(key).slice(0, separator) : String(key || "");\n        const rawUnit = separator >= 0 ? String(key).slice(separator + 1) : "";\n        return normalize(rawName) === wantedName && normalizeUnit(rawUnit) === wantedUnit;\n      });\n    });\n  };`;
          plannerCode = plannerCode.replace(updateDraftAnchor, coverageHelper);
        }

        plannerCode = plannerCode.replace(
          `    const lines = draftItems.filter((item) => item.vendor_code === vendor && !item.excluded && Number(item.po_qty || 0) > 0 && !findActiveItemSplitPo(item, distributionDate));`,
          `    const lines = draftItems.filter((item) => item.vendor_code === vendor && !item.excluded && Number(item.po_qty || 0) > 0 && !isItemCoveredByActivePo(item, distributionDate));`,
        );

        const oldVendorCode = `    const code = \`PO-\${activeSite}-\${distributionDate.replaceAll("-", "")}-\${vendor}\`;`;
        const newVendorCode = `    const baseCode = \`PO-\${activeSite}-\${distributionDate.replaceAll("-", "")}-\${vendor}\`;\n    const hasExistingVendorDatePo = purchaseOrders.some((po) => isActivePurchaseOrder(po) && String(po.vendor_code || "").toUpperCase() === String(vendor).toUpperCase() && coverageDatesFor(po).includes(String(distributionDate)));\n    const code = hasExistingVendorDatePo\n      ? baseCode + "-TAMBAHAN-" + poItemSlug(lines[0]?.item_name) + (lines.length > 1 ? "-" + lines.length : "")\n      : baseCode;`;
        plannerCode = plannerCode.replace(oldVendorCode, newVendorCode);

        plannerCode = plannerCode.replace(
          `selected: row.items.filter((item) => !item.excluded && Number(item.po_qty || 0) > 0 && !findActiveItemSplitPo(item, row.date)),`,
          `selected: row.items.filter((item) => !item.excluded && Number(item.po_qty || 0) > 0 && !isItemCoveredByActivePo(item, row.date)),`,
        );

        const existingRangeBlock = `    const existingCoverage = candidates\n      .map((row) => ({ date: row.date, po: activePoByVendorDate.get(\`\${rangeVendor}|\${row.date}\`) }))\n      .filter((row) => row.po);\n    if (existingCoverage.length) {\n      const labels = existingCoverage.map((row) => \`\${row.date}: \${row.po.po_code} (\${row.po.status})\`).join("; ");\n      setError(\`PO tidak dibuat ulang karena cakupan sudah ada: \${labels}. Buka PO tersebut untuk edit atau buat revisi, agar qty tidak tergandakan.\`);\n      return;\n    }\n`;
        plannerCode = plannerCode.replace(existingRangeBlock, "");

        const oldRangeCode = `        po_code: \`PO-\${activeSite}-\${codeDate}-\${rangeVendor}\`,`;
        const newRangeCode = `        po_code: purchaseOrders.some((po) => isActivePurchaseOrder(po) && String(po.vendor_code || "").toUpperCase() === String(rangeVendor).toUpperCase() && candidates.some((row) => coverageDatesFor(po).includes(String(row.date))))\n          ? "PO-" + activeSite + "-" + codeDate + "-" + rangeVendor + "-TAMBAHAN-" + poItemSlug(aggregateItems[0]?.item_name) + "-" + aggregateItems.length\n          : "PO-" + activeSite + "-" + codeDate + "-" + rangeVendor,`;
        plannerCode = plannerCode.replace(oldRangeCode, newRangeCode);

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

        const reminderTitleAnchor = `<span className="ops-kicker">PENGINGAT PO BERDASARKAN LEAD TIME</span><h3>PO yang Harus Dikerjakan</h3>`;
        if (!plannerCode.includes(reminderTitleAnchor)) {
          throw new Error("[po-delivery] reminder title anchor missing");
        }
        plannerCode = plannerCode.replace(
          reminderTitleAnchor,
          `${reminderTitleAnchor}<PoOpsEnhancements mode="reminder" activeSite={activeSite} reminders={reminders} setReminders={setReminders} setRemindersPulled={setRemindersPulled} setPurchaseOrders={setPurchaseOrders} setDeliveryAlerts={setDeliveryAlerts} />`,
        );

        const detailAnchor = `        {viewingPo && <div className="ops-po-detail" id="po-detail-panel">`;
        if (!plannerCode.includes(detailAnchor)) {
          throw new Error("[po-delivery] PO detail anchor missing");
        }
        plannerCode = plannerCode.replace(
          detailAnchor,
          `        <PoOpsEnhancements mode="calendar" activeSite={activeSite} setReminders={setReminders} setPurchaseOrders={setPurchaseOrders} setPoListLoaded={setPoListLoaded} setDeliveryAlerts={setDeliveryAlerts} />\n${detailAnchor}`,
        );

        // The red "barang belum datang" block is intentionally retired. Receiving
        // is now an explicit action on the actual PO (list/calendar), not an alert.
        const redAlertStart = plannerCode.indexOf(`        {deliveryAlerts.length > 0 && <div className="ops-error" data-delivery-alerts="v20">`);
        if (redAlertStart >= 0) {
          const nextReminderBlock = plannerCode.indexOf(`        {reminderOverdue.length > 0`, redAlertStart);
          if (nextReminderBlock > redAlertStart) {
            plannerCode = plannerCode.slice(0, redAlertStart) + plannerCode.slice(nextReminderBlock);
          }
        }

        const listDetailButton = `<button type="button" onClick={() => viewPoDetail(po)} disabled={actionId === po.id}><Eye size={14} /> Lihat Detail</button>`;
        if (plannerCode.includes(listDetailButton) && !plannerCode.includes(`data-po-receiving-list="v30"`)) {
          plannerCode = plannerCode.replace(
            listDetailButton,
            `${listDetailButton}\n                      <span data-po-receiving-list="v30"><PoReceivingConfirm poId={po.id} poCode={po.po_code} status={po.status} onChanged={async () => { await refreshPurchaseOrders(); }} /></span>`,
          );
        }

        const detailSummaryEnd = `<span>Total <strong>{money((viewingPo.items || []).reduce((sum, item) => sum + Number(item.po_qty || 0) * Number(item.po_price || 0), 0))}</strong></span>\n          </div>`;
        if (plannerCode.includes(detailSummaryEnd) && !plannerCode.includes(`data-po-receiving-detail="v30"`)) {
          plannerCode = plannerCode.replace(
            detailSummaryEnd,
            `${detailSummaryEnd}\n          <div data-po-receiving-detail="v30"><PoReceivingConfirm poId={viewingPo.id} poCode={viewingPo.po_code} status={viewingPo.status} onChanged={async () => { await refreshPurchaseOrders(); const detail = await operationsApi.getPurchaseOrder(viewingPo.id); setViewingPo(detail); }} /></div>`,
          );
        }

        return plannerCode === code ? null : { code: plannerCode, map: null };
      }

      if (id.includes("/src/operations/PoOpsEnhancements.jsx")) {
        let enhancementCode = code;
        const importAnchor = `import { operationsApi } from "./apiClient";`;
        if (!enhancementCode.includes("PoReceivingConfirm")) {
          if (!enhancementCode.includes(importAnchor)) throw new Error("[po-receiving] enhancements import anchor missing");
          enhancementCode = enhancementCode.replace(importAnchor, `${importAnchor}\nimport PoReceivingConfirm from "./PoReceivingConfirm.jsx";`);
        }

        enhancementCode = enhancementCode.replace(
          `          <button type="button" onClick={refreshDelivery} disabled={progress.active}>\n            <RefreshCw size={14} /> Refresh Barang Datang\n          </button>`,
          ``,
        );

        const calendarOrdersAnchor = `            <h4>Pesanan</h4>`;
        if (enhancementCode.includes(calendarOrdersAnchor) && !enhancementCode.includes(`data-calendar-po-receiving="v30"`)) {
          enhancementCode = enhancementCode.replace(
            calendarOrdersAnchor,
            `            <div data-calendar-po-receiving="v30" style={{ marginTop: 12 }}><PoReceivingConfirm inline poId={calendarPo.id} poCode={calendarPo.po_code} status={calendarPo.status} onChanged={async () => { await refreshCalendar(); await refreshActualPo(); const detail = await operationsApi.getPurchaseOrder(calendarPo.id); setCalendarPo((current) => current ? { ...current, ...detail } : current); }} /></div>\n${calendarOrdersAnchor}`,
          );
        }
        return enhancementCode === code ? null : { code: enhancementCode, map: null };
      }

      return null;
    },
  };
}

export default {
  ...runtimeConfig,
  plugins: [...(runtimeConfig.plugins || []), deliveryApiClientCompatibility()],
};
