import React, { Suspense, lazy, useEffect } from "react";
import { createRoot } from "react-dom/client";
import AuthGate from "./auth/AuthGate.jsx";
import CalculatorGateway from "./auth/CalculatorGateway.jsx";

const pathname = typeof window !== "undefined" ? window.location.pathname : "/";
const isOperationsRoute = pathname === "/operations" || pathname.startsWith("/operations/");
const isCalculatorRoute = pathname === "/calculator" || pathname.startsWith("/calculator/");

const OperationsApp = lazy(() => import("./operations/OperationsWorkspace.jsx"));
const AccountantApp = lazy(() => Promise.all([
  import("./App.jsx"),
  import("./styles.css"),
]).then(([appModule]) => ({ default: appModule.default })));

function BootFallback({ text = "Memuat SPPG…" }) {
  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", background: "#08111f", color: "#e5edf7", fontFamily: "Inter, system-ui, sans-serif" }}>
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
      {isOperationsRoute ? <OperationsApp accessRole="OWNER" /> : <AccountantApp accessRole="OWNER" />}
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
