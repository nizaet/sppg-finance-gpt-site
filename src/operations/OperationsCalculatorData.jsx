import React, { useMemo, useState } from "react";
import { CheckCircle2, FileJson, ShieldCheck, UploadCloud } from "lucide-react";
import { operationsApi } from "./apiClient";

const TYPE_LABEL = {
  PRICES: "Master Harga",
  GRAMASI: "Aturan Gramasi",
  RECIPES: "Master Resep",
  DAILY_PLANS: "Rencana Harian",
};

function extractItems(parsed) {
  if (Array.isArray(parsed)) return parsed;
  for (const key of ["items", "data", "plans", "recipes", "prices", "gramasi"]) {
    if (Array.isArray(parsed?.[key])) return parsed[key];
  }
  return [];
}

function detectType(items) {
  const first = items.find((item) => item && typeof item === "object") || {};
  if ((first.date || first.tanggal) && (Array.isArray(first.recipes) || first.shoppingListJSON)) return "DAILY_PLANS";
  if (Array.isArray(first.ingredients)) return "RECIPES";
  if (Object.hasOwn(first, "price") || Object.hasOwn(first, "grams_per_unit")) return "PRICES";
  if (Object.hasOwn(first, "kecil") && Object.hasOwn(first, "besar")) return "GRAMASI";
  return "";
}

async function digestItem(item) {
  const bytes = new TextEncoder().encode(JSON.stringify(item));
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

function chunks(items, size) {
  const result = [];
  for (let index = 0; index < items.length; index += size) result.push(items.slice(index, index + size));
  return result;
}

export default function OperationsCalculatorData() {
  const [site, setSite] = useState("");
  const [fileName, setFileName] = useState("");
  const [dataType, setDataType] = useState("");
  const [sourceItems, setSourceItems] = useState([]);
  const [rows, setRows] = useState([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const selectedCount = rows.filter((row) => row.selected).length;
  const visibleRows = useMemo(() => {
    const needle = query.toLowerCase().trim();
    if (!needle) return rows;
    return rows.filter((row) => `${row.date || ""} ${row.planName || ""} ${row.name || ""} ${row.status}`.toLowerCase().includes(needle));
  }, [rows, query]);

  const resetPreview = () => {
    setRows([]);
    setMessage("");
    setError("");
  };

  const chooseFile = async (event) => {
    const file = event.target.files?.[0];
    resetPreview();
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text());
      const items = extractItems(parsed);
      const detected = detectType(items);
      if (!items.length || !detected) throw new Error("Format belum dikenali sebagai harga, gramasi, resep, atau rencana harian.");
      setFileName(file.name);
      setSourceItems(items);
      setDataType(detected);
    } catch (err) {
      setFileName("");
      setSourceItems([]);
      setDataType("");
      setError(err.message || "File JSON tidak valid.");
    }
  };

  const preview = async () => {
    if (!site) return setError("Pilih target Kalkulator Maja atau Cemplang terlebih dahulu.");
    if (!sourceItems.length || !dataType) return setError("Pilih file backup JSON terlebih dahulu.");
    if (site === "BOTH" && dataType === "DAILY_PLANS") return setError("Rencana harian harus dipilih untuk satu dapur agar tidak salah memasukkan tanggal. Pilih Maja atau Cemplang.");
    setLoading(true);
    setError("");
    setMessage("");
    try {
      let result;
      if (dataType === "DAILY_PLANS") {
        const summaries = await Promise.all(sourceItems.map(async (item, index) => ({
          client_key: String(index),
          date: String(item.date || item.tanggal || ""),
          plan_name: String(item.planName || item.name || ""),
          item_hash: await digestItem(item),
          menu_count: Array.isArray(item.recipes) ? item.recipes.length : 0,
        })));
        result = await operationsApi.previewCalculatorPlans({ site, source_ref: fileName, items: summaries });
      } else {
        const payloadItems = sourceItems.map((item, index) => ({ client_key: String(index), payload: item }));
        if (site === "BOTH") {
          const [maja, cemplang] = await Promise.all(["MAJA", "CEMPLANG"].map((targetSite) => operationsApi.previewCalculatorImport({
            site: targetSite, data_type: dataType, source_ref: fileName, items: payloadItems,
          })));
          const cemplangByKey = new Map((cemplang.items || []).map((row) => [row.clientKey, row]));
          result = { items: (maja.items || []).map((majaRow) => {
            const cemplangRow = cemplangByKey.get(majaRow.clientKey) || {};
            const statuses = [majaRow.status, cemplangRow.status];
            const status = statuses.includes("INVALID") ? "INVALID" : statuses.includes("DUPLICATE_KEY_IN_FILE") ? "DUPLICATE_KEY_IN_FILE" : statuses.includes("CHANGED") ? "CHANGED" : statuses.every((value) => value === "UNCHANGED") ? "UNCHANGED" : "NEW";
            return {
              ...majaRow,
              status,
              siteStatuses: { MAJA: majaRow.status, CEMPLANG: cemplangRow.status },
              selectable: ["NEW", "CHANGED"].includes(status),
              defaultSelected: status === "NEW",
            };
          }) };
        } else {
          result = await operationsApi.previewCalculatorImport({
            site,
            data_type: dataType,
            source_ref: fileName,
            items: payloadItems,
          });
        }
      }
      setRows((result.items || []).map((row) => ({ ...row, selected: Boolean(row.defaultSelected) })));
      setMessage(`Preview selesai. Tidak ada data yang ditulis. ${result.items?.length || 0} baris diperiksa.`);
    } catch (err) {
      setError(err.message || "Preview gagal.");
    } finally {
      setLoading(false);
    }
  };

  const toggle = (clientKey) => {
    setRows((current) => {
      const target = current.find((row) => row.clientKey === clientKey);
      if (!target?.selectable) return current;
      const nextValue = !target.selected;
      return current.map((row) => {
        if (row.clientKey === clientKey) return { ...row, selected: nextValue };
        if (nextValue && dataType === "DAILY_PLANS" && row.date && row.date === target.date) return { ...row, selected: false };
        return row;
      });
    });
  };

  const selectNew = (includeChanged = false) => {
    setRows((current) => current.map((row) => ({
      ...row,
      selected: row.selectable && (row.status === "NEW" || (includeChanged && row.status === "CHANGED")),
    })));
  };

  const commit = async () => {
    const selected = rows.filter((row) => row.selected);
    if (!selected.length) return setError("Centang data yang akan dimasukkan terlebih dahulu.");
    const changed = selected.filter((row) => row.status === "CHANGED").length;
    const targetLabel = site === "BOTH" ? "Maja dan Cemplang" : site;
    const prompt = dataType === "DAILY_PLANS"
      ? `Simpan ${selected.length} rencana baru ke Kalkulator ${site}? Tanggal yang sudah ada akan tetap dilewati dan tidak ditimpa.`
      : `Simpan ${selected.length} data ${TYPE_LABEL[dataType]} ke Kalkulator ${targetLabel}? ${changed} data lama yang dipilih akan diperbarui dan versi sebelumnya tetap tercatat di audit.`;
    if (!window.confirm(prompt)) return;

    setLoading(true);
    setError("");
    setMessage("");
    try {
      const selectedItems = selected.map((row) => ({
        client_key: row.clientKey,
        payload: sourceItems[Number(row.clientKey)],
      }));
      const batchSize = dataType === "DAILY_PLANS" ? 5 : 25;
      let committed = 0;
      let skipped = 0;
      const targetSites = site === "BOTH" ? ["MAJA", "CEMPLANG"] : [site];
      for (const targetSite of targetSites) {
        for (const batch of chunks(selectedItems, batchSize)) {
          const result = await operationsApi.commitCalculatorImport({
            site: targetSite,
            data_type: dataType,
            source_ref: fileName,
            actor: "YAYASAN",
            items: batch,
          });
          committed += Number(result.committedCount || 0);
          skipped += Number(result.skippedCount || 0);
        }
      }
      setMessage(`${committed} penulisan berhasil ke Kalkulator ${targetLabel}. ${skipped} dilewati. Tidak ada rencana lama yang ditimpa.`);
      await preview();
    } catch (err) {
      setError(err.message || "Penyimpanan gagal.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="ops-domain-stack">
      <section className="ops-module">
        <div className="ops-module-header">
          <div>
            <span className="ops-kicker">SATU PINTU · FIRESTORE KALKULATOR + AUDIT PUSAT</span>
            <h3>Data Kalkulator</h3>
            <p>Upload harga, gramasi, resep, atau rencana harian di sini. Preview dan pilihan target wajib dilakukan sebelum data masuk ke Kalkulator Maja atau Cemplang.</p>
          </div>
          <ShieldCheck size={34} />
        </div>
        {error && <div className="ops-error">{error}</div>}
        {message && <div className="ops-success">{message}</div>}
        <div className="ops-form-grid">
          <label>Target kalkulator
            <select value={site} onChange={(event) => { setSite(event.target.value); resetPreview(); }}>
              <option value="">— Pilih dapur —</option>
              <option value="MAJA">Kalkulator Maja</option>
              <option value="CEMPLANG">Kalkulator Cemplang</option>
              <option value="BOTH">Maja + Cemplang (master saja)</option>
            </select>
          </label>
          <label>File backup JSON<input type="file" accept=".json,application/json" onChange={chooseFile} /></label>
          <label>Jenis terdeteksi<input value={dataType ? TYPE_LABEL[dataType] : "Belum ada file"} disabled /></label>
        </div>
        <div className="ops-notice">
          <strong>Aturan aman:</strong> rencana dengan tanggal yang sudah ada selalu dikunci dan dilewati. Jika satu file memiliki dua rencana pada tanggal yang sama, pilih hanya satu. Harga/resep/gramasi yang berubah tidak dipilih otomatis.
        </div>
        <div className="ops-chat-actions">
          <button type="button" onClick={preview} disabled={loading || !site || !sourceItems.length}><UploadCloud size={15} /> {loading ? "Memeriksa…" : "Preview File"}</button>
          <button type="button" onClick={commit} disabled={loading || selectedCount === 0}><CheckCircle2 size={15} /> Simpan {selectedCount} Terpilih</button>
        </div>
      </section>

      {rows.length > 0 && <section className="ops-module">
        <div className="ops-module-header">
          <div><span className="ops-kicker">PREVIEW BELUM MENULIS DATA</span><h3>Pilih Data yang Masuk</h3><p>{fileName} · {TYPE_LABEL[dataType]} · target {site}</p></div>
          <div className="ops-inline-controls">
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Cari tanggal / nama / status" />
            <button type="button" onClick={() => selectNew(false)}>Pilih Data Baru</button>
            {dataType !== "DAILY_PLANS" && <button type="button" onClick={() => selectNew(true)}>Pilih Baru + Berubah</button>}
            <button type="button" onClick={() => setRows((current) => current.map((row) => ({ ...row, selected: false })))}>Kosongkan</button>
          </div>
        </div>
        <div className="ops-summary-strip"><span>Total <strong>{rows.length}</strong></span><span>Terpilih <strong>{selectedCount}</strong></span><span>Data baru <strong>{rows.filter((row) => row.status === "NEW").length}</strong></span><span>Sudah ada <strong>{rows.filter((row) => row.status === "EXISTING_DATE").length}</strong></span><span>Berubah <strong>{rows.filter((row) => row.status === "CHANGED").length}</strong></span></div>
        <div className="ops-table-wrap">
          <table className="ops-table">
            <thead><tr><th>Pilih</th><th>{dataType === "DAILY_PLANS" ? "Tanggal" : "Kunci"}</th><th>Nama</th><th>Status</th><th>Keterangan</th></tr></thead>
            <tbody>
              {visibleRows.map((row) => <tr key={row.clientKey}>
                <td><input type="checkbox" checked={Boolean(row.selected)} disabled={!row.selectable} onChange={() => toggle(row.clientKey)} /></td>
                <td><strong>{row.date || row.recordKey}</strong></td>
                <td>{row.planName || row.name || "-"}{row.menuCount != null && <div className="ops-muted">{row.menuCount} menu</div>}</td>
                <td>{row.status}{row.siteStatuses && <div className="ops-muted">Maja: {row.siteStatuses.MAJA} · Cemplang: {row.siteStatuses.CEMPLANG}</div>}</td>
                <td>{row.status === "EXISTING_DATE" ? "Dikunci: tanggal sudah ada, tidak akan ditimpa." : row.status === "DUPLICATE_DATE_IN_FILE" ? "Ada lebih dari satu rencana pada tanggal ini; pilih satu saja." : row.status === "CHANGED" ? "Versi kalkulator berbeda; centang jika memang ingin memperbarui master." : row.status === "UNCHANGED" ? "Isinya sama; tidak perlu ditulis lagi." : "Siap dipilih."}</td>
              </tr>)}
              {!visibleRows.length && <tr><td colSpan="5" className="ops-empty-cell"><FileJson size={18} /> Tidak ada baris sesuai pencarian.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>}
    </div>
  );
}
