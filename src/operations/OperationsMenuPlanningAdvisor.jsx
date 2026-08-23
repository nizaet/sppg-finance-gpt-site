import React, { useMemo, useState } from "react";
import { BookOpenCheck, ClipboardCopy, Database, RefreshCw, ShieldCheck, Sparkles } from "lucide-react";
import { operationsApi } from "./apiClient";

function todayJakarta() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Jakarta", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date());
}

function formatDate(value) {
  if (!value) return "-";
  const parsed = new Date(`${String(value).slice(0, 10)}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? String(value) : new Intl.DateTimeFormat("id-ID", {
    day: "numeric", month: "long", year: "numeric",
  }).format(parsed);
}

function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "-";
  return new Intl.NumberFormat("id-ID", { maximumFractionDigits: 3 }).format(Number(value));
}

function formatMoney(value) {
  if (value === null || value === undefined || value === "") return "-";
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(Number(value));
}

function copyText(value) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(value);
  return Promise.reject(new Error("Clipboard tidak tersedia"));
}

function draftBrief(context) {
  const target = context?.targetPlanning;
  const lines = [
    `Buatkan DRAFT menu untuk ${context?.site || "site belum dipilih"}.`,
    `Tanggal distribusi: ${context?.requestedDistributionDate || "belum ditentukan"}.`,
    "Gunakan hanya fakta di bawah ini. Jangan mengubah Kalkulator, PO, stok, penerimaan, pembayaran, atau Excel.",
    "Jika gramasi, jumlah porsi, pagu, atau harga tidak ada, tulis sebagai data yang harus dicek; jangan mengarang.",
    "",
    "PLANNING TARGET:",
    target ? JSON.stringify(target, null, 2) : "Belum ada snapshot planning target.",
    "",
    "KNOWLEDGE TERKONFIRMASI:",
    JSON.stringify(context?.confirmedKnowledge || [], null, 2),
    "",
    "DATA YANG MASIH KURANG:",
    JSON.stringify(context?.dataGaps || [], null, 2),
  ];
  return lines.join("\n");
}

export default function OperationsMenuPlanningAdvisor() {
  const [site, setSite] = useState("MAJA");
  const [distributionDate, setDistributionDate] = useState(todayJakarta);
  const [context, setContext] = useState(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const targetItems = context?.targetPlanning?.items || [];
  const history = context?.planningHistory || [];
  const knowledge = context?.confirmedKnowledge || [];
  const gaps = context?.dataGaps || [];
  const brief = useMemo(() => draftBrief(context), [context]);

  const load = async () => {
    setLoading(true); setError(""); setMessage("");
    try {
      const data = await operationsApi.getMenuPlanningPreview({ site, distributionDate });
      setContext(data);
    } catch (err) {
      setContext(null);
      setError(err.message || "Gagal menarik konteks menu.");
    } finally { setLoading(false); }
  };

  const copyDraftBrief = async () => {
    try {
      await copyText(brief);
      setMessage("Brief DRAFT sudah disalin. Tempel ke GPT untuk dibuatkan rekomendasi tanpa mengubah data.");
    } catch (err) { setError(err.message || "Tidak dapat menyalin brief."); }
  };

  return <section className="ops-module menu-advisor">
    <div className="ops-module-header">
      <div>
        <span className="ops-kicker">DRAFT SAJA · BACA DATA</span>
        <h3><Sparkles size={21} /> Asisten Menu</h3>
        <p>Tarik konteks planning dan knowledge terkonfirmasi untuk menyusun draft menu secara aman.</p>
      </div>
      <div className="ops-inline-controls">
        <select aria-label="Site" value={site} onChange={(event) => setSite(event.target.value)}>
          <option value="MAJA">MAJA</option>
          <option value="CEMPLANG">CEMPLANG</option>
        </select>
        <input aria-label="Tanggal distribusi" type="date" value={distributionDate} onChange={(event) => setDistributionDate(event.target.value)} />
        <button type="button" onClick={load} disabled={loading}>
          <RefreshCw size={15} className={loading ? "ops-spin" : ""} />
          {loading ? "Menarik…" : "Tarik konteks"}
        </button>
      </div>
    </div>

    <div className="menu-advisor-boundary">
      <ShieldCheck size={19} />
      <div><strong>Tidak mengubah data.</strong> Halaman ini tidak membuat atau mengedit Kalkulator, PO, penerimaan, pembayaran, maupun Excel.</div>
    </div>
    {error && <div className="ops-error">{error}</div>}
    {message && <div className="ops-success">{message}</div>}

    {!context && !loading && <div className="ops-empty menu-advisor-empty"><Database size={18} /> Pilih site dan tanggal, lalu tekan <strong>Tarik konteks</strong>.</div>}

    {context && <>
      {!context.databaseReady && <div className="ops-error">Database belum tersedia. Tidak ada menu atau harga yang dibuat-buat.</div>}
      <div className="menu-advisor-actions">
        <button type="button" onClick={copyDraftBrief}><ClipboardCopy size={15} /> Salin brief DRAFT untuk GPT</button>
        <span>Data ditarik manual · tanpa simpan otomatis</span>
      </div>

      <div className="menu-advisor-grid">
        <article className="menu-advisor-card">
          <header><BookOpenCheck size={17} /><div><strong>Planning target</strong><small>{context.targetPlanning ? `${formatDate(context.targetPlanning.distributionDate)} · ${context.targetPlanning.sourceSystem || "sumber tidak tercatat"}` : "Belum ditemukan"}</small></div></header>
          {context.targetPlanning ? <>
            <div className="ops-summary-strip">
              <span>{targetItems.length} bahan</span>
              <span>Masak: {context.targetPlanning.cookingAt ? formatDate(context.targetPlanning.cookingAt) : "belum tercatat"}</span>
              <span>Status: {context.targetPlanning.status || "-"}</span>
            </div>
            <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Bahan</th><th>Kategori</th><th>Rencana</th><th>Harga rencana</th><th>Vendor</th></tr></thead><tbody>
              {targetItems.map((item, index) => <tr key={`${item.itemCode || item.itemName}-${index}`}><td><strong>{item.itemName || "Tanpa nama"}</strong>{item.notes && <div className="ops-muted">{item.notes}</div>}</td><td>{item.categoryCode || "-"}</td><td>{formatNumber(item.plannedQty)} {item.unit || ""}</td><td>{formatMoney(item.planningPrice)}</td><td>{item.preferredVendorCode || "-"}</td></tr>)}
              {targetItems.length === 0 && <tr><td colSpan="5" className="ops-empty-cell">Snapshot belum memiliki rincian bahan.</td></tr>}
            </tbody></table></div>
          </> : <p className="ops-muted menu-advisor-card-copy">Tidak ada snapshot aktif untuk tanggal ini. Asisten tidak boleh menyusun kebutuhan bahan tanpa planning.</p>}
        </article>

        <article className="menu-advisor-card">
          <header><ShieldCheck size={17} /><div><strong>Data yang perlu dicek</strong><small>Harus diselesaikan sebelum menu disebut hemat pagu.</small></div></header>
          {gaps.length ? <ul className="menu-advisor-gaps">{gaps.map((gap) => <li key={gap.code}><strong>{gap.code}</strong><span>{gap.message}</span></li>)}</ul> : <p className="ops-muted menu-advisor-card-copy">Tidak ada kekosongan data yang terdeteksi dari konteks ini. Tetap lakukan persetujuan manusia sebelum tindakan operasional.</p>}
        </article>
      </div>

      <div className="menu-advisor-grid">
        <article className="menu-advisor-card">
          <header><BookOpenCheck size={17} /><div><strong>Knowledge terkonfirmasi</strong><small>Hanya fakta yang sudah dikonfirmasi, bukan tebakan model.</small></div></header>
          {knowledge.length ? <ul className="menu-advisor-knowledge">{knowledge.map((item, index) => <li key={`${item.topic || "knowledge"}-${index}`}><strong>{item.topic || item.scopeType || "Knowledge"}</strong><span>{item.statement}</span><small>{item.site || "GLOBAL"} · bukti {item.evidenceCount || 0}</small></li>)}</ul> : <p className="ops-muted menu-advisor-card-copy">Belum ada knowledge terkonfirmasi yang relevan.</p>}
        </article>

        <article className="menu-advisor-card">
          <header><Database size={17} /><div><strong>Planning sebelumnya</strong><small>Referensi pola; bukan instruksi untuk menyalin menu.</small></div></header>
          {history.length ? <ul className="menu-advisor-history">{history.map((item) => <li key={item.snapshotId}><strong>{formatDate(item.distributionDate)}</strong><span>{item.items?.length || 0} bahan · {item.sourceSystem || "sumber tidak tercatat"}</span></li>)}</ul> : <p className="ops-muted menu-advisor-card-copy">Belum ada snapshot planning sebelumnya yang dapat dipakai sebagai pembanding.</p>}
        </article>
      </div>
    </>}
  </section>;
}
