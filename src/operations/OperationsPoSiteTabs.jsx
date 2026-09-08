import React, { memo, useEffect, useState } from "react";
import OperationsPoPlanner from "./OperationsPoPlanner.jsx";

const SITES = ["MAJA", "CEMPLANG"];
const CachedPoPlanner = memo(OperationsPoPlanner);

export default function OperationsPoSiteTabs({ routeSite = '', onSiteChange }) {
  const [site, setSite] = useState(routeSite || "MAJA");
  const activeSite = routeSite || site;
  const [visitedSites, setVisitedSites] = useState(() => new Set([activeSite]));
  useEffect(() => {
    setVisitedSites(current => current.has(activeSite) ? current : new Set([...current, activeSite]));
  }, [activeSite]);
  const setActiveSite = onSiteChange || setSite;

  return (
    <div data-po-site-tabs="v1">
      <section className="ops-module ops-po-site-switcher ops-site-switcher">
        <div>
          <h3>PO Vendor per Dapur</h3>
          <p className="ops-switcher-note">Hasil tarikan MAJA dan CEMPLANG disimpan pada tab masing-masing selama halaman tetap terbuka.</p>
        </div>
        <div className="ops-po-site-tabs" role="tablist" aria-label="Pilih dapur PO Vendor">
          {SITES.map((site) => (
            <button
              key={site}
              type="button"
              role="tab"
              aria-selected={activeSite === site}
              className={activeSite === site ? "active" : ""}
              onClick={() => setActiveSite(site)}
            >
              {site}
            </button>
          ))}
        </div>
      </section>

      {SITES.map((site) => (visitedSites.has(site) || site === activeSite) ? (
        <div
          key={site}
          role="tabpanel"
          data-po-site-panel={site}
          hidden={activeSite !== site}
        >
          <CachedPoPlanner fixedSite={site} />
        </div>
      ) : null)}
    </div>
  );
}
