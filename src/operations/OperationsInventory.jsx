import React, { useEffect, useMemo, useState } from "react";
import { CheckCircle2, ClipboardPaste, RefreshCw, Search } from "lucide-react";
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
      const [data, opnameData] = await Promise.all([
        operationsApi.getInventoryBalances({ site: activeSite, search: searchValue, limit: 1000 }),
        operationsApi.getStockOpnames({ location: activeSite, limit: 12 }),
      ]);
      setItems(data?.items || []);
      setBalanceMeta(data || null);
      setHistory(opnameData?.items || []);
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
      if (!stockDate && data?.stockDate) setStockDate(data.stockDate);
    } catch (err) {
      setError(err.message || "Gagal membaca laporan SO");
    } finally {
      setSaving(false);
    }
  };

  const commitSo = async () => {
    if (!preview?.canCommit) return;
    const warning = Number(preview.reviewCount || 0) + Number(preview.ambiguousCount || 0);
    if (!window.confirm(
      `Simpan SO ${activeSite} tanggal ${preview.stockDate} dengan ${preview.itemCount} komponen?\n\n` +
      `${warning} komponen perlu perhatian dan ${preview.unmappedCount || 0} nama belum ada di Master Barang. Teks asli tetap disimpan; satuan yang tidak cocok tidak akan mengurangi PO.`
    )) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const data = await operationsApi.commitStockOpname({ location: activeSite, text: soText, stock_date: stockDate || null, reporter: reporter || null });
      setMessage(data.duplicate ? `SO ini sudah pernah disimpan (#${data.stockOpnameId}).` : `SO ${activeSite} tersimpan sebagai baseline #${data.stockOpnameId}.`);
      setPreview(null);
      setSoText("");
      await load("");
    } catch (err) {
      setError(err.message || "Gagal menyimpan laporan SO");
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
          <button type="button" onClick={commitSo} disabled={saving || !preview?.canCommit}><CheckCircle2 size={15} /> Konfirmasi & Simpan Baseline</button>
        </div>

        {preview && (
          <div className="ops-draft-group">
            <div className="ops-summary-strip">
              <span>Tanggal <strong>{preview.stockDate}</strong></span><span>Komponen <strong>{preview.itemCount}</strong></span><span>Perlu review <strong>{preview.reviewCount}</strong></span><span>Belum di Master <strong>{preview.unmappedCount}</strong></span>
            </div>
            {preview.warnings?.length > 0 && <div className="ops-notice">{preview.warnings.map((warning) => <div key={warning}>⚠ {warning}</div>)}</div>}
            <div className="ops-table-wrap">
              <table className="ops-table">
                <thead><tr><th>Area</th><th>Nama dari SO</th><th>Jenis kanonik</th><th>Qty</th><th>Unit</th><th>Klasifikasi</th><th>Status parse</th></tr></thead>
                <tbody>{preview.items?.map((item, idx) => <tr key={`${item.rawLine}-${idx}`}><td>{item.areaCode}</td><td><strong>{item.itemName}</strong></td><td>{item.canonicalItemName}</td><td>{qty(item.qty)}</td><td>{item.unit || "⚠ belum ada"}</td><td>{item.classificationStatus}<div className="ops-muted">{item.classificationMethod}</div></td><td>{item.parseStatus}</td></tr>)}</tbody>
              </table>
            </div>
          </div>
        )}
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
