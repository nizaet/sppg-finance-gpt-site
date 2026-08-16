import React, { useEffect, useMemo, useState } from "react";
import { CheckCircle2, ClipboardPaste, Eye, GitMerge, Pencil, Plus, RefreshCw, Save, Search, XCircle } from "lucide-react";
import { operationsApi } from "./apiClient";

const qty = (value) => Number(value || 0).toLocaleString("id-ID", { maximumFractionDigits: 4 });
const localDateTime = (value) => value ? new Date(value).toLocaleString("id-ID", {
  timeZone: "Asia/Jakarta", day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
}) : "-";

export default function OperationsInventory({ fixedSite = "" }) {
  const [site, setSite] = useState(fixedSite || "MAJA");
  const [search, setSearch] = useState("");
  const [items, setItems] = useState([]);
  const [balanceMeta, setBalanceMeta] = useState(null);
  const [history, setHistory] = useState([]);
  const [soText, setSoText] = useState("");
  const [stockDate, setStockDate] = useState("");
  const [reporter, setReporter] = useState("");
  const [preview, setPreview] = useState(null);
  const [reviewedItems, setReviewedItems] = useState([]);
  const [sourceExternalId, setSourceExternalId] = useState("");
  const [masters, setMasters] = useState([]);
  const [masterForm, setMasterForm] = useState({ code: "", canonical_name: "", category_code: "", base_unit: "kg", aliases: "" });
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [selectedBaselineIds, setSelectedBaselineIds] = useState([]);

  useEffect(() => {
    if (fixedSite && site !== fixedSite) {
      setSite(fixedSite);
      setSearch("");
      setPreview(null);
    }
  }, [fixedSite, site]);

  const activeSite = fixedSite || site;

  const load = async (searchValue = search) => {
    setLoading(true);
    setError("");
    try {
      const [data, opnameData, masterData] = await Promise.all([
        operationsApi.getInventoryBalances({ site: activeSite, search: searchValue, limit: 1000 }),
        operationsApi.getStockOpnames({ location: activeSite, limit: 50 }),
        operationsApi.getInventoryItems(""),
      ]);
      setItems(data?.items || []);
      setBalanceMeta(data || null);
      setHistory(opnameData?.items || []);
      setSelectedBaselineIds([]);
      setMasters(masterData?.items || []);
    } catch (err) {
      setError(err.message || "Gagal mengambil saldo gudang");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(""); }, [activeSite]);

  const previewSo = async () => {
    if (!soText.trim()) {
      setError("Paste laporan SO WhatsApp terlebih dahulu.");
      return;
    }
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const data = await operationsApi.previewStockOpname({ location: activeSite, text: soText, stock_date: stockDate || null, reporter: reporter || null });
      setPreview(data);
      setSourceExternalId("");
      setReviewedItems((data?.items || []).map((item, index) => ({
        client_key: String(item.clientKey ?? index),
        include: item.selected !== false,
        area_code: item.areaCode || "UNSPECIFIED",
        raw_item_name: item.itemName || "",
        canonical_item_name: item.canonicalItemName || item.itemName || "",
        inventory_item_code: item.inventoryItemCode || "",
        qty: Number(item.qty || 0),
        unit: item.unit || "",
        raw_line: item.rawLine || item.itemName || "",
        classification_status: item.classificationStatus || "UNMAPPED",
        classification_method: item.classificationMethod || "",
      })));
      if (!stockDate && data?.stockDate) setStockDate(data.stockDate);
    } catch (err) {
      setError(err.message || "Gagal membaca laporan SO");
    } finally {
      setSaving(false);
    }
  };

  const commitSo = async () => {
    const selected = reviewedItems.filter((item) => item.include);
    if (!preview?.canCommit || !selected.length) return;
    const excluded = reviewedItems.length - selected.length;
    if (!window.confirm(
      `Simpan SO ${activeSite} tanggal ${preview.stockDate} dengan ${selected.length} komponen terpilih?\n\n` +
      `${excluded} komponen dikeluarkan. Nama kanonik, Master, qty, dan unit yang disimpan mengikuti hasil edit terakhir di tabel.`
    )) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const data = await operationsApi.commitStockOpname({ location: activeSite, text: soText, stock_date: stockDate || null, source_external_id: sourceExternalId || null, reporter: reporter || null, reviewed_items: reviewedItems });
      setMessage(data.duplicate ? `SO ini sudah pernah disimpan (#${data.stockOpnameId}).` : `SO ${activeSite} tersimpan sebagai SO AKTIF baru #${data.stockOpnameId}: ${data.itemCount} item masuk, ${excluded} item dikeluarkan. Versi lama tetap menjadi histori dan tidak dihitung sebagai saldo aktif.`);
      setPreview(null);
      setReviewedItems([]);
      setSoText("");
      setSourceExternalId("");
      await load("");
    } catch (err) {
      setError(err.message || "Gagal menyimpan laporan SO");
    } finally {
      setSaving(false);
    }
  };

  const detailItems = (detail) => (detail?.items || []).map((item) => ({
    client_key: `${detail.stockOpname.id}:${item.id}`,
    include: true,
    area_code: item.area_code || "UNSPECIFIED",
    raw_item_name: item.raw_item_name || item.canonical_item_name || "",
    canonical_item_name: item.canonical_item_name || item.raw_item_name || "",
    inventory_item_code: item.inventory_item_code || "",
    qty: Number(item.qty || 0),
    unit: item.unit || "",
    raw_line: item.raw_line || item.raw_item_name || "",
    classification_status: item.classification_status || "USER_REVIEWED",
    classification_method: item.classification_method || "BASELINE_CORRECTION",
  }));

  const openBaselineCorrection = async (row, mergeSameDate = false, explicitRows = null) => {
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const targets = explicitRows || (mergeSameDate ? history.filter((item) => String(item.stock_date) === String(row.stock_date)) : [row]);
      const details = await Promise.all(targets.map((item) => operationsApi.getStockOpname(item.id)));
      const correctedItems = details.flatMap(detailItems);
      if (!correctedItems.length) throw new Error("Baseline SO tidak memiliki item.");
      const ids = details.map((detail) => detail.stockOpname.id);
      setSoText(details.map((detail) => detail.stockOpname.raw_text || "").filter(Boolean).join("\n\n--- GABUNGAN SO ---\n\n"));
      setStockDate(String(row.stock_date));
      setReporter(details.map((detail) => detail.stockOpname.reporter).filter(Boolean)[0] || "");
      setReviewedItems(correctedItems);
      setPreview({ canCommit: true, stockDate: String(row.stock_date), items: correctedItems, warnings: [] });
      const isMerge = mergeSameDate || targets.length > 1;
      setSourceExternalId(isMerge ? `consolidated:${row.stock_date}:${ids.join("-")}` : `correction:${row.id}`);
      setMessage(isMerge
        ? `${details.length} baseline tanggal ${row.stock_date} dibuka menjadi satu koreksi. Periksa item, keluarkan duplikat bila ada, lalu simpan satu baseline gabungan.`
        : `Baseline #${row.id} dibuka sebagai koreksi. Bukti lama tidak dihapus; hasil edit akan menjadi baseline terbaru.`);
      window.setTimeout(() => document.getElementById("inventory-so-entry")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
    } catch (err) {
      setError(err.message || "Gagal membuka baseline SO");
    } finally {
      setSaving(false);
    }
  };

  const updateReviewed = (clientKey, patch) => {
    setReviewedItems((current) => current.map((item) => item.client_key === clientKey ? { ...item, ...patch } : item));
  };

  const selectMaster = (clientKey, code) => {
    const master = masters.find((item) => item.code === code);
    if (!master) {
      updateReviewed(clientKey, { inventory_item_code: "", classification_status: "USER_REVIEWED" });
      return;
    }
    updateReviewed(clientKey, {
      inventory_item_code: master.code,
      canonical_item_name: master.canonical_name,
      unit: master.base_unit || "",
      classification_status: "MATCHED",
      classification_method: "USER_SELECTED_MASTER",
    });
  };

  const saveMaster = async () => {
    if (!masterForm.canonical_name.trim()) return setError("Nama kanonik Master Barang wajib diisi.");
    if (!window.confirm(`Simpan Master Barang “${masterForm.canonical_name}” beserta aliasnya?`)) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const result = await operationsApi.saveInventoryItem({
        code: masterForm.code.trim() || null,
        canonical_name: masterForm.canonical_name.trim(),
        category_code: masterForm.category_code.trim() || null,
        base_unit: masterForm.base_unit.trim() || null,
        aliases: masterForm.aliases.split(",").map((value) => value.trim()).filter(Boolean),
      }, true);
      const masterData = await operationsApi.getInventoryItems("");
      setMasters(masterData?.items || []);
      setMasterForm({ code: "", canonical_name: "", category_code: "", base_unit: "kg", aliases: "" });
      setMessage(`Master Barang ${result.canonicalName} (${result.code}) tersimpan. Sekarang dapat dipilih pada baris SO.`);
    } catch (err) {
      setError(err.message || "Gagal menyimpan Master Barang");
    } finally {
      setSaving(false);
    }
  };

  const editMaster = (master) => {
    setMasterForm({
      code: master.code || "",
      canonical_name: master.canonical_name || "",
      category_code: master.category_code || "",
      base_unit: master.base_unit || "",
      aliases: (master.aliases || []).join(", "),
    });
    setMessage(`Master ${master.canonical_name} dibuka untuk diedit.`);
  };

  const negativeCount = useMemo(() => items.filter((x) => Number(x.projected_balance ?? x.balance ?? 0) < 0).length, [items]);
  const lowConfidenceCount = useMemo(() => items.filter((x) => x.confidence === "LOW").length, [items]);
  const historyRows = useMemo(() => {
    const byDate = new Map();
    history.forEach((row) => {
      const key = String(row.stock_date || "");
      if (!byDate.has(key)) byDate.set(key, []);
      byDate.get(key).push(row);
    });
    return history.map((row) => {
      const versions = byDate.get(String(row.stock_date || "")) || [];
      const index = versions.findIndex((item) => item.id === row.id);
      const source = String(row.source_external_id || "");
      return {
        ...row,
        version_no: Math.max(1, versions.length - index),
        version_count: versions.length,
        is_date_latest: index === 0,
        is_balance_active: Number(row.id) === Number(balanceMeta?.latestStockOpnameId),
        result_type: source.startsWith("consolidated:") ? "HASIL GABUNGAN" : source.startsWith("correction:") ? "HASIL KOREKSI" : "INPUT SO",
      };
    });
  }, [history, balanceMeta?.latestStockOpnameId]);

  const toggleBaselineSelection = (row) => {
    setSelectedBaselineIds((current) => {
      if (current.includes(row.id)) return current.filter((id) => id !== row.id);
      const selectedRows = history.filter((item) => current.includes(item.id));
      if (selectedRows.length && String(selectedRows[0].stock_date) !== String(row.stock_date)) {
        setMessage(`Pilihan dipindahkan ke tanggal ${row.stock_date}. SO yang digabungkan wajib berasal dari tanggal yang sama.`);
        return [row.id];
      }
      return [...current, row.id];
    });
  };

  const mergeSelectedBaselines = () => {
    const selected = history.filter((row) => selectedBaselineIds.includes(row.id));
    if (selected.length < 2) {
      setError("Pilih minimal dua versi SO pada tanggal yang sama untuk digabungkan.");
      return;
    }
    openBaselineCorrection(selected[0], false, selected);
  };

  return (
    <div className="ops-domain-stack">
      <section className="ops-module" id="inventory-so-entry">
        <div className="ops-module-header">
          <div>
            <span className="ops-kicker">STOCK OPNAME WHATSAPP → BASELINE GUDANG</span>
            <h3>Masukkan Laporan SO</h3>
            <p>Teks asli, nama aktual, hasil klasifikasi Master Barang, dan komponen beda satuan disimpan terpisah. Preview wajib dicek sebelum menjadi baseline.</p>
          </div>
          <div className="ops-inline-controls">
            <select value={activeSite} disabled={Boolean(fixedSite)} onChange={(e) => { setSite(e.target.value); setSearch(""); setPreview(null); }}><option value="MAJA">Gudang Dapur Maja</option><option value="CEMPLANG">Gudang Dapur Cemplang</option><option value="KOPERASI">Gudang Koperasi</option></select>
          </div>
        </div>
        {error && <div className="ops-error">{error}</div>}
        {message && <div className="ops-success">{message}</div>}
        <div className="ops-form-grid">
          <label>Tanggal SO (boleh kosong jika tertulis di chat)<input type="date" value={stockDate} onChange={(e) => setStockDate(e.target.value)} /></label>
          <label>Pelapor<input value={reporter} onChange={(e) => setReporter(e.target.value)} placeholder="contoh: Bidin" /></label>
          <label>Lokasi<input value={activeSite === "KOPERASI" ? "Gudang Koperasi" : `Gudang Dapur ${activeSite}`} disabled /></label>
        </div>
        <textarea className="ops-chat-input" rows="9" value={soText} onChange={(e) => { setSoText(e.target.value); setPreview(null); setSourceExternalId(""); }} placeholder="Paste laporan SO BARANG dari WhatsApp di sini…" />
        <div className="ops-chat-actions">
          <button type="button" onClick={previewSo} disabled={saving || !soText.trim()}><ClipboardPaste size={15} /> {saving ? "Membaca…" : "Preview SO"}</button>
          <button type="button" onClick={commitSo} disabled={saving || !preview?.canCommit || !reviewedItems.some((item) => item.include)}><CheckCircle2 size={15} /> Simpan {reviewedItems.filter((item) => item.include).length} Item Terpilih</button>
        </div>

        {preview && (
          <div className="ops-draft-group">
            <div className="ops-summary-strip">
              <span>Tanggal <strong>{preview.stockDate}</strong></span><span>Komponen <strong>{reviewedItems.length}</strong></span><span>Dipilih <strong>{reviewedItems.filter((item) => item.include).length}</strong></span><span>Dikeluarkan <strong>{reviewedItems.filter((item) => !item.include).length}</strong></span>
            </div>
            <div className="ops-notice">Item salah seperti “mi telur ayam” dapat dikeluarkan tanpa menahan item lain. Ukuran 90×120/90×100 tetap menjadi nama jenis plastik; qty dapat diedit sendiri.</div>
            {preview.warnings?.length > 0 && <div className="ops-notice">{preview.warnings.map((warning) => <div key={warning}>⚠ {warning}</div>)}</div>}
            <div className="ops-table-wrap">
              <table className="ops-table">
                <thead><tr><th>Simpan?</th><th>Area</th><th>Nama dari SO</th><th>Master Barang</th><th>Jenis kanonik — EDIT</th><th>Qty — EDIT</th><th>Unit — EDIT</th><th>Status</th></tr></thead>
                <tbody>{reviewedItems.map((item) => <tr key={item.client_key}>
                  <td><button type="button" onClick={() => updateReviewed(item.client_key, { include: !item.include })}>{item.include ? <XCircle size={14} /> : <Plus size={14} />} {item.include ? "Keluarkan" : "Masukkan"}</button></td>
                  <td><input value={item.area_code} disabled={!item.include} onChange={(e) => updateReviewed(item.client_key, { area_code: e.target.value })} /></td>
                  <td><strong>{item.raw_item_name}</strong><div className="ops-muted">{item.raw_line}</div></td>
                  <td><select value={item.inventory_item_code} disabled={!item.include} onChange={(e) => selectMaster(item.client_key, e.target.value)}><option value="">Tanpa Master / nama manual</option>{masters.map((master) => <option key={master.code} value={master.code}>{master.canonical_name} · {master.base_unit || "-"}</option>)}</select></td>
                  <td><input value={item.canonical_item_name} disabled={!item.include || Boolean(item.inventory_item_code)} onChange={(e) => updateReviewed(item.client_key, { canonical_item_name: e.target.value, classification_status: "USER_REVIEWED" })} /></td>
                  <td><input className="ops-qty-input" type="number" min="0" step="0.0001" value={item.qty} disabled={!item.include} onChange={(e) => updateReviewed(item.client_key, { qty: Number(e.target.value) })} /></td>
                  <td><input value={item.unit} disabled={!item.include} onChange={(e) => updateReviewed(item.client_key, { unit: e.target.value })} placeholder="kg / pcs / unit / dus" /></td>
                  <td>{item.include ? item.classification_status : "DIKELUARKAN"}<div className="ops-muted">{item.classification_method}</div></td>
                </tr>)}</tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      <section className="ops-module">
        <div className="ops-module-header"><div><span className="ops-kicker">MASTER BARANG & ALIAS</span><h3>Tambah atau Perbarui Klasifikasi</h3><p>Contoh: buat “Mi telur ayam” sebagai jenis tersendiri lalu masukkan alias “mi telur”, “mie telur ayam”. Setelah disimpan, laporan berikutnya lebih cepat dikenali.</p></div></div>
        <div className="ops-form-grid">
          <label>Kode (opsional)<input value={masterForm.code} onChange={(e) => setMasterForm((current) => ({ ...current, code: e.target.value.toUpperCase() }))} placeholder="MI_TELUR_AYAM" /></label>
          <label>Nama kanonik<input value={masterForm.canonical_name} onChange={(e) => setMasterForm((current) => ({ ...current, canonical_name: e.target.value }))} placeholder="Mi telur ayam" /></label>
          <label>Kategori<input value={masterForm.category_code} onChange={(e) => setMasterForm((current) => ({ ...current, category_code: e.target.value.toUpperCase() }))} placeholder="BAHAN_KERING" /></label>
          <label>Satuan dasar<input value={masterForm.base_unit} onChange={(e) => setMasterForm((current) => ({ ...current, base_unit: e.target.value }))} placeholder="dus / pcs / kg" /></label>
          <label>Alias dipisah koma<input value={masterForm.aliases} onChange={(e) => setMasterForm((current) => ({ ...current, aliases: e.target.value }))} placeholder="mi telur, mie telur ayam" /></label>
          <label>Aksi<div className="ops-row-actions"><button type="button" onClick={saveMaster} disabled={saving || !masterForm.canonical_name.trim()}><Save size={14} /> Simpan Master</button></div></label>
        </div>
        <div className="ops-summary-strip"><span>Master aktif <strong>{masters.length}</strong></span></div>
        <div className="ops-table-wrap">
          <table className="ops-table">
            <thead><tr><th>Kode</th><th>Nama Master</th><th>Kategori</th><th>Satuan</th><th>Alias</th><th>Aksi</th></tr></thead>
            <tbody>{masters.map((master) => <tr key={master.code}><td>{master.code}</td><td><strong>{master.canonical_name}</strong></td><td>{master.category_code || "-"}</td><td>{master.base_unit || "-"}</td><td>{(master.aliases || []).join(" · ") || "-"}</td><td><button type="button" onClick={() => editMaster(master)}><Pencil size={14} /> Edit Master</button></td></tr>)}</tbody>
          </table>
        </div>
      </section>

      <section className="ops-module">
        <div className="ops-module-header">
          <div>
            <span className="ops-kicker">SO + MOVEMENT + PEMAKAIAN</span>
            <h3>Saldo & Proyeksi Gudang</h3>
            <p>“Aktual terhitung” berasal dari SO dan fakta sesudahnya. “Proyeksi” juga mengurangi planning yang belum memiliki laporan pemakaian aktual.</p>
          </div>
          <div className="ops-inline-controls">
            <input value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load(search)} placeholder="Cari barang" />
            <button type="button" onClick={() => load(search)} disabled={loading}><Search size={15} /> Cari</button>
            <button type="button" onClick={() => { setSearch(""); load(""); }} disabled={loading}><RefreshCw size={15} /> Semua</button>
          </div>
        </div>
        <div className="ops-summary-strip">
          <span>Item <strong>{items.length}</strong></span><span>SO terakhir <strong>{balanceMeta?.latestStockOpnameDate || "belum ada"}</strong></span><span>Proyeksi s.d. <strong>{balanceMeta?.projectionThrough || "-"}</strong></span><span>Saldo negatif <strong>{negativeCount}</strong></span><span>Keyakinan rendah <strong>{lowConfidenceCount}</strong></span>
        </div>
        {balanceMeta?.baselineNeedsConsolidation && <div className="ops-error">
          Terdeteksi {balanceMeta.sameDateStockOpnameCount} baseline terpisah pada {balanceMeta.latestStockOpnameDate}. Saldo saat ini hanya memakai baseline paling baru sehingga item terlihat sedikit.
          <div className="ops-row-actions"><button type="button" onClick={() => {
            const row = history.find((item) => String(item.stock_date) === String(balanceMeta.latestStockOpnameDate));
            if (row) openBaselineCorrection(row, true);
          }} disabled={saving}><Plus size={14} /> Gabungkan dan Koreksi Semua SO Tanggal Ini</button></div>
        </div>}
        <div className="ops-table-wrap">
          <table className="ops-table">
            <thead><tr><th>Barang</th><th>SO</th><th>Movement</th><th>Pemakaian Aktual</th><th>Pemakaian Rencana</th><th>Aktual Terhitung</th><th>Proyeksi</th><th>Unit</th><th>Dasar</th></tr></thead>
            <tbody>
              {items.map((item, idx) => <tr key={`${item.item_name}-${item.unit}-${idx}`}><td><strong>{item.item_name}</strong><div className="ops-muted">{item.raw_item_names?.join(" · ")}</div></td><td>{qty(item.so_qty)}</td><td>{qty(item.movement_delta)}</td><td>−{qty(item.actual_usage_depletion)}</td><td>−{qty(item.planned_depletion)}</td><td>{qty(item.actual_balance)}</td><td><strong>{qty(item.projected_balance)}</strong></td><td>{item.unit || "-"}</td><td>{item.stock_basis}<div className="ops-muted">SO {item.stock_as_of || "-"} · keyakinan {item.confidence}</div></td></tr>)}
              {!loading && items.length === 0 && <tr><td colSpan="9" className="ops-empty-cell">Belum ada SO atau movement stok untuk lokasi/filter ini.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="ops-module">
        <div className="ops-module-header"><div><span className="ops-kicker">VERSI & STATUS SO</span><h3>Histori Stock Opname</h3><p>Saldo hanya memakai satu baris berlabel <strong>AKTIF UNTUK SALDO</strong>. Baris lain adalah bukti/versi lama dan tidak dijumlahkan otomatis.</p></div><div className="ops-row-actions"><button type="button" onClick={mergeSelectedBaselines} disabled={saving || selectedBaselineIds.length < 2}><GitMerge size={14} /> Preview Gabungan ({selectedBaselineIds.length})</button><button type="button" onClick={() => setSelectedBaselineIds([])} disabled={!selectedBaselineIds.length}>Bersihkan Pilihan</button></div></div>
        <div className="ops-notice"><strong>Cara pakai:</strong> Jika beberapa input pada tanggal yang sama adalah potongan laporan yang harus menjadi satu SO, centang semuanya lalu klik <strong>Preview Gabungan</strong>. Periksa duplikat, kemudian simpan; hasil baru otomatis menjadi SO aktif.</div>
        <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Pilih</th><th>Status</th><th>Versi</th><th>Tanggal SO</th><th>Isi</th><th>Pelapor</th><th>Disimpan</th><th>Aksi</th></tr></thead><tbody>{historyRows.map((row) => <tr key={row.id} className={row.is_balance_active ? "ops-active-row" : ""}>
          <td><input type="checkbox" checked={selectedBaselineIds.includes(row.id)} onChange={() => toggleBaselineSelection(row)} aria-label={`Pilih SO ${row.id}`} /></td>
          <td><div className="ops-status-stack">{row.is_balance_active ? <span className="ops-badge ops-badge-active">AKTIF UNTUK SALDO</span> : row.is_date_latest ? <span className="ops-badge ops-badge-latest">TERBARU TANGGAL INI</span> : <span className="ops-badge">VERSI LAMA</span>}<span className="ops-badge ops-badge-type">{row.result_type}</span></div></td>
          <td><strong>v{row.version_no}</strong><div className="ops-muted">#{row.id} · dari {row.version_count} versi</div></td>
          <td><strong>{row.stock_date}</strong><div className="ops-muted">{row.location_code}</div></td>
          <td><strong>{row.item_count} komponen</strong><div className="ops-muted">{row.warning_count} peringatan</div></td>
          <td>{row.reporter || "-"}</td>
          <td>{localDateTime(row.created_at)}<div className="ops-muted">WIB</div></td>
          <td><div className="ops-row-actions"><button type="button" onClick={() => openBaselineCorrection(row, false)} disabled={saving}>{row.is_balance_active ? <Eye size={14} /> : <Pencil size={14} />} {row.is_balance_active ? "Lihat & Koreksi" : "Buka & Jadikan Aktif"}</button></div></td>
        </tr>)}{!loading && history.length === 0 && <tr><td colSpan="8" className="ops-empty-cell">Belum ada SO tersimpan.</td></tr>}</tbody></table></div>
      </section>
    </div>
  );
}
