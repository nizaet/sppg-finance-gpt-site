import React, { Suspense, lazy, useState } from "react";
import {
  Calculator,
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
  ["today", "Control Tower", LayoutDashboard],
  ["po", "PO Vendor", CalendarDays],
  ["receiving", "Penerimaan", PackageCheck],
  ["inventory", "Gudang", Warehouse],
  ["payments", "Invoice & Pembayaran", WalletCards],
  ["accounting", "Akuntan & BGN", FileSpreadsheet],
  ["vendors", "Vendor & Lead Time", Store],
  ["review", "Review", ListChecks],
  ["chat", "Sumber Chat", MessageSquareText],
];

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
  return <section className="ops-module"><div className="ops-empty">Membuka modul…</div></section>;
}

export default function OperationsWorkspace({ accessRole = "OWNER" }) {
  const role = String(accessRole || "OWNER").toUpperCase();
  const [tab, setTab] = useState("today");
  const [visitedTabs, setVisitedTabs] = useState(() => new Set(["today"]));

  // Defense in depth: site roles should have been routed to /calculator by main.jsx.
  if (role !== "OWNER") {
    window.location.replace("/calculator");
    return null;
  }

  const openTab = (id) => {
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
          <small>YAYASAN · MAJA + CEMPLANG</small>
        </div>

        <nav>
          <a href="/dapur/maja"><Calculator size={17} /> Kalkulator Maja</a>
          <a href="/dapur/cemplang"><Calculator size={17} /> Kalkulator Cemplang</a>
          {tabs.map(([id, label, Icon]) => (
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
          <strong>Alur:</strong> Kalkulator → planning → kurangi stok gudang → PO editable → invoice vendor → pembayaran → Excel akuntan → maker/approval BGN.
        </div>
      </aside>

      <main className="ops-content">
        <div hidden={tab !== "today"}>
          <OperationsControlTower />
        </div>

        <Suspense fallback={<ModuleFallback />}>
          {Object.entries(moduleComponents).map(([id, Component]) => (
            visitedTabs.has(id) ? (
              <div key={id} hidden={tab !== id}>
                <Component accessRole="OWNER" />
              </div>
            ) : null
          ))}
        </Suspense>
      </main>
    </div>
  );
}
