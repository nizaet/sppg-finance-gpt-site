import fs from "node:fs";

const path = "src/operations/OperationsPoPlanner.jsx";
let source = fs.readFileSync(path, "utf8");

function replaceOnce(label, before, after) {
  const count = source.split(before).length - 1;
  if (count !== 1) {
    throw new Error(`${label}: expected exactly one source anchor, found ${count}`);
  }
  source = source.replace(before, after);
}

replaceOnce(
  "PO must use current actual dapur stock",
  `    const stock = {\n      balance: Math.max(0, Number(item.available_for_po ?? item.balance ?? 0)),\n      actualBalance: Number(item.actual_balance ?? item.balance ?? 0),`,
  `    const actualBalance = Number(item.actual_balance ?? item.balance ?? 0);\n    const stock = {\n      // PO follows the warehouse screen's “Stok aktual sekarang”. Planning\n      // depletion/provisional PO supply remains audit/projection information and\n      // must never replace the current physical dapur balance used by PO.\n      balance: Math.max(0, actualBalance),\n      actualBalance,`,
);

replaceOnce(
  "Tarik Data must load saved PO coverage for duplicate guard",
  `      const [scheduleData, inventoryData, cooperativeData] = await Promise.all([\n        operationsApi.previewPoSchedule({ distributionDate, cookingDate, site: activeSite }),\n        operationsApi.getInventoryBalances({ site: activeSite, search: "", limit: 1000, forDate: distributionDate }),\n        operationsApi.getInventoryBalances({ site: "KOPERASI", search: "", limit: 1000, forDate: distributionDate }),\n      ]);\n      setSchedule(scheduleData?.items || []);\n      applyPlanningSnapshot(detail, inventoryData?.items || [], cooperativeData?.items || []);`,
  `      const [scheduleData, inventoryData, cooperativeData, poData] = await Promise.all([\n        operationsApi.previewPoSchedule({ distributionDate, cookingDate, site: activeSite }),\n        operationsApi.getInventoryBalances({ site: activeSite, search: "", limit: 1000, forDate: distributionDate }),\n        operationsApi.getInventoryBalances({ site: "KOPERASI", search: "", limit: 1000, forDate: distributionDate }),\n        // Duplicate prevention is part of the explicit “Tarik Data” action.\n        // Include RECEIVED/archived rows for this exact distribution date so an\n        // item that was already ordered cannot silently become PO-able again.\n        operationsApi.getPurchaseOrders({\n          site: activeSite,\n          includeArchived: true,\n          fromDate: distributionDate,\n          toDate: distributionDate,\n          limit: 200,\n        }),\n      ]);\n      setSchedule(scheduleData?.items || []);\n      setPurchaseOrders(poData?.items || []);\n      setPoListLoaded(true);\n      applyPlanningSnapshot(detail, inventoryData?.items || [], cooperativeData?.items || []);`,
);

fs.writeFileSync(path, source);
console.log("Applied PO planner fix: actual dapur stock + saved-PO duplicate guard");
