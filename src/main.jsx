import React, { Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import AuthGate from "./auth/AuthGate.jsx";

const pathname = typeof window !== "undefined" ? window.location.pathname : "/";
const isOperationsRoute = pathname === "/operations" || pathname.startsWith("/operations/");
const isCemplangAccountantRoute =
  pathname === "/accountant/cemplang" || pathname.startsWith("/accountant/cemplang/");

const RootComponent = isOperationsRoute
  ? lazy(() => import("./operations/OperationsWorkspace.jsx"))
  : isCemplangAccountantRoute
    ? lazy(() => Promise.all([
        import("./App.jsx?cemplang-accountant"),
        import("./styles.css"),
      ]).then(([appModule]) => ({ default: appModule.default })))
    : lazy(() => Promise.all([
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

function RoutedApp({ role }) {
  // Aplikasi Akuntan di root adalah OWNER-only. Site role yang membuka URL root
  // diarahkan ke Pusat Operasional sebelum bundle App.jsx dimuat.
  if (!isOperationsRoute && role !== "OWNER") {
    window.location.replace("/operations");
    return <BootFallback text="Mengalihkan ke Pusat Operasional…" />;
  }

  return (
    <Suspense fallback={<BootFallback />}>
      <RootComponent accessRole={role} />
    </Suspense>
  );
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <AuthGate>
      {({ role }) => <RoutedApp role={role} />}
    </AuthGate>
  </React.StrictMode>
);
