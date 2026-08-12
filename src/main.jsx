import React, { Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";

const pathname = typeof window !== "undefined" ? window.location.pathname : "/";
const isOperationsRoute = pathname === "/operations" || pathname.startsWith("/operations/");

const RootComponent = isOperationsRoute
  ? lazy(() => import("./operations/OperationsWorkspace.jsx"))
  : lazy(() => Promise.all([
      import("./App.jsx"),
      import("./styles.css"),
    ]).then(([appModule]) => ({ default: appModule.default })));

function BootFallback() {
  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", background: "#08111f", color: "#e5edf7", fontFamily: "Inter, system-ui, sans-serif" }}>
      Memuat SPPG…
    </div>
  );
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <Suspense fallback={<BootFallback />}>
      <RootComponent />
    </Suspense>
  </React.StrictMode>
);
