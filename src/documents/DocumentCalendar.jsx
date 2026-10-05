import React, { useEffect, useState } from "react";
import { documentApi } from "./documentApi.js";

export default function DocumentCalendar({ site, serviceDate, onSelect, revision }) {
  const [month, setMonth] = useState(serviceDate.slice(0, 7));
  const [items, setItems] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => { setMonth(serviceDate.slice(0, 7)); }, [serviceDate]);
  useEffect(() => {
    let active = true;
    setItems([]); setError(""); setLoading(true);
    documentApi.calendar(site, month).then(result => { if (active) setItems(result.items || []); })
      .catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [site, month, revision]);
  const [year, number] = month.split("-").map(Number);
  const first = new Date(year, number - 1, 1).getDay();
  const days = new Date(year, number, 0).getDate();
  const byDate = Object.fromEntries(items.map(x => [x.serviceDate, x]));
  const shift = delta => {
    const date = new Date(year, number - 1 + delta, 1);
    setMonth(`${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`);
  };
  return <section className="doc-card" aria-label="Kalender invoice dan kuitansi">
    <div className="doc-heading"><div><h3>Kalender Invoice & Kuitansi · {site}</h3><p>Semua jenis dokumen per tanggal. Klik tanggal untuk membuka register; dibatalkan tidak masuk biaya harian.</p></div>
      <div className="doc-actions"><button type="button" aria-label="Bulan invoice sebelumnya" onClick={() => shift(-1)}>‹</button><input aria-label="Bulan invoice" type="month" value={month} onChange={e => { if (e.target.value) setMonth(e.target.value); }}/><button type="button" aria-label="Bulan invoice berikutnya" onClick={() => shift(1)}>›</button></div></div>
    {error && <p role="alert" className="doc-message error">{error}</p>}
    {loading && <p role="status">Memuat kalender…</p>}
    <div className="doc-calendar-week">{["Min", "Sen", "Sel", "Rab", "Kam", "Jum", "Sab"].map(x => <span key={x}>{x}</span>)}</div>
    <div className="doc-calendar-grid">{Array.from({ length: first + days }, (_, index) => {
      if (index < first) return <span key={`blank-${index}`}/>;
      const day = index - first + 1, date = `${month}-${String(day).padStart(2, "0")}`, info = byDate[date];
      return <button key={date} type="button" aria-label={`Invoice tanggal ${date}`} aria-pressed={serviceDate === date} onClick={() => onSelect(date)}>
        <strong>{day}</strong>{info ? <><small>{info.draft} Draft · {info.final} Final</small>{info.cancelled > 0 && <small>{info.cancelled} Dibatalkan</small>}</> : <small>Belum ada</small>}
      </button>;
    })}</div>
  </section>;
}
