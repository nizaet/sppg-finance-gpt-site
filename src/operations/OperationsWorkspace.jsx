import React, { useState } from "react";
import { CalendarDays, LayoutDashboard, ListChecks, MessageSquareText, Store, WalletCards } from "lucide-react";
import OperationsControlTower from "./OperationsControlTower.jsx";
import OperationsPoPlanner from "./OperationsPoPlanner.jsx";
import OperationsVendorMaster from "./OperationsVendorMaster.jsx";
import OperationsPayments from "./OperationsPayments.jsx";
import OperationsReviewQueue from "./OperationsReviewQueue.jsx";
import OperationsChatIngest from "./OperationsChatIngest.jsx";
import "./workspace.css";

const tabs = [
  ["today", "Hari Ini", LayoutDashboard],
  ["chat", "Input Chat", MessageSquareText],
  ["po", "Kalender PO", CalendarDays],
  ["vendors", "Vendor & Lead Time", Store],
  ["payments", "Pembayaran", WalletCards],
  ["review", "Review AI", ListChecks],
];

export default function OperationsWorkspace() {
  const [tab, setTab] = useState("today");
  return (
    <div className="ops-workspace">
      <aside className="ops-sidebar">
        <div className="ops-brand"><span>SPPG</span><strong>Pusat Operasional</strong><small>Maja + Cemplang</small></div>
        <nav>{tabs.map(([id, label, Icon]) => <button type="button" key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}><Icon size={17} />{label}</button>)}</nav>
        <div className="ops-sidebar-note">Kalkulator menu tetap menjadi sumber planning. Perubahan operasional tidak menimpa planning historis.</div>
      </aside>
      <main className="ops-content">
        {tab === "today" && <OperationsControlTower />}
        {tab === "chat" && <OperationsChatIngest />}
        {tab === "po" && <OperationsPoPlanner />}
        {tab === "vendors" && <OperationsVendorMaster />}
        {tab === "payments" && <OperationsPayments />}
        {tab === "review" && <OperationsReviewQueue />}
      </main>
    </div>
  );
}
