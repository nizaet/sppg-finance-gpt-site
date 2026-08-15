import React, { useEffect, useMemo, useState } from "react";
import { CheckCircle2, ClipboardPaste, Plus, RefreshCw, Save, Search, XCircle } from "lucide-react";
import { operationsApi } from "./apiClient";

const qty = (value) => Number(value || 0).toLocaleString("id-ID", { maximumFractionDigits: 4 });

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
  const [masters, setMasters] = useState([]);
  const [masterForm, setMasterForm] = useState({ code: "", canonical_name: "", category_code: "", base_unit: "kg", aliases: "" });
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

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
        operationsApi.getStockOpnames({ location: activeSite, limit: 12 }),
        operationsApi.getInventoryItems(""),
      ]);
      setItems(data?.items || []);
      setBalanceMeta(data || null);
      setHistory(opnameData?.items || []);
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
      const data = await operationsApi.commitStockOpname({ location: activeSite, text: soText, stock_date: stockDate || null, reporter: reporter || null, reviewed_items: reviewedItems });
      setMessage(data.duplicate ? `SO ini sudah pernah disimpan (#${data.stockOpnameId}).` : `SO ${activeSite} tersimpan sebagai baseline #${data.stockOpnameId}: ${data.itemCount} item masuk, ${excluded} item dikeluarkan.`);
      setPreview(null);
      setReviewedItems([]);
      setSoText("");
      await load("");
    } catch (err) {
      setError(err.message || "Gagal menyimpan laporan SO");
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

  const negativeCount = useMemo(() => items.filter((x) => Number(x.projected_balance ?? x.balance ?? 0) < 0).length, [items]);
  const lowConfidenceCount = useMemo(() => items.filter((x) => x.confidence === "LOW").length, [items]);

  return (
    <div className="ops-domain-stack">
      <section className="ops-module">
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
        <textarea className="ops-chat-input" rows="9" value={soText} onChange={(e) => { setSoText(e.target.value); setPreview(null); }} placeholder="Paste laporan SO BARANG dari WhatsApp di sini…" />
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
        <div className="ops-module-header"><div><span className="ops-kicker">HISTORI BASELINE</span><h3>SO Terakhir</h3><p>Setiap SO disimpan sebagai bukti baru; laporan lama tidak ditimpa.</p></div></div>
        <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Tanggal</th><th>Lokasi</th><th>Pelapor</th><th>Komponen</th><th>Peringatan</th><th>Disimpan</th></tr></thead><tbody>{history.map((row) => <tr key={row.id}><td><strong>{row.stock_date}</strong></td><td>{row.location_code}</td><td>{row.reporter || "-"}</td><td>{row.item_count}</td><td>{row.warning_count}</td><td>{row.created_at}</td></tr>)}{!loading && history.length === 0 && <tr><td colSpan="6" className="ops-empty-cell">Belum ada SO tersimpan.</td></tr>}</tbody></table></div>
      </section>
    </div>
  );
}
