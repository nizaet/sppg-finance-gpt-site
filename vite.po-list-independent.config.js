import baseConfig from "./vite.flowviews4.config.js";
import financeUiPlacementPlugin from "./vite.finance-ui-placement.js";

function poListIndependentPlugin() {
  return {
    name: "sppg-po-list-independent-v2",
    // This plugin rewrites raw JSX/source markers. It must run before React/Vite
    // compiles OperationsPoPlanner, otherwise the string anchors no longer exist.
    enforce: "pre",
    transform(code, id) {
      if (!id.includes("/src/operations/OperationsPoPlanner.jsx")) return null;
      let out = code;

      if (!out.includes("poListLoading")) {
        out = out.replace(
          '  const [loading, setLoading] = useState(false);',
          '  const [loading, setLoading] = useState(false);\n  const [poListLoading, setPoListLoading] = useState(false);\n  const [poListLoaded, setPoListLoaded] = useState(false);'
        );
      }

      if (!out.includes("activeSiteRef.current = activeSite")) {
        out = out.replace(
          '  const activeSite = fixedSite || site;',
          '  const activeSite = fixedSite || site;\n  const activeSiteRef = React.useRef(activeSite);\n  activeSiteRef.current = activeSite;'
        );
      }

      const helperMarker = '  const loadBase = async () => {';
      if (out.includes(helperMarker) && !out.includes("const refreshPoListOnly = async")) {
        const helper = `  const poListBounds = () => {\n    const isoLocal = (value) => {\n      const d = new Date(value);\n      const shifted = new Date(d.getTime() - d.getTimezoneOffset() * 60000);\n      return shifted.toISOString().slice(0, 10);\n    };\n    const now = new Date();\n    const from = new Date(now);\n    const to = new Date(now);\n    from.setDate(from.getDate() - 31);\n    to.setDate(to.getDate() + 92);\n    return { fromDate: isoLocal(from), toDate: isoLocal(to) };\n  };\n\n  const refreshPoListOnly = async () => {\n    const requestedSite = activeSite;\n    const bounds = poListBounds();\n    setPoListLoading(true);\n    try {\n      const poData = await operationsApi.getPurchaseOrders({\n        site: requestedSite,\n        includeArchived: true,\n        fromDate: bounds.fromDate,\n        toDate: bounds.toDate,\n        limit: 500,\n      });\n      if (String(activeSiteRef.current || "").toUpperCase() !== String(requestedSite || "").toUpperCase()) return poData;\n      const rows = (poData?.items || []).filter((po) => !po?.site || String(po.site).toUpperCase() === String(requestedSite).toUpperCase());\n      setPurchaseOrders(rows);\n      setPoListLoaded(true);\n      return poData;\n    } catch (err) {\n      setError("Gagal refresh List PO. " + (err.message || ""));\n      throw err;\n    } finally {\n      setPoListLoading(false);\n    }\n  };\n\n`;
        out = out.replace(helperMarker, helper + helperMarker);
      }

      out = out.replace(
        '    setPurchaseOrders([]);\n    setReminders([]);',
        '    setPurchaseOrders([]);\n    setPoListLoaded(false);\n    setReminders([]);'
      );

      const loadBasePattern = /  const loadBase = async \(\) => \{[\s\S]*?\n  \};\n\n  const pullDailyData = async \(\) => \{/;
      if (loadBasePattern.test(out)) {
        const replacement = `  const loadBase = async () => {\n    setLoading(true);\n    setError("");\n    setReminders([]);\n    try {\n      const [poResult, vendorResult] = await Promise.allSettled([\n        refreshPoListOnly(),\n        operationsApi.getReferenceVendors(activeSite),\n      ]);\n\n      if (vendorResult.status === "fulfilled") {\n        const vendorsData = vendorResult.value;\n        const uniqueVendors = new Map(FALLBACK_VENDORS.map(([code, name]) => [code, { code, name }]));\n        (vendorsData?.items || []).forEach((item) => {\n          if (item?.code) uniqueVendors.set(String(item.code).toUpperCase(), { code: String(item.code).toUpperCase(), name: item.name || item.code });\n        });\n        setVendorOptions(Array.from(uniqueVendors.values()).sort((a, b) => a.name.localeCompare(b.name, "id")));\n        const phones = {};\n        (vendorsData?.items || []).forEach((item) => {\n          if (item?.code && item?.metadata?.whatsapp_phone) phones[String(item.code).toUpperCase()] = String(item.metadata.whatsapp_phone);\n        });\n        setVendorPhones(phones);\n        setPhoneValue(phones[phoneVendor] || "");\n      } else {\n        setError("Daftar vendor belum termuat. " + (vendorResult.reason?.message || ""));\n      }\n\n      if (poResult.status === "rejected" && vendorResult.status === "rejected") {\n        setError("List PO dan vendor belum termuat. Gunakan Refresh List PO; pengingat dapat ditarik terpisah.");\n      }\n      // Reminder deliberately does not block the saved-PO list.\n    } finally {\n      setLoading(false);\n    }\n  };\n\n  const pullDailyData = async () => {`;
        out = out.replace(loadBasePattern, replacement);
      }

      const refreshPattern = /  const refreshPurchaseOrders = async \(\) => \{[\s\S]*?\n  \};/;
      if (refreshPattern.test(out)) {
        out = out.replace(
          refreshPattern,
          '  const refreshPurchaseOrders = async () => {\n    await refreshPoListOnly();\n  };'
        );
      }

      out = out.replaceAll(
        '      const poData = await operationsApi.getPurchaseOrders({ site: activeSite, limit: 50 });\n      setPurchaseOrders(poData?.items || []);',
        '      await refreshPoListOnly();'
      );

      const listHeader = '<div><span className="ops-kicker">PO TERCATAT</span><h3>Purchase Order Aktual</h3><p>Planning, stok, PO, receiving, invoice dan pembayaran tetap layer terpisah.</p></div>\n        </div>';
      if (out.includes(listHeader) && !out.includes('data-refresh-po-list="v2"')) {
        out = out.replace(
          listHeader,
          '<div><span className="ops-kicker">PO TERCATAT</span><h3>Purchase Order Aktual</h3><p>Planning, stok, PO, receiving, invoice dan pembayaran tetap layer terpisah. List membaca periode operasional lintas bulan agar PO akhir bulan dan awal bulan berikutnya tidak hilang.</p></div>\n          <div className="ops-row-actions"><button data-refresh-po-list="v2" type="button" onClick={refreshPoListOnly} disabled={poListLoading}><RefreshCw size={14} /> {poListLoading ? "Memuat List…" : "Refresh List PO"}</button></div>\n        </div>'
        );
      }

      out = out.replace(
        '{!loading && purchaseOrders.length === 0 && <tr><td colSpan="9" className="ops-empty-cell">Belum ada PO tercatat untuk site ini.</td></tr>}',
        '{!poListLoading && !poListLoaded && <tr><td colSpan="9" className="ops-empty-cell">List PO belum ditarik. Tekan Refresh List PO bila ingin memuatnya.</td></tr>}{!poListLoading && poListLoaded && purchaseOrders.length === 0 && <tr><td colSpan="9" className="ops-empty-cell">Tidak ada PO tercatat untuk site ini pada periode operasional.</td></tr>}'
      );

      return out === code ? null : { code: out, map: null };
    },
  };
}

function poCalendarCrossMonthPlugin() {
  return {
    name: "sppg-po-calendar-cross-month-v1",
    enforce: "pre",
    transform(code, id) {
      if (!id.includes("/src/operations/PoOpsEnhancements.jsx")) return null;
      let out = code;

      const refreshActualOld = `  const refreshActualPo = async () => {\n    const bounds = monthBounds(calendarMonth || today().slice(0, 7));\n    const result = await operationsApi.getPurchaseOrders({\n      site: activeSite,\n      limit: 500,\n      fromDate: bounds.first,\n      toDate: bounds.last,\n    });\n    setPurchaseOrders?.(activePoRows(result?.items || []));\n    setPoListLoaded?.(true);\n  };`;
      const refreshActualNew = `  const refreshActualPo = async () => {\n    const fromDate = shiftDate(today(), -31);\n    const toDate = shiftDate(today(), 92);\n    const result = await operationsApi.getPurchaseOrders({\n      site: activeSite,\n      includeArchived: true,\n      limit: 500,\n      fromDate,\n      toDate,\n    });\n    setPurchaseOrders?.(activePoRows(result?.items || []));\n    setPoListLoaded?.(true);\n  };`;
      out = out.replace(refreshActualOld, refreshActualNew);

      const calendarLogicPattern = /  const refreshCalendar = async \(\) => \{[\s\S]*?\n  \}, \[calendarMonth\]\);/;
      const calendarLogicNew = `  const visibleCalendarBounds = () => {\n    const bounds = monthBounds(calendarMonth);\n    const firstWeekDay = (new Date(bounds.year, bounds.month - 1, 1).getDay() + 6) % 7;\n    const usedCells = firstWeekDay + bounds.lastDay;\n    const trailingDays = (7 - (usedCells % 7)) % 7;\n    return {\n      ...bounds,\n      firstVisible: shiftDate(bounds.first, -firstWeekDay),\n      lastVisible: shiftDate(bounds.last, trailingDays),\n    };\n  };\n\n  const refreshCalendar = async () => {\n    const bounds = visibleCalendarBounds();\n    const result = await operationsApi.getPurchaseOrders({\n      site: activeSite,\n      includeArchived: true,\n      fromDate: bounds.firstVisible,\n      toDate: bounds.lastVisible,\n      limit: 500,\n    });\n    const rows = result?.items || [];\n    setCalendarPos(rows);\n  };\n\n  const calendarCells = useMemo(() => {\n    const bounds = visibleCalendarBounds();\n    const cells = [];\n    let cursor = bounds.firstVisible;\n    while (cursor <= bounds.lastVisible) {\n      cells.push({\n        date: cursor,\n        day: Number(cursor.slice(8, 10)),\n        inMonth: cursor.slice(0, 7) === calendarMonth,\n      });\n      cursor = shiftDate(cursor, 1);\n    }\n    return cells;\n  }, [calendarMonth]);`;
      out = out.replace(calendarLogicPattern, calendarLogicNew);

      const renderPattern = /\{calendarCells\.map\(\(day, index\) => \{[\s\S]*?\n        \}\)\}/;
      const renderNew = `{calendarCells.map((cell, index) => {\n          const dateValue = cell.date;\n          const dayPos = poByDate.get(dateValue) || [];\n          const monthLabel = new Date(\`${'${dateValue}'}T12:00:00\`).toLocaleDateString("id-ID", { month: "short" });\n          return (\n            <div key={dateValue || index} style={{ minHeight: 86, border: "1px solid rgba(127,127,127,.25)", borderRadius: 8, padding: 6, opacity: cell.inMonth ? 1 : 0.72, background: cell.inMonth ? undefined : "rgba(127,127,127,.06)" }}>\n              <div style={{ display: "flex", gap: 4, alignItems: "baseline" }}>\n                <strong>{cell.day}</strong>\n                {!cell.inMonth && <span className="ops-muted" style={{ fontSize: 10 }}>{monthLabel}</span>}\n              </div>\n              {dayPos.map((po) => (\n                <button key={\`${'${po.id}'}-${'${dateValue}'}\`} type="button" onClick={() => openCalendarPo(po)} style={{ display: "block", width: "100%", marginTop: 5, textAlign: "left", whiteSpace: "normal" }}>\n                  <strong>{po.vendor_code}</strong>\n                  <div className="ops-muted">{po.po_code}</div>\n                  <div className="ops-muted">PO dibuat {compactTimestamp(po.created_at).slice(0, 10)}</div>\n                </button>\n              ))}\n            </div>\n          );\n        })}`;
      out = out.replace(renderPattern, renderNew);

      return out === code ? null : { code: out, map: null };
    },
  };
}

// The Cemplang accountant module can pass through the inherited transform more
// than once while Vite resolves the query-suffixed App.jsx module. Once the
// transform has already installed the fixed Cemplang runtime site, running the
// brittle exact-string replacement a second time used to abort the entire MAJA
// production build. Wrap that inherited plugin so the transform is idempotent.
const inheritedPlugins = (baseConfig.plugins || []).map((plugin) => {
  if (plugin?.name !== "sppg-cemplang-accountant-variant" || typeof plugin.transform !== "function") {
    return plugin;
  }
  const originalTransform = plugin.transform;
  return {
    ...plugin,
    transform(code, id, ...rest) {
      const isCemplangAccountant = id.includes("/src/App.jsx?cemplang-accountant");
      const alreadyTransformed =
        code.includes('siteId: "sppg-cemplang2-gpt-site"') &&
        !code.includes("const runtimeSite = RUNTIME_HOST_SITE_MAP[currentHostname] || null;");
      if (isCemplangAccountant && alreadyTransformed) return null;
      return originalTransform.call(this, code, id, ...rest);
    },
  };
});

export default {
  ...baseConfig,
  plugins: [...inheritedPlugins, poListIndependentPlugin(), poCalendarCrossMonthPlugin(), financeUiPlacementPlugin()],
};