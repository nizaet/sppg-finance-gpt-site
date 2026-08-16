import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

function poPlannerVariant() {
  return {
    name: "sppg-po-planner-ui",
    enforce: "pre",
    transform(code, id) {
      if (id.includes("/src/operations/apiClient.js")) {
        const next = code.replace("/v1/po-reminders?", "/v1/po-reminders-v2?");
        if (next === code) throw new Error("[po-planner] Missing reminder API anchor");
        return { code: next, map: null };
      }
      if (!id.includes("/src/operations/OperationsPoPlanner.jsx")) return null;

      let next = code;
      const replaceOnce = (needle, replacement, label) => {
        if (!next.includes(needle)) {
          throw new Error(`[po-planner] Missing transform anchor: ${label}`);
        }
        next = next.replace(needle, replacement);
      };
      const replaceRegex = (pattern, replacement, label) => {
        if (!pattern.test(next)) {
          throw new Error(`[po-planner] Missing transform section: ${label}`);
        }
        next = next.replace(pattern, replacement);
      };

      replaceOnce(
        "function normalize(value) {",
        `function canDeletePo(po) {\n  const status = String(po?.status || "").toUpperCase();\n  const poCode = String(po?.po_code || "").toUpperCase();\n  return status === "DRAFT" || status === "CANCELLED" || status === "HISTORICAL_IMPORTED" || poCode.startsWith("TEST-");\n}\n\nfunction normalize(value) {`,
        "delete eligibility helper",
      );

      replaceOnce(
        `  const deletePo = async (po) => {\n    if (!window.confirm(\`Hapus permanen DRAFT \${po.po_code} rev \${po.revision_no}?\`)) return;`,
        `  const deletePo = async (po) => {\n    const status = String(po?.status || "").toUpperCase();\n    const isTest = String(po?.po_code || "").toUpperCase().startsWith("TEST-");\n    const kind = isTest ? "PO TEST" : status === "HISTORICAL_IMPORTED" ? "PO HISTORICAL IMPORT" : status === "CANCELLED" ? "PO CANCELLED" : "PO DRAFT";\n    if (!window.confirm(\`Hapus permanen \${kind} \${po.po_code} rev \${po.revision_no}?\\n\\nTindakan ini tidak dapat dibatalkan.\`)) return;`,
        "delete confirmation",
      );

      replaceOnce(
        `{REVISABLE_PO_STATUSES.has(status) && <button type="button" onClick={() => cancelPo(po)} disabled={actionId === po.id}><XCircle size={14} /> Batalkan</button>}`,
        `{REVISABLE_PO_STATUSES.has(status) && <button type="button" onClick={() => cancelPo(po)} disabled={actionId === po.id}><XCircle size={14} /> Batalkan</button>}\n                      {canDeletePo(po) && <button type="button" className="danger" onClick={() => deletePo(po)} disabled={actionId === po.id}><Trash2 size={14} /> Hapus</button>}`,
        "delete button",
      );

      next = next.replaceAll("horizonDays: 21", "horizonDays: 2");

      replaceOnce(
        `  return (\n    <div className="ops-domain-stack">`,
        `  const reminderToday = reminders.filter((item) => String(item.po_date || "") === today());\n  const reminderTomorrow = reminders.filter((item) => String(item.po_date || "") === shiftDate(today(), 1));\n  const reminderActionStatuses = new Set(["DUE_TODAY", "DRAFT_NEEDS_FINAL", "READY_TO_SEND"]);\n\n  return (\n    <div className="ops-domain-stack">`,
        "reminder day buckets",
      );

      replaceRegex(
        /      <section className="ops-module">\n        <div className="ops-module-header">\n          <div><span className="ops-kicker">PENGINGAT OTOMATIS<\/span><h3>PO yang Harus Dikerjakan<\/h3>[\s\S]*?      <\/section>\n\n/,
        `      <section className="ops-module">\n        <div className="ops-module-header">\n          <div><span className="ops-kicker">PENGINGAT PO 2 HARI</span><h3>PO yang Harus Dikerjakan</h3><p>Hanya kebutuhan dari planning aktif dengan qty lebih dari 0 yang ditampilkan. Daftar dikelompokkan berdasarkan tanggal kirim PO dan vendor sesuai lead time.</p></div>\n          <BellRing size={32} />\n        </div>\n        <div className="ops-summary-strip">\n          <span>Harus dikerjakan hari ini <strong>{reminderToday.filter((item) => reminderActionStatuses.has(item.reminder_status)).length}</strong></span>\n          <span>Untuk besok <strong>{reminderTomorrow.filter((item) => item.reminder_status !== "DONE").length}</strong></span>\n          <span>Cakupan <strong>H-0 + besok</strong></span>\n        </div>\n\n        <div className="ops-draft-group">\n          <div className="ops-draft-group-head"><div><strong>Harus di-PO Hari Ini</strong><span>{today()} · berdasarkan planning aktif + lead time</span></div></div>\n          <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Status</th><th>Vendor</th><th>Masak</th><th>Distribusi</th><th>Item</th><th>PO</th></tr></thead><tbody>\n            {reminderToday.map((item, index) => <tr key={\`today-\${item.vendor_code}-\${index}\`}><td><strong>{REMINDER_LABELS[item.reminder_status] || item.reminder_status}</strong></td><td>{item.vendor_name || item.vendor_code}</td><td>{(item.cooking_dates || [item.cooking_date]).filter(Boolean).join(", ")}</td><td>{(item.distribution_dates || [item.distribution_date]).filter(Boolean).join(", ")}</td><td>{item.item_count}</td><td>{item.purchase_order_id ? <div><strong>{item.po_code || item.po_status}</strong><div className="ops-muted">{item.po_status}</div>{item.po_sent_at && <div className="ops-muted">Terkirim: {compactTimestamp(item.po_sent_at)}</div>}<button type="button" onClick={() => viewPoDetail(item.purchase_order_id)}><Eye size={13} /> Lihat PO</button></div> : "Belum dibuat"}</td></tr>)}\n            {!loading && reminderToday.length === 0 && <tr><td colSpan="6" className="ops-empty-cell">Tidak ada kebutuhan PO yang jatuh pada hari ini dari planning aktif.</td></tr>}\n          </tbody></table></div>\n        </div>\n\n        <div className="ops-draft-group">\n          <div className="ops-draft-group-head"><div><strong>Untuk Di-PO Besok</strong><span>{shiftDate(today(), 1)} · persiapan satu hari ke depan</span></div></div>\n          <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Status</th><th>Vendor</th><th>Masak</th><th>Distribusi</th><th>Item</th><th>PO</th></tr></thead><tbody>\n            {reminderTomorrow.map((item, index) => <tr key={\`tomorrow-\${item.vendor_code}-\${index}\`}><td><strong>{item.reminder_status === "UPCOMING" ? "Besok" : (REMINDER_LABELS[item.reminder_status] || item.reminder_status)}</strong></td><td>{item.vendor_name || item.vendor_code}</td><td>{(item.cooking_dates || [item.cooking_date]).filter(Boolean).join(", ")}</td><td>{(item.distribution_dates || [item.distribution_date]).filter(Boolean).join(", ")}</td><td>{item.item_count}</td><td>{item.purchase_order_id ? <div><strong>{item.po_code || item.po_status}</strong><div className="ops-muted">{item.po_status}</div>{item.po_sent_at && <div className="ops-muted">Terkirim: {compactTimestamp(item.po_sent_at)}</div>}<button type="button" onClick={() => viewPoDetail(item.purchase_order_id)}><Eye size={13} /> Lihat PO</button></div> : "Belum dibuat"}</td></tr>)}\n            {!loading && reminderTomorrow.length === 0 && <tr><td colSpan="6" className="ops-empty-cell">Tidak ada kebutuhan PO untuk besok dari planning aktif.</td></tr>}\n          </tbody></table></div>\n        </div>\n      </section>\n\n`,
        "two-day PO reminder",
      );

      replaceRegex(
        /      <section className="ops-module">\n        <div className="ops-module-header">\n          <div><span className="ops-kicker">JADWAL PO<\/span><h3>Waktu Pesan Vendor<\/h3>[\s\S]*?      <\/section>\n\n/,
        "",
        "remove duplicated PO schedule table",
      );

      return { code: next, map: null };
    },
  };
}

function cemplangAccountantVariant() {
  return {
    name: "sppg-cemplang-accountant-variant",
    enforce: "pre",
    transform(code, id) {
      if (!id.includes("/src/App.jsx?cemplang-accountant")) return null;

      let next = code;
      const replaceOnce = (needle, replacement, label) => {
        if (!next.includes(needle)) {
          throw new Error(`[cemplang-accountant] Missing transform anchor: ${label}`);
        }
        next = next.replace(needle, replacement);
      };

      replaceOnce(
        '} from "firebase/firestore";',
        `} from "firebase/firestore";\nimport { getAuth, inMemoryPersistence, setPersistence, signInWithCustomToken } from "firebase/auth";\nimport { authApi } from "./auth/session.js";`,
        "Firebase imports",
      );

      replaceOnce(
        "const runtimeSite = RUNTIME_HOST_SITE_MAP[currentHostname] || null;",
        `const runtimeSite = {\n  siteId: "sppg-cemplang2-gpt-site",\n  databaseId: "cemplang2",\n  siteLabel: "SPPG CEMPLANG 2",\n  siteShortLabel: "Cemplang 2"\n};`,
        "Cemplang runtime site",
      );

      replaceOnce(
        "const app = hasFirebaseConfig ? initializeApp(firebaseConfig) : null;",
        `const app = hasFirebaseConfig ? initializeApp(firebaseConfig) : null;\nconst firebaseAuth = app ? getAuth(app) : null;`,
        "Firebase Auth init",
      );

      replaceOnce(
        '  const [lastSaved, setLastSaved] = useState("Memeriksa sinkronisasi...");',
        `  const [lastSaved, setLastSaved] = useState("Memeriksa sinkronisasi...");\n  const [cemplangFirebaseReady, setCemplangFirebaseReady] = useState(false);`,
        "Cemplang auth state",
      );

      const loadEffectAnchor = `  useEffect(() => {\n    if (!db || !paths) {\n      setIsDataLoaded(true);\n      setLastSaved("Firebase config belum tersedia");`;
      const authAndLoad = `  useEffect(() => {\n    let cancelled = false;\n\n    const authenticateCemplangFirebase = async () => {\n      try {\n        if (!firebaseAuth) throw new Error("Firebase Auth belum tersedia.");\n        setLastSaved("Menghubungkan Firebase Cemplang...");\n        const session = await authApi.firebaseCemplangToken();\n        if (!session?.customToken) throw new Error("Firebase custom token tidak tersedia.");\n        await setPersistence(firebaseAuth, inMemoryPersistence);\n        await signInWithCustomToken(firebaseAuth, session.customToken);\n        if (!cancelled) {\n          setCemplangFirebaseReady(true);\n          setLastSaved("Firebase Cemplang terautentikasi");\n        }\n      } catch (err) {\n        console.error(err);\n        if (!cancelled) {\n          setLastSaved("Gagal autentikasi Firebase Cemplang: " + err.message);\n          setIsDataLoaded(true);\n        }\n      }\n    };\n\n    authenticateCemplangFirebase();\n    return () => { cancelled = true; };\n  }, []);\n\n  useEffect(() => {\n    if (!cemplangFirebaseReady) return;\n    if (!db || !paths) {\n      setIsDataLoaded(true);\n      setLastSaved("Firebase config belum tersedia");`;
      replaceOnce(loadEffectAnchor, authAndLoad, "Cemplang auth gate");

      replaceOnce(
        `  }, [paths]);\n\n  const saveMeta = async`,
        `  }, [paths, cemplangFirebaseReady]);\n\n  const saveMeta = async`,
        "Firestore load dependency",
      );

      return { code: next, map: null };
    },
  };
}

export default defineConfig({
  plugins: [poPlannerVariant(), cemplangAccountantVariant(), react()],
  preview: {
    host: "0.0.0.0",
    allowedHosts: true
  },
  server: {
    host: "0.0.0.0",
    allowedHosts: true
  }
});
