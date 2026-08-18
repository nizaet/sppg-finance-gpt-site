import baseConfig from "./vite.config.js";

function poReminderActionsVisible() {
  return {
    name: "sppg-po-reminder-actions-visible",
    enforce: "pre",
    transform(code, id) {
      if (!id.includes("/src/operations/OperationsPoPlanner.jsx")) return null;
      if (!code.includes("PENGINGAT PO BERDASARKAN LEAD TIME")) return null;

      let next = code;
      const replaceOnce = (needle, replacement, label) => {
        if (!next.includes(needle)) {
          throw new Error(`[po-runtime] Missing transform anchor: ${label}`);
        }
        next = next.replace(needle, replacement);
      };

      replaceOnce(
        `  const [reminders, setReminders] = useState([]);`,
        `  const [reminders, setReminders] = useState([]);\n  const [deliveryAlerts, setDeliveryAlerts] = useState([]);\n  const [poSearch, setPoSearch] = useState("");\n  const [showArchivedPo, setShowArchivedPo] = useState(false);`,
        "delivery alert and archive state",
      );

      replaceOnce(
        `      const [poData, vendorsData, reminderData] = await Promise.all([\n        operationsApi.getPurchaseOrders({ site: activeSite, limit: 50 }),\n        operationsApi.getReferenceVendors(activeSite),\n        operationsApi.getPoReminders({ site: activeSite, date: today(), horizonDays: 2 }),\n      ]);\n      setPurchaseOrders(poData?.items || []);\n      setReminders(reminderData?.items || []);`,
        `      const [poData, vendorsData, reminderData, alertData] = await Promise.all([\n        operationsApi.getPurchaseOrders({ site: activeSite, limit: 80, fromDate: shiftDate(today(), -1), toDate: shiftDate(today(), 7) }),\n        operationsApi.getReferenceVendors(activeSite),\n        operationsApi.getPoReminders({ site: activeSite, date: today(), horizonDays: 2 }),\n        operationsApi.getPoDeliveryAlerts({ site: activeSite, date: today(), minimumHour: 17 }),\n      ]);\n      setPurchaseOrders(poData?.items || []);\n      setReminders(reminderData?.items || []);\n      setDeliveryAlerts(alertData?.items || []);`,
        "load base PO + alerts",
      );

      next = next.replaceAll(
        `operationsApi.getPurchaseOrders({ site: activeSite, limit: 50 })`,
        `operationsApi.getPurchaseOrders({ site: activeSite, limit: 80, fromDate: shiftDate(today(), -1), toDate: shiftDate(today(), 7) })`,
      );

      replaceOnce(
        `  const refreshPurchaseOrders = async () => {\n    const poData = await operationsApi.getPurchaseOrders({ site: activeSite, limit: 80, fromDate: shiftDate(today(), -1), toDate: shiftDate(today(), 7) });\n    setPurchaseOrders(poData?.items || []);\n  };`,
        `  const refreshPurchaseOrders = async (options = {}) => {\n    const search = options.search ?? poSearch;\n    const includeArchived = options.includeArchived ?? (showArchivedPo || Boolean(String(search || "").trim()));\n    const dateWindow = String(search || "").trim() ? {} : { fromDate: shiftDate(today(), -1), toDate: shiftDate(today(), 7) };\n    const poData = await operationsApi.getPurchaseOrders({\n      site: activeSite,\n      limit: 80,\n      search,\n      includeArchived,\n      ...dateWindow,\n    });\n    setPurchaseOrders(poData?.items || []);\n  };`,
        "archive-aware PO refresh",
      );

      replaceOnce(
        `<div><span className="ops-kicker">PO TERCATAT</span><h3>Purchase Order Aktual</h3><p>Planning, stok, PO, receiving, invoice dan pembayaran tetap layer terpisah.</p></div>`,
        `<div><span className="ops-kicker">PO TERCATAT</span><h3>Purchase Order Aktual</h3><p>Default hanya PO aktif H-1 s.d. H+7. PO RECEIVED dan H+2 masuk arsip, tapi tetap bisa dicari.</p><div className="ops-form-grid" data-po-archive-search="v16"><label>Cari PO / barang / vendor<input value={poSearch} onChange={(e) => setPoSearch(e.target.value)} placeholder="contoh: Holil, Jeruk, PO-MAJA..." /></label><label>Arsip<div className="ops-row-actions"><input type="checkbox" checked={showArchivedPo} onChange={(e) => setShowArchivedPo(e.target.checked)} /> Tampilkan arsip</div></label><label>Aksi<div className="ops-row-actions"><button type="button" onClick={() => refreshPurchaseOrders({ search: poSearch, includeArchived: showArchivedPo || Boolean(poSearch.trim()) })}><RefreshCw size={14} /> Cari / Refresh</button></div></label></div></div>`,
        "PO archive search controls",
      );

      const returnAnchor = `  return (\n    <div className="ops-domain-stack">`;
      if (!next.includes(returnAnchor)) {
        throw new Error("[po-actions-visible] Missing OperationsPoPlanner return anchor");
      }

      const helperBlock = `  const refreshDeliveryAlerts = async () => {\n    const alertData = await operationsApi.getPoDeliveryAlerts({ site: activeSite, date: today(), minimumHour: 17 });\n    setDeliveryAlerts(alertData?.items || []);\n  };\n\n  const confirmDeliveryAlert = async (alert, action) => {\n    const labels = {\n      SENT_CONFIRMED: "PO sudah terkirim",\n      ARRIVED_MATCH: "Barang datang sesuai PO",\n      ARRIVED_MISMATCH: "Barang datang tidak sesuai",\n    };\n    const label = labels[action] || action;\n    const notePrompt = action === "ARRIVED_MATCH"\n      ? "Catatan penerimaan / penerima barang (opsional):"\n      : "Alasan / catatan wajib:";\n    const note = window.prompt(notePrompt, action === "SENT_CONFIRMED" ? "Sudah dikirim ke vendor" : "");\n    if (note === null) return;\n    if (["SENT_CONFIRMED", "ARRIVED_MISMATCH"].includes(action) && !String(note || "").trim()) {\n      setError(action === "SENT_CONFIRMED" ? "Alasan/catatan wajib diisi untuk konfirmasi PO sudah terkirim." : "Alasan wajib diisi kalau barang datang tidak sesuai.");\n      return;\n    }\n    const confirmText = action === "ARRIVED_MATCH"\n      ? \`Catat seluruh sisa item \${alert.poCode} sebagai BARANG DATANG SESUAI?\\n\\nStok akan bertambah sesuai sisa qty PO yang belum diterima.\`\n      : \`\${label} untuk \${alert.poCode}?\\n\\nCatatan: \${note || "-"}\`;\n    if (!window.confirm(confirmText)) return;\n    setActionId(alert.purchaseOrderId);\n    setError("");\n    setMessage("");\n    try {\n      const result = await operationsApi.confirmPoDeliveryAlert({\n        purchase_order_id: alert.purchaseOrderId,\n        action,\n        note: note || null,\n        actor: "operations-ui",\n      });\n      await refreshPurchaseOrders();\n      await refreshReminders();\n      await refreshDeliveryAlerts();\n      setMessage(result?.message || \`\${label} tersimpan.\`);\n    } catch (err) {\n      setError(err.message || \`Gagal menyimpan konfirmasi \${label}\`);\n    } finally {\n      setActionId(null);\n    }\n  };\n\n  const updateDraftStockQty = (planningItemId, plannedQty, value) => {\n    const stockQty = Math.max(0, Number(value || 0));\n    const recommended = Math.max(0, Number((Number(plannedQty || 0) - stockQty).toFixed(4)));\n    const current = draftItems.find((row) => row.planning_snapshot_item_id === planningItemId);\n    const wasAuto = !current || Number(current.po_qty || 0) === Number(current.recommended_po_qty || 0);\n    updateDraftItem(planningItemId, {\n      stock_qty: stockQty,\n      projected_stock_qty: stockQty,\n      stock_basis: "MANUAL_UI_STOCK_OVERRIDE_FOR_PO",\n      stock_confidence: "MANUAL",\n      recommended_po_qty: recommended,\n      po_qty: wasAuto ? recommended : current.po_qty,\n    });\n  };\n\n  const reminderShortageLines = (item) => (item.requirement_details || [])\n    .filter((detail) => Number(detail.remaining_po_qty || 0) > 0)\n    .map((detail) => ({\n      name: (detail.item_names || []).filter(Boolean).join(", ") || detail.stock_type_code || "Item",\n      qty: Number(detail.remaining_po_qty || 0),\n      unit: detail.unit || "",\n      state: String(detail.ordering_state || "NOT_ORDERED").toUpperCase(),\n    }));\n\n  const renderReminderActions = (item) => {\n    const remaining = remainingReminderQty(item);\n    const reminderStatus = String(item.reminder_status || "").toUpperCase();\n    const orderingAction = ["OVERDUE", "DUE_TODAY"].includes(reminderStatus) && remaining > 0;\n    const residualReview = reminderStatus === "SHORTAGE_REVIEW" && remaining > 0;\n    const canCreatePo = orderingAction || residualReview;\n    const canConfirmStock = ["OVERDUE", "DUE_TODAY", "SHORTAGE_REVIEW"].includes(reminderStatus) && remaining > 0;\n    const canConfirmManualPo = ["OVERDUE", "DUE_TODAY"].includes(reminderStatus) && Boolean(item.reminder_key);\n\n    return <div className="ops-row-actions" data-po-reminder-actions="v16">\n      {item.reminder_override ? (\n        <button type="button" onClick={() => clearReminderOverride(item)} disabled={reminderActionKey === item.reminder_key}><RotateCcw size={13} /> Batalkan Override</button>\n      ) : <>\n        {canCreatePo && <button className="ops-button-primary" type="button" onClick={() => createReminderShortagePo(item)} disabled={reminderActionKey === item.reminder_key}><ShoppingCart size={13} /> {residualReview ? "Buat PO Tambahan" : "Buat PO"}</button>}\n        {canConfirmManualPo && <button className="ops-button-success" type="button" onClick={() => saveReminderOverride(item, "MANUAL_PO")} disabled={reminderActionKey === item.reminder_key}><Send size={13} /> PO sudah dilakukan</button>}\n        {canConfirmStock && item.reminder_key && <button type="button" onClick={() => confirmShortageStock(item)} disabled={reminderActionKey === item.reminder_key}><Save size={13} /> Konfirmasi stok gudang</button>}\n        {residualReview && item.reminder_key && <button className="ops-button-success" type="button" onClick={() => saveReminderOverride(item, "CHECKED")} disabled={reminderActionKey === item.reminder_key}><CheckCircle2 size={13} /> Sudah dicek / biarkan</button>}\n      </>}\n    </div>;\n  };\n\n`;
      next = next.replace(returnAnchor, `${helperBlock}${returnAnchor}`);

      const stockDisplay = `<strong className={Number(item.stock_qty || 0) > 0 ? "ops-stock-positive" : ""}>{qty(item.stock_qty)}</strong>`;
      const editableStockDisplay = `<div data-editable-stock="v16"><strong className={Number(item.stock_qty || 0) > 0 ? "ops-stock-positive" : ""}>{qty(item.stock_qty)}</strong><PoQtyMath value={item.stock_qty} title={"Stok gudang " + item.item_name} onChange={(value) => updateDraftStockQty(item.planning_snapshot_item_id, item.planned_qty, value)} /></div>`;
      replaceOnce(stockDisplay, editableStockDisplay, "editable daily stock qty");

      const reminderStart = next.indexOf('<span className="ops-kicker">PENGINGAT PO BERDASARKAN LEAD TIME</span>');
      const nextSection = next.indexOf('      <section className="ops-module">', reminderStart + 20);
      if (reminderStart < 0 || nextSection < 0) {
        throw new Error("[po-actions-visible] Lead-time reminder block was not found after base transform");
      }

      let reminderBlock = next.slice(reminderStart, nextSection);
      const shortageCell = `<strong>{reminderNames(item).length || item.item_count}</strong>{reminderNames(item).length > 0 && <div className="ops-muted">{reminderNames(item).join(", ")}</div>}`;
      const shortageCellWithQty = `<strong>{reminderShortageLines(item).length || reminderNames(item).length || item.item_count}</strong>{reminderShortageLines(item).length > 0 ? <div className="ops-muted">{reminderShortageLines(item).map((line) => <div key={line.name + "-" + line.unit}><strong>{line.name}</strong> kurang {qty(line.qty)} {line.unit} <span className={"ops-reminder-pill " + (line.state === "ORDERED_PARTIAL" || line.state === "IN_APP_PARTIAL" ? "ops-pill-amber" : "ops-pill-red")}>{line.state === "ORDERED_PARTIAL" ? "SUDAH DIPESAN · SISA" : line.state === "IN_APP_PARTIAL" ? "PO APLIKASI BELUM CUKUP" : "BELUM DIPESAN"}</span></div>)}</div> : reminderNames(item).length > 0 && <div className="ops-muted">{reminderNames(item).join(", ")}</div>}`;
      reminderBlock = reminderBlock.replaceAll(shortageCell, shortageCellWithQty);

      const alertBlockAnchor = `        </div>\n\n        {reminderOverdue.length > 0 && <div className="ops-draft-group">`;
      const alertBlock = `        </div>\n        {deliveryAlerts.length > 0 && <div className="ops-error" data-delivery-alerts="v20"><strong>⚠ Peringatan barang belum datang setelah jam 17.00</strong>{deliveryAlerts.map((alert) => <div key={alert.purchaseOrderId} className="ops-delivery-alert-item"><strong>{alert.poCode}</strong> · {alert.vendorCode} · masak {String(alert.cookingDate || "-")}<div>{alert.message}</div>{(alert.items || []).slice(0, 6).map((line) => <div className="ops-muted" key={line.itemName}>{line.message}</div>)}<div className="ops-row-actions" data-delivery-alert-actions="v20"><button type="button" onClick={() => confirmDeliveryAlert(alert, "SENT_CONFIRMED")} disabled={actionId === alert.purchaseOrderId}><Send size={13} /> PO sudah terkirim</button><button className="ops-button-success" type="button" onClick={() => confirmDeliveryAlert(alert, "ARRIVED_MATCH")} disabled={actionId === alert.purchaseOrderId}><CheckCircle2 size={13} /> Barang datang sesuai</button><button type="button" onClick={() => confirmDeliveryAlert(alert, "ARRIVED_MISMATCH")} disabled={actionId === alert.purchaseOrderId}><XCircle size={13} /> Datang tidak sesuai</button></div></div>)}</div>}\n\n        {reminderOverdue.length > 0 && <div className="ops-draft-group">`;
      if (!reminderBlock.includes(alertBlockAnchor)) {
        throw new Error("[po-runtime] Missing alert block anchor");
      }
      reminderBlock = reminderBlock.replace(alertBlockAnchor, alertBlock);

      reminderBlock = reminderBlock.replaceAll(
        '<th>PO</th></tr></thead><tbody>',
        '<th>PO</th><th data-po-actions-version="v16">Aksi</th></tr></thead><tbody>',
      );
      reminderBlock = reminderBlock.replaceAll(
        '</td></tr>)}',
        '</td><td>{renderReminderActions(item)}</td></tr>)}',
      );
      reminderBlock = reminderBlock.replaceAll('colSpan="6"', 'colSpan="7"');

      const headerCount = (reminderBlock.match(/data-po-actions-version="v16"/g) || []).length;
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
