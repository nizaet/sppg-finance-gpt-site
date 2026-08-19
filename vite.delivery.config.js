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

        const oldSequence = `      await refreshPurchaseOrders();\n      await refreshReminders();\n      await refreshDeliveryAlerts();\n      setMessage(result?.message || \`\${label} tersimpan.\`);`;
        if (plannerCode.includes(oldSequence)) {
          const newSequence = `      if (!result?.saved) throw new Error(result?.message || \`Konfirmasi \${label} belum tersimpan.\`);\n      setDeliveryAlerts((current) => current.filter((row) => row.purchaseOrderId !== alert.purchaseOrderId));\n      try {\n        await refreshDeliveryAlerts();\n      } catch (alertRefreshError) {\n        console.warn("Delivery alert saved but alert refresh failed", alertRefreshError);\n      }\n      const secondaryRefresh = await Promise.allSettled([refreshPurchaseOrders(), refreshReminders()]);\n      const failedRefreshes = secondaryRefresh.filter((entry) => entry.status === "rejected");\n      setMessage((result?.message || \`\${label} tersimpan.\`) + (failedRefreshes.length ? " Data PO/pengingat akan diperbarui saat refresh berikutnya." : ""));`;
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

        // Staged sync state + interactive PO calendar state.
        const stateAnchor = `  const [reminderActionKey, setReminderActionKey] = useState("");`;
        if (plannerCode.includes(stateAnchor) && !plannerCode.includes("poSyncProgress")) {
          plannerCode = plannerCode.replace(
            stateAnchor,
            `${stateAnchor}\n  const [poSyncProgress, setPoSyncProgress] = useState({ running: false, step: 0, total: 0, label: "" });\n  const [calendarMonth, setCalendarMonth] = useState(today().slice(0, 7));\n  const [calendarPo, setCalendarPo] = useState(null);\n  const [calendarPoLoading, setCalendarPoLoading] = useState(false);`,
          );
        }

        const syncInsertAnchor = `  const reducedByStock = draftItems.filter((x) => Number(x.stock_qty || 0) > 0 && Number(x.recommended_po_qty) < Number(x.planned_qty)).length;`;
        if (plannerCode.includes(syncInsertAnchor) && !plannerCode.includes("syncPoBlocks")) {
          const stagedHelpers = `  const syncPoBlocks = async (scope = "all") => {\n    const steps = scope === "po"\n      ? [{ label: "PO Aktual", run: async () => { const data = await operationsApi.getPurchaseOrders({ site: activeSite, limit: 80, fromDate: shiftDate(today(), -7), toDate: shiftDate(today(), 31), includeArchived: true }); setPurchaseOrders(data?.items || []); } }]\n      : scope === "alerts"\n        ? [{ label: "Barang belum datang", run: async () => { const data = await operationsApi.getPoDeliveryAlerts({ site: activeSite, date: today(), minimumHour: 17 }); setDeliveryAlerts(data?.items || []); } }]\n        : scope === "reminders"\n          ? [\n              { label: "Pengingat terlambat + hari ini", run: async () => operationsApi.getPoReminders({ site: activeSite, date: today(), horizonDays: 1 }) },\n              { label: "Pengingat besok", run: async () => operationsApi.getPoReminders({ site: activeSite, date: shiftDate(today(), 1), horizonDays: 1 }) },\n            ]\n          : [\n              { label: "PO Aktual", run: async () => { const data = await operationsApi.getPurchaseOrders({ site: activeSite, limit: 80, fromDate: shiftDate(today(), -7), toDate: shiftDate(today(), 31), includeArchived: true }); setPurchaseOrders(data?.items || []); } },\n              { label: "Barang belum datang", run: async () => { const data = await operationsApi.getPoDeliveryAlerts({ site: activeSite, date: today(), minimumHour: 17 }); setDeliveryAlerts(data?.items || []); } },\n              { label: "Pengingat terlambat + hari ini", run: async () => operationsApi.getPoReminders({ site: activeSite, date: today(), horizonDays: 1 }) },\n              { label: "Pengingat besok", run: async () => operationsApi.getPoReminders({ site: activeSite, date: shiftDate(today(), 1), horizonDays: 1 }) },\n            ];\n    setError("");\n    setMessage("");\n    setPoSyncProgress({ running: true, step: 0, total: steps.length, label: "Mulai sinkron..." });\n    const reminderSets = [];\n    const failures = [];\n    for (let index = 0; index < steps.length; index += 1) {\n      const step = steps[index];\n      setPoSyncProgress({ running: true, step: index, total: steps.length, label: step.label });\n      try {\n        const result = await step.run();\n        if (scope === "reminders" || (scope === "all" && index >= 2)) reminderSets.push(result?.items || []);\n      } catch (err) {\n        failures.push(step.label + ": " + (err?.message || "gagal"));\n      }\n      setPoSyncProgress({ running: true, step: index + 1, total: steps.length, label: step.label + " selesai" });\n    }\n    if (reminderSets.length) {\n      const merged = new Map();\n      reminderSets.flat().forEach((item) => {\n        const key = item.reminder_key || [item.site, item.vendor_code, item.po_date, ...(item.distribution_dates || [])].join("|");\n        merged.set(key, item);\n      });\n      setReminders(Array.from(merged.values()).filter((item) => !item?.site || String(item.site).toUpperCase() === String(activeSite).toUpperCase()));\n    }\n    setPoSyncProgress({ running: false, step: steps.length, total: steps.length, label: failures.length ? "Selesai dengan sebagian error" : "Sinkron selesai" });\n    if (failures.length) setError(failures.join(" · "));\n    else setMessage((scope === "all" ? "Semua blok PO" : scope === "po" ? "PO Aktual" : scope === "alerts" ? "Peringatan barang" : "Pengingat PO") + " " + activeSite + " sudah disinkronkan.");\n  };\n\n  const shiftCalendarMonth = (delta) => {\n    const base = new Date(calendarMonth + "-01T12:00:00");\n    base.setMonth(base.getMonth() + delta);\n    setCalendarMonth(base.toISOString().slice(0, 7));\n  };\n\n  const calendarCells = useMemo(() => {\n    const first = new Date(calendarMonth + "-01T12:00:00");\n    const start = new Date(first);\n    start.setDate(1 - first.getDay());\n    return Array.from({ length: 42 }, (_, index) => {\n      const day = new Date(start);\n      day.setDate(start.getDate() + index);\n      const key = day.toISOString().slice(0, 10);\n      return { key, day: day.getDate(), inMonth: key.slice(0, 7) === calendarMonth, pos: purchaseOrders.filter((po) => coverageDatesFor(po).includes(key)) };\n    });\n  }, [calendarMonth, purchaseOrders]);\n\n  const openCalendarPo = async (po) => {\n    setCalendarPoLoading(true);\n    setError("");\n    try {\n      const detail = await operationsApi.getPurchaseOrder(po.id);\n      setCalendarPo({ ...po, ...detail });\n    } catch (err) {\n      setError(err.message || "Gagal membuka PO kalender");\n    } finally {\n      setCalendarPoLoading(false);\n    }\n  };\n\n${syncInsertAnchor}`;
          plannerCode = plannerCode.replace(syncInsertAnchor, stagedHelpers);
        }

        // Robust reminder sync control: anchor on the icon instead of exact header text.
        if (!plannerCode.includes("data-po-staged-sync=\"reminders\"")) {
          const bellAnchor = `<BellRing size={32} />`;
          if (plannerCode.includes(bellAnchor)) {
            plannerCode = plannerCode.replace(
              bellAnchor,
              `<div className="ops-row-actions" data-po-staged-sync="reminders"><button type="button" onClick={() => syncPoBlocks("reminders")} disabled={poSyncProgress.running}><RefreshCw size={14} /> Tarik / Sinkron Pengingat</button>${bellAnchor}</div>`,
            );
          }
        }

        // Progress bar directly below the lead-time reminder header.
        const reminderSectionAnchor = `<span className="ops-kicker">PENGINGAT PO BERDASARKAN LEAD TIME</span>`;
        if (plannerCode.includes(reminderSectionAnchor) && !plannerCode.includes("data-po-sync-progress")) {
          const headerClose = plannerCode.indexOf(`</div>`, plannerCode.indexOf(reminderSectionAnchor));
          if (headerClose >= 0) {
            const insertAt = headerClose + 6;
            plannerCode = plannerCode.slice(0, insertAt) + `<div data-po-sync-progress="v24" style={{marginTop:10}}>{poSyncProgress.total > 0 && <><div className="ops-muted">{poSyncProgress.label} · {poSyncProgress.step}/{poSyncProgress.total}</div><div style={{height:10,borderRadius:999,overflow:"hidden",background:"rgba(127,127,127,.18)"}}><div style={{height:"100%",width:((poSyncProgress.step / Math.max(1, poSyncProgress.total)) * 100) + "%",background:"currentColor",transition:"width .25s ease"}} /></div></>}</div>` + plannerCode.slice(insertAt);
          }
        }

        // Dedicated refresh control on PO Aktual header.
        const actualHeader = `<div><span className="ops-kicker">PO TERCATAT</span><h3>Purchase Order Aktual</h3>`;
        if (plannerCode.includes(actualHeader) && !plannerCode.includes("data-po-staged-sync=\"actual\"")) {
          plannerCode = plannerCode.replace(
            actualHeader,
            `<div><span className="ops-kicker">PO TERCATAT</span><h3>Purchase Order Aktual</h3><div className="ops-row-actions" data-po-staged-sync="actual"><button type="button" onClick={() => syncPoBlocks("po")} disabled={poSyncProgress.running}><RefreshCw size={14} /> Refresh PO Aktual</button><button type="button" onClick={() => syncPoBlocks("all")} disabled={poSyncProgress.running}><RefreshCw size={14} /> Sinkron Semua Blok</button></div>`,
          );
        }

        // Calendar built from already-loaded actual POs; clicking one opens a modal.
        const actualDetailAnchor = `{viewingPo && <div className="ops-po-detail" id="po-detail-panel">`;
        if (plannerCode.includes(actualDetailAnchor) && !plannerCode.includes("data-po-actual-calendar")) {
          const calendarBlock = `<div className="ops-draft-group" data-po-actual-calendar="v24"><div className="ops-draft-group-head"><div><strong>Kalender PO Aktual · {activeSite}</strong><span>PO ditempatkan pada tanggal distribusi. Di setiap event terlihat tanggal PO dibuat; klik untuk rincian tanggal pesan, masak, distribusi, status, dan item.</span></div><div className="ops-row-actions"><button type="button" onClick={() => shiftCalendarMonth(-1)}>‹ Bulan lalu</button><strong>{calendarMonth}</strong><button type="button" onClick={() => shiftCalendarMonth(1)}>Bulan depan ›</button></div></div><div style={{display:"grid",gridTemplateColumns:"repeat(7,minmax(0,1fr))",gap:6,marginTop:10}}>{["Min","Sen","Sel","Rab","Kam","Jum","Sab"].map((name) => <div key={name} className="ops-muted" style={{textAlign:"center",padding:6}}>{name}</div>)}{calendarCells.map((cell) => <div key={cell.key} style={{minHeight:100,border:"1px solid rgba(127,127,127,.25)",borderRadius:8,padding:6,opacity:cell.inMonth?1:.45,overflow:"hidden"}}><div style={{fontWeight:700,marginBottom:4}}>{cell.day}</div>{cell.pos.slice(0,5).map((po) => <button key={po.id} type="button" onClick={() => openCalendarPo(po)} style={{display:"block",width:"100%",textAlign:"left",marginBottom:4,padding:"5px 6px",borderRadius:6,border:"1px solid rgba(127,127,127,.22)",background:"transparent"}}><strong>{po.vendor_code}</strong><div className="ops-muted">{po.po_code}</div><div className="ops-muted">dibuat {String(po.created_at || "-").slice(0,10)}</div></button>)}{cell.pos.length > 5 && <div className="ops-muted">+{cell.pos.length - 5} PO lagi</div>}</div>)}</div></div>{calendarPoLoading && <div className="ops-notice">Membuka rincian PO kalender…</div>}{calendarPo && <div role="dialog" aria-modal="true" data-po-calendar-popup="v24" style={{position:"fixed",inset:0,zIndex:2000,background:"rgba(0,0,0,.55)",display:"flex",alignItems:"center",justifyContent:"center",padding:18}} onClick={() => setCalendarPo(null)}><div className="ops-module" style={{width:"min(760px,96vw)",maxHeight:"86vh",overflow:"auto",margin:0}} onClick={(event) => event.stopPropagation()}><div className="ops-draft-group-head"><div><strong>{calendarPo.po_code} · Rev {calendarPo.revision_no}</strong><span>{calendarPo.vendor_code} · {calendarPo.status}</span></div><button type="button" onClick={() => setCalendarPo(null)}><XCircle size={14} /> Tutup</button></div><div className="ops-summary-strip"><span>PO dibuat <strong>{String(calendarPo.created_at || "-").slice(0,10)}</strong></span><span>Jadwal pesan/kirim <strong>{calendarPo.scheduled_order_date || "Lead time belum diatur"}</strong></span><span>Masak <strong>{calendarPo.cooking_date || String(calendarPo.cooking_at || "-").slice(0,10)}</strong></span><span>Untuk distribusi <strong>{coverageLabel(calendarPo)}</strong></span><span>Status <strong>{calendarPo.status}</strong></span></div>{(calendarPo.coverage || []).length > 0 && <div><h4>Masak & distribusi per tanggal</h4>{calendarPo.coverage.map((day) => <div key={String(day.distribution_date)} className="ops-notice">Masak <strong>{String(day.cooking_date || "-")}</strong> → Distribusi <strong>{String(day.distribution_date)}</strong></div>)}</div>}<h4>Pesanan</h4><div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Barang</th><th>Qty</th><th>Unit</th></tr></thead><tbody>{(calendarPo.items || []).map((item, index) => <tr key={item.id || index}><td><strong>{item.item_name}</strong></td><td>{qty(item.po_qty)}</td><td>{item.unit || "-"}</td></tr>)}</tbody></table></div></div></div>}`;
          plannerCode = plannerCode.replace(actualDetailAnchor, `${calendarBlock}${actualDetailAnchor}`);
        }

        // Alert block gets its own refresh button after runtime alert insertion.
        plannerCode = plannerCode.replace(
          `<strong>⚠ Peringatan barang belum datang setelah jam 17.00</strong>`,
          `<strong>⚠ Peringatan barang belum datang setelah jam 17.00</strong><div className="ops-row-actions" data-po-staged-sync="alerts"><button type="button" onClick={() => syncPoBlocks("alerts")} disabled={poSyncProgress.running}><RefreshCw size={13} /> Refresh Barang Datang</button></div>`,
        );

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
