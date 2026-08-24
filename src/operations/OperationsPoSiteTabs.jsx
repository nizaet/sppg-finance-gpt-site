import React, { useState } from "react";
import OperationsPoPlanner from "./OperationsPoPlanner.jsx";

const SITES = ["MAJA", "CEMPLANG"];

export default function OperationsPoSiteTabs() {
  const [activeSite, setActiveSite] = useState("MAJA");

  return (
    <div data-po-site-tabs="v1">
      <section className="ops-module ops-po-site-switcher">
        <div>
          <span className="ops-kicker">RUANG KERJA PO TERPISAH</span>
          <h3>PO Vendor per Dapur</h3>
          <p>Hasil tarikan MAJA dan CEMPLANG disimpan pada tab masing-masing selama halaman tetap terbuka.</p>
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

      {SITES.map((site) => (
        <div
          key={site}
          role="tabpanel"
          data-po-site-panel={site}
          hidden={activeSite !== site}
        >
          <OperationsPoPlanner fixedSite={site} />
        </div>
      ))}
    </div>
  );
}
