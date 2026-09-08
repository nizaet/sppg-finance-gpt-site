import React, { Suspense, lazy, memo, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
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
import { readOperationsRoute, normalizeOperationsRoute, operationsUrl, operationsRouteKey, SITE_TABS } from "./navigation.js";
import "./workspace.css";

const OperationsPoSiteTabs = lazy(() => import("./OperationsPoSiteTabs.jsx"));
const OperationsControlTower = lazy(() => import("./OperationsControlTower.jsx"));
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
  today: OperationsControlTower,
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

const ModulePanel = memo(function ModulePanel({ Component, routeSite, onSiteChange }) {
  return <Component accessRole="OWNER" routeSite={routeSite} onSiteChange={onSiteChange} />;
});

function ModuleFallback() {
  return <section className="ops-module"><div className="ops-empty">Membuka modul…</div></section>;
}

export default function OperationsWorkspace({ accessRole = "OWNER" }) {
  const role = String(accessRole || "OWNER").toUpperCase();
  const [route, setRoute] = useState(readOperationsRoute);
  const tab = route.tab;
  const [visitedTabs, setVisitedTabs] = useState(() => new Set([route.tab]));
  const sitesByTab = useRef({ [route.tab]: route.site });
  const scrollPositions = useRef(new Map());
  const routeRef = useRef(route);
  const workspaceRef = useRef(null);
  const sidebarRef = useRef(null);
  const [theme, setTheme] = useAppTheme();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    document.title = `${tabs.find(([id]) => id === tab)?.[1] || 'Pusat Operasional'} | SPPG`;
  }, [tab]);

  useEffect(() => {
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

  const activateRoute = useCallback((next) => {
    scrollPositions.current.set(operationsRouteKey(routeRef.current), window.scrollY);
    routeRef.current = next;
    sitesByTab.current[next.tab] = next.site;
    setRoute(next);
    setMobileMenuOpen(false);
    setVisitedTabs(current => current.has(next.tab) ? current : new Set([...current, next.tab]));
  }, []);

  useEffect(() => {
    const previous = window.history.scrollRestoration;
    window.history.scrollRestoration = 'manual';
    const onPopState = () => activateRoute(readOperationsRoute());
    window.addEventListener('popstate', onPopState);
    return () => {
      window.removeEventListener('popstate', onPopState);
      window.history.scrollRestoration = previous;
    };
  }, [activateRoute]);

  useLayoutEffect(() => {
    window.scrollTo(0, scrollPositions.current.get(operationsRouteKey(route)) || 0);
  }, [route.tab, route.site]);

  useEffect(() => {
    if (!sidebarRef.current || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => {
      workspaceRef.current?.style.setProperty('--ops-header-height', `${entry.target.getBoundingClientRect().height}px`);
    });
    observer.observe(sidebarRef.current);
    return () => observer.disconnect();
  }, []);

  const navigate = useCallback((id, site) => {
    const next = normalizeOperationsRoute(id, site ?? sitesByTab.current[id]);
    const url = operationsUrl(next.tab, next.site);
    if (window.location.pathname + window.location.search !== url) window.history.pushState(null, '', url);
    activateRoute(next);
  }, [activateRoute]);

  const changeSite = useCallback(site => navigate(routeRef.current.tab, site), [navigate]);

  // Defense in depth: site roles should have been routed to /calculator by main.jsx.
  if (role !== "OWNER") {
    window.location.replace("/calculator");
    return null;
  }

  return (
    <div className="ops-workspace" ref={workspaceRef}>
      <aside ref={sidebarRef} className={`ops-sidebar${mobileMenuOpen ? " mobile-open" : ""}`}>
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
            <a
              href={operationsUrl(id, sitesByTab.current[id])}
              key={id}
              className={tab === id ? "active" : ""}
              aria-current={tab === id ? 'page' : undefined}
              onClick={(event) => {
                if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                event.preventDefault();
                navigate(id);
              }}
            >
              <Icon size={17} />
              {label}
            </a>
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
          {Object.entries(moduleComponents).map(([id, Component]) => (
            visitedTabs.has(id) ? (
              <div key={id} hidden={tab !== id}>
                <Suspense fallback={<ModuleFallback />}>
                  <ModulePanel Component={Component}
                    routeSite={sitesByTab.current[id]}
                    onSiteChange={SITE_TABS[id] ? changeSite : undefined} />
                </Suspense>
              </div>
            ) : null
          ))}
      </main>
    </div>
  );
}
