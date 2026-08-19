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

        // Delivery confirmation remains responsive even if secondary reminder work is slow.
        const oldSequence = `      await refreshPurchaseOrders();\n      await refreshReminders();\n      await refreshDeliveryAlerts();\n      setMessage(result?.message || \`\${label} tersimpan.\`);`;
        if (plannerCode.includes(oldSequence)) {
          const newSequence = `      if (!result?.saved) throw new Error(result?.message || \`Konfirmasi \${label} belum tersimpan.\`);\n      setDeliveryAlerts((current) => current.filter((row) => row.purchaseOrderId !== alert.purchaseOrderId));\n      try { await refreshDeliveryAlerts(); } catch (alertRefreshError) { console.warn("Delivery alert saved but alert refresh failed", alertRefreshError); }\n      const secondaryRefresh = await Promise.allSettled([refreshPurchaseOrders(), refreshReminders()]);\n      const failedRefreshes = secondaryRefresh.filter((entry) => entry.status === "rejected");\n      setMessage((result?.message || \`\${label} tersimpan.\`) + (failedRefreshes.length ? " Data PO/pengingat akan diperbarui saat refresh berikutnya." : ""));`;
          plannerCode = plannerCode.replace(oldSequence, newSequence);
        }

        // Item-level PO coverage: one Telur PO cannot block other items for the same vendor/date.
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

        // Runtime pre-transform guarantees these state anchors. Attach the new UI state here,
        // instead of relying on a long raw-source header string.
        const archiveStateAnchor = `  const [showArchivedPo, setShowArchivedPo] = useState(false);`;
        if (!plannerCode.includes(archiveStateAnchor)) {
          throw new Error("[po-delivery] runtime state anchor missing");
        }
        if (!plannerCode.includes("poSyncProgress")) {
          plannerCode = plannerCode.replace(
            archiveStateAnchor,
            `${archiveStateAnchor}\n  const [poSyncProgress, setPoSyncProgress] = useState({ active: false, percent: 0, label: "Siap" });\n  const [calendarMonth, setCalendarMonth] = useState(today().slice(0, 7));\n  const [calendarPos, setCalendarPos] = useState([]);\n  const [calendarPo, setCalendarPo] = useState(null);`,
          );
        }

        // Never display late results from the previously selected site.
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

        const returnAnchor = `  return (\n    <div className="ops-domain-stack">`;
        if (!plannerCode.includes(returnAnchor)) {
          throw new Error("[po-delivery] OperationsPoPlanner return anchor missing");
        }

        if (!plannerCode.includes("syncPoReminderStages")) {
          const helperBlock = `  const mergeReminderRows = (baseRows, extraRows) => {\n    const merged = new Map();\n    [...(baseRows || []), ...(extraRows || [])].forEach((row) => {\n      const key = row.reminder_key || [row.site, row.vendor_code, row.po_date, row.procurement_bucket, ...(row.distribution_dates || [])].join("|");\n      merged.set(key, row);\n    });\n    return Array.from(merged.values());\n  };\n\n  const syncPoReminderStages = async () => {\n    setPoSyncProgress({ active: true, percent: 5, label: "Menyiapkan pengingat " + activeSite });\n    setError("");\n    let collected = [];\n    const failures = [];\n    const stages = [\n      { date: today(), percent: 50, label: "Menarik terlambat + hari ini" },\n      { date: shiftDate(today(), 1), percent: 100, label: "Menarik pengingat besok" },\n    ];\n    for (const stage of stages) {\n      setPoSyncProgress({ active: true, percent: Math.max(10, stage.percent - 35), label: stage.label });\n      try {\n        const result = await operationsApi.getPoReminders({ site: activeSite, date: stage.date, horizonDays: 1 });\n        collected = mergeReminderRows(collected, (result?.items || []).filter((row) => !row?.site || String(row.site).toUpperCase() === String(activeSite).toUpperCase()));\n        setReminders(collected);\n      } catch (err) {\n        failures.push(stage.label + ": " + (err.message || "gagal"));\n      }\n      setPoSyncProgress({ active: true, percent: stage.percent, label: stage.label + " selesai" });\n    }\n    setPoSyncProgress({ active: false, percent: 100, label: failures.length ? "Selesai sebagian" : "Sinkron selesai" });\n    if (failures.length) setError("Sebagian pengingat gagal: " + failures.join("; "));\n    else setMessage("Pengingat PO " + activeSite + " selesai disinkronkan bertahap.");\n  };\n\n  const syncAllPoBlocks = async () => {\n    setError("");\n    setPoSyncProgress({ active: true, percent: 5, label: "Memulai sinkron " + activeSite });\n    const failures = [];\n    try { setPoSyncProgress({ active: true, percent: 15, label: "1/4 · PO Aktual" }); await refreshPurchaseOrders(); } catch (err) { failures.push("PO Aktual: " + (err.message || "gagal")); }\n    try { setPoSyncProgress({ active: true, percent: 35, label: "2/4 · Barang belum datang" }); await refreshDeliveryAlerts(); } catch (err) { failures.push("Barang belum datang: " + (err.message || "gagal")); }\n    let collected = [];\n    try {\n      setPoSyncProgress({ active: true, percent: 55, label: "3/4 · Pengingat terlambat + hari ini" });\n      const current = await operationsApi.getPoReminders({ site: activeSite, date: today(), horizonDays: 1 });\n      collected = mergeReminderRows(collected, current?.items || []); setReminders(collected);\n    } catch (err) { failures.push("Pengingat hari ini: " + (err.message || "gagal")); }\n    try {\n      setPoSyncProgress({ active: true, percent: 80, label: "4/4 · Pengingat besok" });\n      const tomorrow = await operationsApi.getPoReminders({ site: activeSite, date: shiftDate(today(), 1), horizonDays: 1 });\n      collected = mergeReminderRows(collected, tomorrow?.items || []); setReminders(collected);\n    } catch (err) { failures.push("Pengingat besok: " + (err.message || "gagal")); }\n    setPoSyncProgress({ active: false, percent: 100, label: failures.length ? "Sinkron selesai sebagian" : "Semua blok tersinkron" });\n    if (failures.length) setError("Sinkron selesai sebagian: " + failures.join("; "));\n    else setMessage("Semua blok PO " + activeSite + " sudah disinkronkan.");\n  };\n\n  const calendarMonthBounds = (value) => {\n    const [year, month] = String(value || today().slice(0, 7)).split("-").map(Number);\n    const first = year + "-" + String(month).padStart(2, "0") + "-01";\n    const lastDay = new Date(year, month, 0).getDate();\n    const last = year + "-" + String(month).padStart(2, "0") + "-" + String(lastDay).padStart(2, "0");\n    return { year, month, first, last, lastDay };\n  };\n\n  const refreshPoCalendar = async () => {\n    const bounds = calendarMonthBounds(calendarMonth);\n    const result = await operationsApi.getPurchaseOrders({ site: activeSite, includeArchived: true, fromDate: bounds.first, toDate: bounds.last, limit: 500 });\n    setCalendarPos(result?.items || []);\n  };\n\n  const openCalendarPo = async (po) => {\n    setActionId(po.id);\n    try {\n      const detail = await operationsApi.getPurchaseOrder(po.id);\n      setCalendarPo({ ...po, ...detail });\n    } catch (err) { setError(err.message || "Gagal membuka PO dari kalender"); }\n    finally { setActionId(null); }\n  };\n\n  const calendarCells = useMemo(() => {\n    const bounds = calendarMonthBounds(calendarMonth);\n    const firstWeekDay = (new Date(bounds.year, bounds.month - 1, 1).getDay() + 6) % 7;\n    const cells = Array(firstWeekDay).fill(null);\n    for (let day = 1; day <= bounds.lastDay; day += 1) cells.push(String(day).padStart(2, "0"));\n    while (cells.length % 7) cells.push(null);\n    return cells;\n  }, [calendarMonth]);\n\n  const calendarPoByDate = useMemo(() => {\n    const mapped = new Map();\n    (calendarPos || []).forEach((po) => coverageDatesFor(po).forEach((dateValue) => {\n      const key = String(dateValue); if (!mapped.has(key)) mapped.set(key, []); mapped.get(key).push(po);\n    }));\n    return mapped;\n  }, [calendarPos]);\n\n  useEffect(() => {\n    let cancelled = false;\n    const bounds = calendarMonthBounds(calendarMonth);\n    operationsApi.getPurchaseOrders({ site: activeSite, includeArchived: true, fromDate: bounds.first, toDate: bounds.last, limit: 500 })\n      .then((result) => { if (!cancelled) setCalendarPos(result?.items || []); })\n      .catch(() => {});\n    return () => { cancelled = true; };\n  }, [activeSite, calendarMonth]);\n\n`;
          plannerCode = plannerCode.replace(returnAnchor, `${helperBlock}${returnAnchor}`);
        }

        // Reminder header: short stable anchor after runtime pre-transform.
        const reminderTitleAnchor = `<span className="ops-kicker">PENGINGAT PO BERDASARKAN LEAD TIME</span><h3>PO yang Harus Dikerjakan</h3>`;
        if (!plannerCode.includes(reminderTitleAnchor)) {
          throw new Error("[po-delivery] reminder title anchor missing");
        }
        plannerCode = plannerCode.replace(
          reminderTitleAnchor,
          `<span className="ops-kicker">PENGINGAT PO BERDASARKAN LEAD TIME</span><h3>PO yang Harus Dikerjakan</h3><div className="ops-row-actions" data-po-staged-sync="v24"><button className="ops-button-primary" type="button" onClick={syncPoReminderStages} disabled={poSyncProgress.active}><RefreshCw size={14} /> Tarik / Sinkron Pengingat</button><button type="button" onClick={refreshDeliveryAlerts} disabled={poSyncProgress.active}><RefreshCw size={14} /> Refresh Barang Datang</button></div>{poSyncProgress.percent > 0 && <div data-po-sync-progress="v24" style={{marginTop:8}}><div className="ops-muted">{poSyncProgress.label} · {poSyncProgress.percent}%</div><div style={{height:10,borderRadius:999,background:"rgba(127,127,127,.22)",overflow:"hidden"}}><div style={{height:"100%",width:poSyncProgress.percent + "%",background:"currentColor",transition:"width .25s ease"}} /></div></div>`,
        );

        // Add independent refresh controls to the actual PO section.
        const actualTitleAnchor = `<span className="ops-kicker">PO TERCATAT</span><h3>Purchase Order Aktual</h3>`;
        if (!plannerCode.includes(actualTitleAnchor)) {
          throw new Error("[po-delivery] actual PO title anchor missing");
        }
        plannerCode = plannerCode.replace(
          actualTitleAnchor,
          `<span className="ops-kicker">PO TERCATAT</span><h3>Purchase Order Aktual</h3><div className="ops-row-actions" data-po-actual-refresh="v24"><button type="button" onClick={() => refreshPurchaseOrders()} disabled={poSyncProgress.active}><RefreshCw size={14} /> Refresh PO Aktual</button><button className="ops-button-primary" type="button" onClick={syncAllPoBlocks} disabled={poSyncProgress.active}><RefreshCw size={14} /> Sinkron Semua Blok</button></div>`,
        );

        // Calendar is built from persisted PO rows; it does not call the expensive reminder engine.
        const detailAnchor = `        {viewingPo && <div className="ops-po-detail" id="po-detail-panel">`;
        if (!plannerCode.includes(detailAnchor)) {
          throw new Error("[po-delivery] PO detail anchor missing");
        }
        const calendarBlock = `        <div className="ops-draft-group" data-po-actual-calendar="v24">\n          <div className="ops-draft-group-head"><div><strong>Kalender PO Aktual</strong><span>PO ditempatkan pada tanggal distribusi. Klik PO untuk melihat dibuat kapan, pesan/kirim kapan, masak dan distribusi untuk kapan.</span></div><div className="ops-row-actions"><input type="month" value={calendarMonth} onChange={(e) => setCalendarMonth(e.target.value)} /><button type="button" onClick={refreshPoCalendar}><RefreshCw size={14} /> Refresh Kalender</button></div></div>\n          <div style={{display:"grid",gridTemplateColumns:"repeat(7,minmax(0,1fr))",gap:6,marginTop:10}}>{["Sen","Sel","Rab","Kam","Jum","Sab","Min"].map((day) => <strong key={day} className="ops-muted" style={{textAlign:"center"}}>{day}</strong>)}{calendarCells.map((day, index) => { const dateValue = day ? calendarMonth + "-" + day : ""; const dayPos = dateValue ? (calendarPoByDate.get(dateValue) || []) : []; return <div key={index} style={{minHeight:86,border:"1px solid rgba(127,127,127,.25)",borderRadius:8,padding:6,opacity:day ? 1 : .25}}>{day && <><strong>{Number(day)}</strong>{dayPos.map((po) => <button key={po.id + "-" + dateValue} type="button" onClick={() => openCalendarPo(po)} style={{display:"block",width:"100%",marginTop:5,textAlign:"left",whiteSpace:"normal"}}><strong>{po.vendor_code}</strong><div className="ops-muted">{po.po_code}</div><div className="ops-muted">PO dibuat {compactTimestamp(po.created_at).slice(0,10)}</div></button>)}</>}</div>; })}</div>\n        </div>\n        {calendarPo && <div data-po-calendar-popup="v24" style={{position:"fixed",inset:0,zIndex:10000,background:"rgba(0,0,0,.55)",display:"flex",alignItems:"center",justifyContent:"center",padding:18}} onClick={() => setCalendarPo(null)}><div className="ops-module" style={{width:"min(760px,96vw)",maxHeight:"88vh",overflow:"auto"}} onClick={(e) => e.stopPropagation()}><div className="ops-draft-group-head"><div><strong>{calendarPo.po_code} · Rev {calendarPo.revision_no}</strong><span>{calendarPo.vendor_code} · {calendarPo.status}</span></div><button type="button" onClick={() => setCalendarPo(null)}><XCircle size={14} /> Tutup</button></div><div className="ops-summary-strip"><span>PO dibuat <strong>{compactTimestamp(calendarPo.created_at) || "-"}</strong></span><span>Jadwal pesan/kirim <strong>{calendarPo.scheduled_order_date || "Lead time belum diatur"}</strong></span><span>Masak <strong>{calendarPo.cooking_date || "-"}</strong></span><span>Distribusi <strong>{coverageLabel(calendarPo)}</strong></span><span>Status <strong>{calendarPo.status}</strong></span></div><h4>Pesanan</h4><div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Barang</th><th>Qty</th><th>Unit</th></tr></thead><tbody>{(calendarPo.items || []).map((item, index) => <tr key={item.id || index}><td>{item.item_name}</td><td>{qty(item.po_qty)}</td><td>{item.unit || "-"}</td></tr>)}</tbody></table></div>{(calendarPo.coverage || []).length > 0 && <><h4>Masak untuk kapan</h4><div className="ops-coverage-grid">{calendarPo.coverage.map((day, index) => <div className="ops-notice" key={String(day.distribution_date) + index}>Masak <strong>{String(day.cooking_date || calendarPo.cooking_date || "-")}</strong> → distribusi <strong>{String(day.distribution_date || "-")}</strong></div>)}</div></>}</div></div>}\n`;
        plannerCode = plannerCode.replace(detailAnchor, `${calendarBlock}${detailAnchor}`);

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
