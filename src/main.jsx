import React, { Suspense, lazy, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { getApp, getApps, initializeApp } from "firebase/app";
import { getAuth, signInWithCustomToken } from "firebase/auth";
import AuthGate from "./auth/AuthGate.jsx";
import CalculatorGateway from "./auth/CalculatorGateway.jsx";
import { authApi, readSessionToken } from "./auth/session.js";
import { applyAppTheme } from "./theme.js";
import { installRuntimeUiPolish } from "./runtimeUiPolish.js";
import { installInventoryUiEnhancements } from "./operations/inventory-ui-enhancements.js";
import "./operations/inventory-editor.css";

applyAppTheme();
installRuntimeUiPolish();
installInventoryUiEnhancements();

const pathname = typeof window !== "undefined" ? window.location.pathname : "/";
const isOperationsRoute = pathname === "/operations" || pathname.startsWith("/operations/");
const isCalculatorRoute = pathname === "/calculator" || pathname.startsWith("/calculator/");
const isCemplangAccountantRoute = pathname === "/accountant/cemplang" || pathname.startsWith("/accountant/cemplang/");

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY || "AIzaSyB72MVySugfHF_vu11WYv-s9uiQbRpftk4",
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN || "sppg-finance-gpt.firebaseapp.com",
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID || "sppg-finance-gpt",
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET || "sppg-finance-gpt.firebasestorage.app",
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID || "732611890148",
  appId: import.meta.env.VITE_FIREBASE_APP_ID || "1:732611890148:web:5dcfab93d1d351b10315f1",
  measurementId: import.meta.env.VITE_FIREBASE_MEASUREMENT_ID || "G-DZERB61197",
};

const OperationsApp = lazy(() => import("./operations/OperationsWorkspace.jsx"));
const AccountantApp = lazy(() => Promise.all([
  import("./App.jsx"),
  import("./styles.css"),
]).then(([appModule]) => ({ default: appModule.default })));
const CemplangAccountantApp = lazy(() => Promise.all([
  import("./App.jsx?cemplang-accountant"),
  import("./styles.css"),
]).then(([appModule]) => ({ default: appModule.default })));

function BootFallback({ text = "Memuat SPPG…" }) {
  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24, textAlign: "center", background: "var(--app-bg, #08111f)", color: "var(--app-text, #e5edf7)", fontFamily: "Inter, system-ui, sans-serif" }}>
      {text}
    </div>
  );
}

function CalculatorRedirect({ role }) {
  useEffect(() => {
    window.location.replace(`/dapur/${String(role).toLowerCase()}`);
  }, [role]);
  return <BootFallback text={`Membuka Kalkulator ${role}…`} />;
}

function CemplangAccountantRoute() {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const authenticate = async () => {
      try {
        const sessionToken = readSessionToken();
        if (!sessionToken) throw new Error("Sesi OWNER SPPG tidak ditemukan. Silakan login ulang.");

        const tokenPayload = await authApi.firebaseCemplangToken(sessionToken);
        const customToken = tokenPayload?.customToken || tokenPayload?.token;
        if (!customToken) throw new Error("Custom token Firebase Cemplang kosong.");

        const firebaseApp = getApps().length ? getApp() : initializeApp(firebaseConfig);
        await signInWithCustomToken(getAuth(firebaseApp), customToken);
        if (!cancelled) setReady(true);
      } catch (err) {
        console.error("Cemplang Firebase auth failed", err);
        if (!cancelled) setError(err?.message || "Gagal autentikasi Firebase Cemplang");
      }
    };
    authenticate();
    return () => { cancelled = true; };
  }, []);

  if (error) return <BootFallback text={`Gagal autentikasi Akuntan Cemplang: ${error}`} />;
  if (!ready) return <BootFallback text="Menyiapkan akses Firebase Akuntan Cemplang…" />;
  return <CemplangAccountantApp accessRole="OWNER" />;
}

function RoutedApp({ role, config }) {
  const normalizedRole = String(role || "OWNER").toUpperCase();

  // MAJA/CEMPLANG are calculator-only. This routing rule applies regardless of
  // which browser URL they manually type after login.
  if (normalizedRole !== "OWNER") {
    return <CalculatorRedirect role={normalizedRole} />;
  }

  if (isCalculatorRoute) {
    return <CalculatorGateway role="OWNER" config={config} />;
  }

  return (
    <Suspense fallback={<BootFallback />}>
      {isOperationsRoute
        ? <OperationsApp accessRole="OWNER" />
        : isCemplangAccountantRoute
          ? <CemplangAccountantRoute />
          : <AccountantApp accessRole="OWNER" />}
    </Suspense>
  );
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <AuthGate>
      {({ role, config }) => <RoutedApp role={role} config={config} />}
    </AuthGate>
  </React.StrictMode>
);
