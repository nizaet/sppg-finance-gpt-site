import React, { Suspense, lazy, useState } from "react";
import {
  CalendarDays,
  FileSpreadsheet,
  LayoutDashboard,
  ListChecks,
  MessageSquareText,
  Store,
  WalletCards,
} from "lucide-react";
import OperationsControlTower from "./OperationsControlTower.jsx";
import "./workspace.css";

const OperationsPoPlanner = lazy(() => import("./OperationsPoPlanner.jsx"));
const OperationsPayments = lazy(() => import("./OperationsPayments.jsx"));
const OperationsAccountantBgn = lazy(() => import("./OperationsAccountantBgn.jsx"));
const OperationsVendorMaster = lazy(() => import("./OperationsVendorMaster.jsx"));
const OperationsReviewQueue = lazy(() => import("./OperationsReviewQueue.jsx"));
const OperationsChatIngest = lazy(() => import("./OperationsChatIngest.jsx"));

const tabs = [
  ["today", "Hari Ini", LayoutDashboard],
  ["po", "PO Vendor", CalendarDays],
  ["payments", "Invoice & Pembayaran", WalletCards],
  ["accounting", "Akuntan & BGN", FileSpreadsheet],
  ["vendors", "Vendor & Lead Time", Store],
  ["review", "Review", ListChecks],
  ["chat", "Sumber Chat", MessageSquareText],
];

function ModuleFallback() {
  return (
    <section className="ops-module">
      <div className="ops-empty">Membuka modul…</div>
    </section>
  );
}

export default function OperationsWorkspace() {
  const [tab, setTab] = useState("today");

  return (
    <div className="ops-workspace">
      <aside className="ops-sidebar">
        <div className="ops-brand">
          <span>SPPG</span>
          <strong>Pusat Operasional</strong>
          <small>Maja + Cemplang</small>
        </div>

        <nav>
          {tabs.map(([id, label, Icon]) => (
            <button
              type="button"
              key={id}
              className={tab === id ? "active" : ""}
              onClick={() => setTab(id)}
            >
              <Icon size={17} />
              {label}
            </button>
          ))}
        </nav>

        <div className="ops-sidebar-note">
          Pusat Resep, Master Harga, dan Kalkulator tetap menjadi sumber planning terpusat.
          Pusat Operasional mengelola proses setelah planning tanpa menimpa data planning historis.
        </div>
      </aside>

      <main className="ops-content">
        {tab === "today" ? (
          <OperationsControlTower />
        ) : (
          <Suspense fallback={<ModuleFallback />}>
            {tab === "po" && <OperationsPoPlanner />}
            {tab === "payments" && <OperationsPayments />}
            {tab === "accounting" && <OperationsAccountantBgn />}
            {tab === "vendors" && <OperationsVendorMaster />}
            {tab === "review" && <OperationsReviewQueue />}
            {tab === "chat" && <OperationsChatIngest />}
          </Suspense>
        )}
      </main>
    </div>
  );
}
