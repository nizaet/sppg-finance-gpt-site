import React, { useState } from "react";
import DocumentWorkspace, { todayJakarta } from "../documents/DocumentWorkspace.jsx";

export default function OperationsDocuments({ routeSite = "MAJA", onSiteChange }) {
  const [localSite, setLocalSite] = useState(routeSite || "MAJA");
  const [date, setDate] = useState(todayJakarta);
  const site = onSiteChange ? routeSite : localSite;
  return <section>
    <div className="doc-context"><strong>Dapur</strong>{["MAJA", "CEMPLANG"].map(x => <button className={site === x ? "active" : ""} key={x} type="button" onClick={() => { if (x !== site && window.confirm("Buka dokumen dapur lain? Simpan draft sebelum berpindah.")) (onSiteChange || setLocalSite)(x); }}>{x}</button>)}</div>
    <DocumentWorkspace site={site} serviceDate={date} onDateChange={setDate} onOpenDaily={() => window.location.assign(`/lpdh?site=${site}&date=${date}&tab=daily`)}/>
  </section>;
}
