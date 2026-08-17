import baseConfig from "./vite.config.js";

function poReminderActionsVisible() {
  return {
    name: "sppg-po-reminder-actions-visible",
    enforce: "pre",
    transform(code, id) {
      if (!id.includes("/src/operations/OperationsPoPlanner.jsx")) return null;
      if (!code.includes("PENGINGAT PO BERDASARKAN LEAD TIME")) return null;

      let next = code;
      const returnAnchor = `  return (\n    <div className="ops-domain-stack">`;
      if (!next.includes(returnAnchor)) {
        throw new Error("[po-actions-visible] Missing OperationsPoPlanner return anchor");
      }

      const actionHelper = `  const renderReminderActions = (item) => {\n    const remaining = remainingReminderQty(item);\n    const reminderStatus = String(item.reminder_status || "").toUpperCase();\n    const orderingAction = ["OVERDUE", "DUE_TODAY"].includes(reminderStatus) && remaining > 0;\n    const residualReview = reminderStatus === "SHORTAGE_REVIEW" && remaining > 0;\n    const canCreatePo = orderingAction || residualReview;\n    const canConfirmStock = ["OVERDUE", "DUE_TODAY", "SHORTAGE_REVIEW"].includes(reminderStatus) && remaining > 0;\n    const canConfirmManualPo = ["OVERDUE", "DUE_TODAY"].includes(reminderStatus) && Boolean(item.reminder_key);\n\n    return <div className="ops-row-actions" data-po-reminder-actions="v15">\n      {item.reminder_override ? (\n        <button type="button" onClick={() => clearReminderOverride(item)} disabled={reminderActionKey === item.reminder_key}><RotateCcw size={13} /> Batalkan Override</button>\n      ) : <>\n        {canCreatePo && <button className="ops-button-primary" type="button" onClick={() => createReminderShortagePo(item)} disabled={reminderActionKey === item.reminder_key}><ShoppingCart size={13} /> {residualReview ? "Buat PO Tambahan" : "Buat PO"}</button>}\n        {canConfirmManualPo && <button className="ops-button-success" type="button" onClick={() => saveReminderOverride(item, "MANUAL_PO")} disabled={reminderActionKey === item.reminder_key}><Send size={13} /> PO sudah dilakukan</button>}\n        {canConfirmStock && item.reminder_key && <button type="button" onClick={() => confirmShortageStock(item)} disabled={reminderActionKey === item.reminder_key}><Save size={13} /> Konfirmasi stok gudang</button>}\n        {residualReview && item.reminder_key && <button className="ops-button-success" type="button" onClick={() => saveReminderOverride(item, "CHECKED")} disabled={reminderActionKey === item.reminder_key}><CheckCircle2 size={13} /> Sudah dicek / biarkan</button>}\n      </>}\n    </div>;\n  };\n\n`;
      next = next.replace(returnAnchor, `${actionHelper}${returnAnchor}`);

      const reminderStart = next.indexOf('<span className="ops-kicker">PENGINGAT PO BERDASARKAN LEAD TIME</span>');
      const nextSection = next.indexOf('      <section className="ops-module">', reminderStart + 20);
      if (reminderStart < 0 || nextSection < 0) {
        throw new Error("[po-actions-visible] Lead-time reminder block was not found after base transform");
      }

      let reminderBlock = next.slice(reminderStart, nextSection);
      reminderBlock = reminderBlock.replaceAll(
        '<th>PO</th></tr></thead><tbody>',
        '<th>PO</th><th data-po-actions-version="v15">Aksi</th></tr></thead><tbody>',
      );
      reminderBlock = reminderBlock.replaceAll(
        '</td></tr>)}',
        '</td><td>{renderReminderActions(item)}</td></tr>)}',
      );
      reminderBlock = reminderBlock.replaceAll('colSpan="6"', 'colSpan="7"');

      const headerCount = (reminderBlock.match(/data-po-actions-version="v15"/g) || []).length;
      const actionCellCount = (reminderBlock.match(/renderReminderActions\(item\)/g) || []).length;
      if (headerCount !== 3 || actionCellCount !== 3) {
        throw new Error(`[po-actions-visible] Expected 3 reminder action columns/cells, got headers=${headerCount}, cells=${actionCellCount}`);
      }

      next = next.slice(0, reminderStart) + reminderBlock + next.slice(nextSection);
      return { code: next, map: null };
    },
  };
}

export default {
  ...baseConfig,
  plugins: [...(baseConfig.plugins || []), poReminderActionsVisible()],
};
