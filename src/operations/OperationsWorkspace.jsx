import React, { Suspense, lazy, useEffect, useState } from "react";
import {
  Calculator,
  CalendarDays,
  FileSpreadsheet,
  FolderUp,
  LayoutDashboard,
  ListChecks,
  MessageSquareText,
  Sparkles,
  Moon,
  Menu,
  X,
  PackageCheck,
  Store,
  Sun,
  ShieldCheck,
  WalletCards,
  Warehouse,
} from "lucide-react";
import { useAppTheme } from "../theme.js";
import OperationsControlTower from "./OperationsControlTower.jsx";
import "./workspace.css";

const OperationsPoSiteTabs = lazy(() => import("./OperationsPoSiteTabs.jsx"));
const OperationsReceiving = lazy(() => import("./OperationsReceiving.jsx"));
const OperationsInventory = lazy(() => import("./OperationsInventory.jsx"));
const OperationsPayments = lazy(() => import("./OperationsPayments.jsx"));
const OperationsAccountantBgn = lazy(() => import("./OperationsAccountantBgn.jsx"));
const OperationsVendorMaster = lazy(() => import("./OperationsVendorMaster.jsx"));
const OperationsReviewQueue = lazy(() => import("./OperationsReviewQueue.jsx"));
const OperationsChatIngest = lazy(() => import("./OperationsChatIngest.jsx"));
const OperationsCalculatorData = lazy(() => import("./OperationsCalculatorData.jsx"));
const OperationsHermesApprovals = lazy(() => import("./OperationsHermesApprovals.jsx"));
const OperationsMenuPlanningAdvisor = lazy(() => import("./OperationsMenuPlanningAdvisor.jsx"));

const tabs = [
  ["today", "Control Tower", LayoutDashboard],
  ["po", "PO Vendor", CalendarDays],
  ["receiving", "Penerimaan", PackageCheck],
  ["inventory", "Gudang", Warehouse],
  ["calculator-data", "Data Kalkulator", FolderUp],
  ["menu-advisor", "Asisten Menu", Sparkles],
  ["payments", "Invoice & Pembayaran", WalletCards],
  ["accounting", "Akuntan & BGN", FileSpreadsheet],
  ["vendors", "Vendor & Lead Time", Store],
  ["review", "Review", ListChecks],
  ["hermes", "Persetujuan Hermes", ShieldCheck],
  ["chat", "Sumber Chat", MessageSquareText],
];

const moduleComponents = {
  po: OperationsPoSiteTabs,
  receiving: OperationsReceiving,
  inventory: OperationsInventory,
  "calculator-data": OperationsCalculatorData,
  "menu-advisor": OperationsMenuPlanningAdvisor,
  payments: OperationsPayments,
  accounting: OperationsAccountantBgn,
  vendors: OperationsVendorMaster,
  review: OperationsReviewQueue,
  hermes: OperationsHermesApprovals,
  chat: OperationsChatIngest,
};

function ModuleFallback() {
  return <section className="ops-module"><div className="ops-empty">Membuka modul…</div></section>;
}

export default function OperationsWorkspace({ accessRole = "OWNER" }) {
  const role = String(accessRole || "OWNER").toUpperCase();
  const [tab, setTab] = useState("today");
  const [visitedTabs, setVisitedTabs] = useState(() => new Set(["today"]));
  const [theme, setTheme] = useAppTheme();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    document.title = "Pusat Operasional | SPPG";
    ["icon", "shortcut icon"].forEach((rel) => {
      let link = document.querySelector(`link[rel='${rel}']`);
      if (!link) {
        link = document.createElement("link");
        link.rel = rel;
        document.head.appendChild(link);
      }
      link.href = "/favicon-operations.svg?v=27";
      link.type = "image/svg+xml";
    });
  }, []);

  // Defense in depth: site roles should have been routed to /calculator by main.jsx.
  if (role !== "OWNER") {
    window.location.replace("/calculator");
    return null;
  }

  const openTab = (id) => {
    setTab(id);
    setMobileMenuOpen(false);
    setVisitedTabs((current) => {
      if (current.has(id)) return current;
      const next = new Set(current);
      next.add(id);
      return next;
    });
  };

  return (
    <div className="ops-workspace">
      <aside className={`ops-sidebar${mobileMenuOpen ? " mobile-open" : ""}`}>
        <div className="ops-brand">
          <div>
            <span>SPPG</span>
            <strong>Pusat Operasional</strong>
            <small>YAYASAN · MAJA + CEMPLANG</small>
          </div>
          <button className="ops-mobile-menu" type="button" aria-expanded={mobileMenuOpen} aria-controls="ops-primary-navigation" onClick={() => setMobileMenuOpen((open) => !open)}>
            {mobileMenuOpen ? <X size={19} /> : <Menu size={19} />}
            <span>{mobileMenuOpen ? "Tutup" : "Menu"}</span>
          </button>
        </div>

        <nav id="ops-primary-navigation">
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

        <button className="ops-theme-toggle" type="button" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
          {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
          {theme === "dark" ? "Gunakan Tema Terang" : "Gunakan Tema Gelap"}
        </button>

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
