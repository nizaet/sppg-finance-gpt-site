import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

function poCleanupVariant() {
  return {
    name: "sppg-po-cleanup-ui",
    enforce: "pre",
    transform(code, id) {
      if (!id.includes("/src/operations/OperationsPoPlanner.jsx")) return null;

      let next = code;
      const replaceOnce = (needle, replacement, label) => {
        if (!next.includes(needle)) {
          throw new Error(`[po-cleanup] Missing transform anchor: ${label}`);
        }
        next = next.replace(needle, replacement);
      };

      replaceOnce(
        "function normalize(value) {",
        `function canDeletePo(po) {\n  const status = String(po?.status || "").toUpperCase();\n  const poCode = String(po?.po_code || "").toUpperCase();\n  return status === "DRAFT" || status === "CANCELLED" || poCode.startsWith("TEST-");\n}\n\nfunction normalize(value) {`,
        "delete eligibility helper",
      );

      replaceOnce(
        `{REVISABLE_PO_STATUSES.has(status) && <button type="button" onClick={() => cancelPo(po)} disabled={actionId === po.id}><XCircle size={14} /> Batalkan</button>}`,
        `{REVISABLE_PO_STATUSES.has(status) && <button type="button" onClick={() => cancelPo(po)} disabled={actionId === po.id}><XCircle size={14} /> Batalkan</button>}\n                      {canDeletePo(po) && <button type="button" className="danger" onClick={() => deletePo(po)} disabled={actionId === po.id}><Trash2 size={14} /> Hapus</button>}`,
        "delete button",
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
  plugins: [poCleanupVariant(), cemplangAccountantVariant(), react()],
  preview: {
    host: "0.0.0.0",
    allowedHosts: true
  },
  server: {
    host: "0.0.0.0",
    allowedHosts: true
  }
});
