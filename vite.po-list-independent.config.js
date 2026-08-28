import baseConfig from "./vite.flowviews4.config.js";

function poListIndependentPlugin() {
  return {
    name: "sppg-po-list-independent-v1",
    enforce: "post",
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
        const helper = `  const currentPoMonthBounds = () => {\n    const now = new Date();\n    const year = now.getFullYear();\n    const month = now.getMonth() + 1;\n    const mm = String(month).padStart(2, "0");\n    const lastDay = new Date(year, month, 0).getDate();\n    return { fromDate: year + "-" + mm + "-01", toDate: year + "-" + mm + "-" + String(lastDay).padStart(2, "0") };\n  };\n\n  const refreshPoListOnly = async () => {\n    const requestedSite = activeSite;\n    const bounds = currentPoMonthBounds();\n    setPoListLoading(true);\n    try {\n      const poData = await operationsApi.getPurchaseOrders({\n        site: requestedSite,\n        includeArchived: true,\n        fromDate: bounds.fromDate,\n        toDate: bounds.toDate,\n        limit: 500,\n      });\n      if (String(activeSiteRef.current || "").toUpperCase() !== String(requestedSite || "").toUpperCase()) return poData;\n      const rows = (poData?.items || []).filter((po) => !po?.site || String(po.site).toUpperCase() === String(requestedSite).toUpperCase());\n      setPurchaseOrders(rows);\n      setPoListLoaded(true);\n      return poData;\n    } catch (err) {\n      setError("Gagal refresh List PO. " + (err.message || ""));\n      throw err;\n    } finally {\n      setPoListLoading(false);\n    }\n  };\n\n`;
        out = out.replace(helperMarker, helper + helperMarker);
      }

      out = out.replace(
        '    setPurchaseOrders([]);\n    setReminders([]);',
        '    setPurchaseOrders([]);\n    setPoListLoaded(false);\n    setReminders([]);'
      );

      const loadBasePattern = /  const loadBase = async \(\) => \{[\s\S]*?\n  \};\n\n  const pullDailyData = async \(\) => \{/;
      if (loadBasePattern.test(out)) {
        const replacement = `  const loadBase = async () => {\n    setLoading(true);\n    setError("");\n    setReminders([]);\n    try {\n      const [poResult, vendorResult] = await Promise.allSettled([\n        refreshPoListOnly(),\n        operationsApi.getReferenceVendors(activeSite),\n      ]);\n\n      if (vendorResult.status === "fulfilled") {\n        const vendorsData = vendorResult.value;\n        const uniqueVendors = new Map(FALLBACK_VENDORS.map(([code, name]) => [code, { code, name }]));\n        (vendorsData?.items || []).forEach((item) => {\n          if (item?.code) uniqueVendors.set(String(item.code).toUpperCase(), { code: String(item.code).toUpperCase(), name: item.name || item.code });\n        });\n        setVendorOptions(Array.from(uniqueVendors.values()).sort((a, b) => a.name.localeCompare(b.name, "id")));\n        const phones = {};\n        (vendorsData?.items || []).forEach((item) => {\n          if (item?.code && item?.metadata?.whatsapp_phone) phones[String(item.code).toUpperCase()] = String(item.metadata.whatsapp_phone);\n        });\n        setVendorPhones(phones);\n        setPhoneValue(phones[phoneVendor] || "");\n      } else {\n        setError("Daftar vendor belum termuat. " + (vendorResult.reason?.message || ""));\n      }\n\n      if (poResult.status === "rejected" && vendorResult.status === "rejected") {\n        setError("List PO dan vendor belum termuat. Gunakan Refresh List PO; pengingat dapat ditarik terpisah.");\n      }\n      // Reminder sengaja TIDAK ditunggu di sini. Endpoint reminder dapat berat dan\n      // mempunyai tombol Tarik / Sinkron Pengingat sendiri. List PO harus tetap cepat.\n    } finally {\n      setLoading(false);\n    }\n  };\n\n  const pullDailyData = async () => {`;
        out = out.replace(loadBasePattern, replacement);
      }

      const refreshPattern = /  const refreshPurchaseOrders = async \(\) => \{[\s\S]*?\n  \};/;
      if (refreshPattern.test(out)) {
        out = out.replace(
          refreshPattern,
          '  const refreshPurchaseOrders = async () => {\n    await refreshPoListOnly();\n  };'
        );
      }

      out = out.replace(
        '      const poData = await operationsApi.getPurchaseOrders({ site: activeSite, limit: 50 });\n      setPurchaseOrders(poData?.items || []);',
        '      await refreshPoListOnly();'
      );

      const listHeader = '<div><span className="ops-kicker">PO TERCATAT</span><h3>Purchase Order Aktual</h3><p>Planning, stok, PO, receiving, invoice dan pembayaran tetap layer terpisah.</p></div>\n        </div>';
      if (out.includes(listHeader) && !out.includes('data-refresh-po-list="v1"')) {
        out = out.replace(
          listHeader,
          '<div><span className="ops-kicker">PO TERCATAT</span><h3>Purchase Order Aktual</h3><p>Planning, stok, PO, receiving, invoice dan pembayaran tetap layer terpisah. List membaca seluruh bulan berjalan dan tidak menunggu pengingat.</p></div>\n          <div className="ops-row-actions"><button data-refresh-po-list="v1" type="button" onClick={refreshPoListOnly} disabled={poListLoading}><RefreshCw size={14} /> {poListLoading ? "Memuat List…" : "Refresh List PO"}</button></div>\n        </div>'
        );
      }

      out = out.replace(
        '{!loading && purchaseOrders.length === 0 && <tr><td colSpan="9" className="ops-empty-cell">Belum ada PO tercatat untuk site ini.</td></tr>}',
        '{!poListLoading && !poListLoaded && <tr><td colSpan="9" className="ops-empty-cell">List PO belum ditarik. Tekan Refresh List PO bila ingin memuatnya.</td></tr>}{!poListLoading && poListLoaded && purchaseOrders.length === 0 && <tr><td colSpan="9" className="ops-empty-cell">Tidak ada PO tercatat untuk site ini.</td></tr>}'
      );

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
  plugins: [...inheritedPlugins, poListIndependentPlugin()],
};
