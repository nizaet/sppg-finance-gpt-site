import React, { Suspense, lazy, useMemo, useState } from "react";
import {
  CalendarDays,
  FileSpreadsheet,
  LayoutDashboard,
  ListChecks,
  MessageSquareText,
  PackageCheck,
  Store,
  WalletCards,
  Warehouse,
} from "lucide-react";
import OperationsControlTower from "./OperationsControlTower.jsx";
import "./workspace.css";

const OperationsPoPlanner = lazy(() => import("./OperationsPoPlanner.jsx"));
const OperationsReceiving = lazy(() => import("./OperationsReceiving.jsx"));
const OperationsInventory = lazy(() => import("./OperationsInventory.jsx"));
const OperationsPayments = lazy(() => import("./OperationsPayments.jsx"));
const OperationsAccountantBgn = lazy(() => import("./OperationsAccountantBgn.jsx"));
const OperationsVendorMaster = lazy(() => import("./OperationsVendorMaster.jsx"));
const OperationsReviewQueue = lazy(() => import("./OperationsReviewQueue.jsx"));
const OperationsChatIngest = lazy(() => import("./OperationsChatIngest.jsx"));

const tabs = [
  ["today", "Hari Ini", LayoutDashboard],
  ["po", "PO Vendor", CalendarDays],
  ["receiving", "Penerimaan", PackageCheck],
  ["inventory", "Gudang", Warehouse],
  ["payments", "Invoice & Pembayaran", WalletCards],
  ["accounting", "Akuntan & BGN", FileSpreadsheet],
  ["vendors", "Vendor & Lead Time", Store],
  ["review", "Review", ListChecks],
  ["chat", "Sumber Chat", MessageSquareText],
];

const OWNER_ONLY_TABS = new Set(["accounting", "review", "chat"]);

const moduleComponents = {
  po: OperationsPoPlanner,
  receiving: OperationsReceiving,
  inventory: OperationsInventory,
  payments: OperationsPayments,
  accounting: OperationsAccountantBgn,
  vendors: OperationsVendorMaster,
  review: OperationsReviewQueue,
  chat: OperationsChatIngest,
};

function ModuleFallback() {
  return (
    <section className="ops-module">
      <div className="ops-empty">Membuka modul…</div>
    </section>
  );
}

export default function OperationsWorkspace({ accessRole = "OWNER" }) {
  const role = String(accessRole || "OWNER").toUpperCase();
  const fixedSite = role === "MAJA" || role === "CEMPLANG" ? role : "";
  const visibleTabs = useMemo(
    () => tabs.filter(([id]) => role === "OWNER" || !OWNER_ONLY_TABS.has(id)),
    [role],
  );
  const [tab, setTab] = useState("today");
  const [visitedTabs, setVisitedTabs] = useState(() => new Set(["today"]));

  const openTab = (id) => {
    if (role !== "OWNER" && OWNER_ONLY_TABS.has(id)) return;
    setTab(id);
    setVisitedTabs((current) => {
      if (current.has(id)) return current;
      const next = new Set(current);
      next.add(id);
      return next;
    });
  };

  return (
    <div className="ops-workspace">
      <aside className="ops-sidebar">
        <div className="ops-brand">
          <span>SPPG</span>
          <strong>Pusat Operasional</strong>
          <small>{fixedSite ? `Akses ${fixedSite}` : "Maja + Cemplang"}</small>
        </div>

        <nav>
          {visibleTabs.map(([id, label, Icon]) => (
            <button
              type="button"
              key={id}
              className={tab === id ? "active" : ""}
              onClick={() => openTab(id)}
            >
              <Icon size={17} />
              {label}
            </button>
          ))}
        </nav>

        <div className="ops-sidebar-note">
          Pusat Resep, Master Harga, dan Kalkulator tetap menjadi sumber planning terpusat.
          {fixedSite
            ? ` Akun ${fixedSite} hanya melihat dan bekerja pada operasional ${fixedSite}.`
            : " Pusat Operasional mengelola kedua dapur; Akuntan & BGN tetap khusus OWNER."}
        </div>
      </aside>

      <main className="ops-content">
        <div hidden={tab !== "today"}>
          <OperationsControlTower fixedSite={fixedSite} />
        </div>

        <Suspense fallback={<ModuleFallback />}>
          {Object.entries(moduleComponents).map(([id, Component]) => (
            visitedTabs.has(id) && (role === "OWNER" || !OWNER_ONLY_TABS.has(id)) ? (
              <div key={id} hidden={tab !== id}>
                <Component fixedSite={fixedSite} accessRole={role} />
              </div>
            ) : null
          ))}
        </Suspense>
      </main>
    </div>
  );
}
