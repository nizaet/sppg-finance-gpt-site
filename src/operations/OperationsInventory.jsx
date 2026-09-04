import React, { useEffect, useMemo, useState } from "react";
import { CheckCircle2, ClipboardPaste, Eye, Pencil, Plus, RefreshCw, Save, Search, Trash2, XCircle } from "lucide-react";
import { operationsApi } from "./apiClient";

const qty = (value) => Number(value || 0).toLocaleString("id-ID", { maximumFractionDigits: 4 });
const signedQty = (value) => {
  const number = Number(value || 0);
  return `${number > 0 ? "+" : number < 0 ? "−" : ""}${qty(Math.abs(number))}`;
};
const localDateTime = (value) => value ? new Date(value).toLocaleString("id-ID", {
  timeZone: "Asia/Jakarta", day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
}) : "-";
const stockKey = (name, unit) => `${String(name || "").toLocaleLowerCase("id-ID").replace(/[^a-z0-9]+/g, " ").trim()}|${String(unit || "").toLocaleLowerCase("id-ID").trim()}`;
const todayMonth = () => new Date().toISOString().slice(0, 7);
const transferMonthBounds = (month) => {
  const first = new Date(`${month}-01T12:00:00`);
  const last = new Date(first.getFullYear(), first.getMonth() + 1, 0);
  return { fromDate: `${month}-01`, toDate: `${month}-${String(last.getDate()).padStart(2, "0")}`, first, last };
};
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));

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
  const [stockEdit, setStockEdit] = useState(null);
  const [transfers, setTransfers] = useState([]);
  const [transferMonth, setTransferMonth] = useState(todayMonth());
  const [selectedTransferDate, setSelectedTransferDate] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (fixedSite && site !== fixedSite) {
      setSite(fixedSite);
      setSearch("");
      setPreview(null);
      setStockEdit(null);
    }
  }, [fixedSite, site]);

  const activeSite = fixedSite || site;
  const currentBalanceByItem = useMemo(() => {
    const result = new Map();
    items.forEach((item) => {
      const actual = Number(item.actual_balance ?? 0);
      [item.item_name, ...(item.raw_item_names || [])].filter(Boolean).forEach((name) => {
        const key = stockKey(name, item.unit);
        if (!result.has(key)) result.set(key, actual);
      });
    });
    return result;
  }, [items]);

  const addStockComparison = (item) => {
    let before = null;
    for (const name of [item.canonical_item_name, item.raw_item_name].filter(Boolean)) {
      const found = currentBalanceByItem.get(stockKey(name, item.unit));
      if (found !== undefined) {
        before = found;
        break;
      }
    }
    return { ...item, actual_before_qty: before, verification_delta: before === null ? null : Number(item.qty || 0) - before };
  };

  const load = async (searchValue = search) => {
    setLoading(true);
    setError("");
    try {
      const [data, opnameData, masterData, transferData] = await Promise.all([
        operationsApi.getInventoryBalances({ site: activeSite, search: searchValue, limit: 1000 }),
        operationsApi.getStockOpnames({ location: activeSite, limit: 50 }),
        operationsApi.getInventoryItems(""),
        activeSite === "KOPERASI"
          ? operationsApi.getKoperasiTransfers(transferMonthBounds(transferMonth))
          : Promise.resolve({ items: [] }),
      ]);
      setItems(data?.items || []);
      setBalanceMeta(data || null);
      setHistory(opnameData?.items || []);
      setMasters(masterData?.items || []);
      setTransfers(transferData?.items || []);
    } catch (err) {
      setError(err.message || "Gagal mengambil stok gudang");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(""); }, [activeSite]);

  const loadTransfers = async (month = transferMonth) => {
    if (activeSite !== "KOPERASI") return;
    setLoading(true);
    setError("");
    try {
      const data = await operationsApi.getKoperasiTransfers(transferMonthBounds(month));
      setTransfers(data?.items || []);
      setSelectedTransferDate("");
    } catch (err) {
      setError(err.message || "Gagal mengambil riwayat kiriman Gudang Koperasi");
    } finally {
      setLoading(false);
    }
  };

  const exportTransfersExcel = () => {
    if (!transfers.length) return setError("Belum ada kiriman pada bulan ini untuk diekspor.");
    const rows = transfers.map((item) => `<tr><td>${escapeHtml(item.transfer_date)}</td><td>${escapeHtml(item.to_location)}</td><td>${escapeHtml(item.item_name)}</td><td style="mso-number-format:'0.0000'">${escapeHtml(item.qty)}</td><td>${escapeHtml(item.unit)}</td><td>${escapeHtml(item.po_code || "-")}</td><td>${escapeHtml(item.receipt_code || "-")}</td><td>${escapeHtml(item.reporter || "-")}</td></tr>`).join("");
    const html = `<!doctype html><html><head><meta charset="utf-8"></head><body><table border="1"><thead><tr><th>Tanggal kirim</th><th>Tujuan</th><th>Barang</th><th>Qty</th><th>Satuan</th><th>PO</th><th>Receipt</th><th>Penerima</th></tr></thead><tbody>${rows}</tbody></table></body></html>`;
    const blob = new Blob(["\ufeff", html], { type: "application/vnd.ms-excel;charset=utf-8" });
    const href = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = href;
    link.download = `Kiriman_Gudang_Koperasi_${transferMonth}.xls`;
    link.click();
    URL.revokeObjectURL(href);
  };

  const previewSo = async () => {
    if (!soText.trim()) return setError("Paste laporan SO WhatsApp terlebih dahulu.");
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const data = await operationsApi.previewStockOpname({ location: activeSite, text: soText, stock_date: stockDate || null, reporter: reporter || null });
      setPreview(data);
      setSourceExternalId("");
      setReviewedItems((data?.items || []).map((item, index) => addStockComparison({
        client_key: String(item.clientKey ?? index), include: item.selected !== false,
        area_code: item.areaCode || "UNSPECIFIED", raw_item_name: item.itemName || "",
        canonical_item_name: item.canonicalItemName || item.itemName || "", inventory_item_code: item.inventoryItemCode || "",
        qty: Number(item.qty || 0), unit: item.unit || "", raw_line: item.rawLine || item.itemName || "",
        classification_status: item.classificationStatus || "UNMAPPED", classification_method: item.classificationMethod || "",
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
    const replacing = sourceExternalId.startsWith("consolidated:") || sourceExternalId.startsWith("correction:");
    if (!window.confirm(
      `Jadikan SO ${activeSite} tanggal ${preview.stockDate} sebagai stok aktual dengan ${selected.length} item?\n\n` +
      "Angka SO mengganti hitungan stok fisik sebelumnya — bukan ditambahkan dua kali. Penerimaan barang sesudah SO menambah stok; pemakaian aktual mengurangi stok.\n\n" +
      `${excluded} komponen dikeluarkan. ${replacing ? "SO lama yang diperbaiki akan otomatis menjadi arsip." : ""}`
    )) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const data = await operationsApi.commitStockOpname({ location: activeSite, text: soText, stock_date: stockDate || null, source_external_id: sourceExternalId || null, reporter: reporter || null, reviewed_items: reviewedItems });
      const archived = Number(data?.supersededStockOpnameIds?.length || 0);
      if (data.duplicate) setMessage(`SO ini sudah menjadi stok aktif (#${data.stockOpnameId}); tidak disimpan dua kali.`);
      else if (data.restored) setMessage(`SO #${data.stockOpnameId} dipulihkan dan kembali dipakai sebagai stok aktual.`);
      else setMessage(`Stok aktual ${activeSite} sekarang memakai SO #${data.stockOpnameId}: ${data.itemCount} item. ${archived ? `${archived} SO pecahan lama otomatis diarsipkan.` : ""}`);
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
    client_key: `${detail.stockOpname.id}:${item.id}`, include: true, area_code: item.area_code || "UNSPECIFIED",
    raw_item_name: item.raw_item_name || item.canonical_item_name || "", canonical_item_name: item.canonical_item_name || item.raw_item_name || "",
    inventory_item_code: item.inventory_item_code || "", qty: Number(item.qty || 0), unit: item.unit || "",
    raw_line: item.raw_line || item.raw_item_name || "", classification_status: item.classification_status || "USER_REVIEWED",
    classification_method: item.classification_method || "KOREKSI_OPERATOR",
  }));

  const combineRepeatedItems = (sourceItems) => {
    const combined = new Map();
    sourceItems.forEach((source) => {
      const key = `${stockKey(source.canonical_item_name || source.raw_item_name, source.unit)}|${String(source.area_code || "")}`;
      const existing = combined.get(key);
      if (!existing) return combined.set(key, { ...source });
      combined.set(key, {
        ...existing, qty: Number(existing.qty || 0) + Number(source.qty || 0),
        raw_line: `${existing.raw_line} + ${source.raw_line}`,
        classification_status: existing.classification_status === "MATCHED" ? existing.classification_status : source.classification_status,
        inventory_item_code: existing.inventory_item_code || source.inventory_item_code,
      });
    });
    return [...combined.values()];
  };

  const prepareStockCorrection = async (row, mergeSameDate = false, explicitRows = null) => {
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const targets = explicitRows || (mergeSameDate ? history.filter((item) => String(item.stock_date) === String(row.stock_date)) : [row]);
      const details = await Promise.all(targets.map((item) => operationsApi.getStockOpname(item.id)));
      const rawItems = details.flatMap(detailItems);
      if (!rawItems.length) throw new Error("SO tidak memiliki item yang dapat dikoreksi.");
      const correctedItems = (mergeSameDate ? combineRepeatedItems(rawItems) : rawItems).map(addStockComparison);
      const ids = details.map((detail) => detail.stockOpname.id);
      setSoText(details.map((detail) => detail.stockOpname.raw_text || "").filter(Boolean).join("\n\n--- LAPORAN SO DIGABUNG ---\n\n"));
      setStockDate(String(row.stock_date));
      setReporter(details.map((detail) => detail.stockOpname.reporter).filter(Boolean)[0] || "");
      setReviewedItems(correctedItems);
      setPreview({ canCommit: true, stockDate: String(row.stock_date), items: correctedItems, warnings: [] });
      setSourceExternalId(mergeSameDate ? `consolidated:${row.stock_date}:${ids.join("-")}` : `correction:${row.id}`);
      setMessage(mergeSameDate
        ? `${details.length} potongan SO tanggal ${row.stock_date} disatukan menjadi ${correctedItems.length} barang. Baris dengan nama dan satuan sama sudah dijumlahkan; cek sekali, lalu simpan sebagai stok aktual.`
        : `SO ${row.stock_date} dibuka untuk koreksi. Saat disimpan, angka koreksi ini menjadi stok aktual dan SO lama masuk arsip.`);
      window.setTimeout(() => document.getElementById("inventory-so-entry")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
    } catch (err) {
      setError(err.message || "Gagal membuka SO untuk koreksi");
    } finally {
      setSaving(false);
    }
  };

  const repairFragmentedStock = () => {
    const sameDateRows = history.filter((item) => String(item.stock_date) === String(balanceMeta?.latestStockOpnameDate));
    if (sameDateRows.length < 2) return setError("Tidak ada potongan SO yang perlu disatukan.");
    prepareStockCorrection(sameDateRows[0], true, sameDateRows);
  };

  const deleteStockOpname = async (row) => {
    const isCurrent = Number(row.id) === Number(balanceMeta?.latestStockOpnameId);
    if (!window.confirm(
      `Hapus SO ${row.stock_date} (${row.item_count} item) dari stok aktif?\n\n` +
      `${isCurrent ? "Ini adalah SO yang sedang dipakai untuk PO. Setelah dihapus, sistem akan memakai SO aktif sebelumnya; jika tidak ada, masukkan SO baru." : "SO ini tidak akan lagi ikut perhitungan stok dan PO."}\n\n` +
      "Bukti chat dan riwayat audit tetap disimpan."
    )) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      await operationsApi.deleteStockOpname(row.id, "Dihapus operator dari stok aktif");
      setMessage(`SO ${row.stock_date} #${row.id} sudah dihapus dari perhitungan stok dan PO. Bukti audit tetap aman.`);
      await load("");
    } catch (err) {
      setError(err.message || "Gagal menghapus SO dari stok aktif");
    } finally {
      setSaving(false);
    }
  };

  const openManualStockEdit = (item) => {
    const current = Number(item.actual_balance ?? item.balance ?? 0);
    setStockEdit({
      item_name: item.item_name || "",
      inventory_item_code: item.inventory_item_code || "",
      unit: item.unit || "",
      current_balance: current,
      target_balance: current,
      reason: "Koreksi manual stok gudang",
    });
    setMessage(`Edit manual stok dibuka untuk ${item.item_name}.`);
    window.setTimeout(() => document.getElementById("inventory-manual-edit")?.scrollIntoView({ behavior: "smooth", block: "center" }), 0);
  };

  const updateStockEdit = (patch) => setStockEdit((current) => current ? { ...current, ...patch } : current);

  const commitManualStockEdit = async () => {
    if (!stockEdit?.item_name?.trim()) return setError("Nama barang wajib diisi untuk koreksi manual.");
    const current = Number(stockEdit.current_balance || 0);
    const target = Number(stockEdit.target_balance);
    if (!Number.isFinite(target) || target < 0) return setError("Stok baru harus berupa angka 0 atau lebih.");
    const delta = target - current;
    if (Math.abs(delta) <= 0.00005) return setError("Stok baru sama dengan stok tercatat. Tidak ada koreksi yang perlu disimpan.");
    if (!window.confirm(
      `Set stok aktual ${stockEdit.item_name} dari ${qty(current)} ${stockEdit.unit || ""} menjadi ${qty(target)} ${stockEdit.unit || ""}?\n\n` +
      `Sistem akan mencatat movement koreksi ${signedQty(delta)} ${stockEdit.unit || ""}. Histori SO dan penerimaan tidak dihapus.`
    )) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const result = await operationsApi.manualStockAdjustment({
        location: activeSite,
        item_name: stockEdit.item_name.trim(),
        inventory_item_code: stockEdit.inventory_item_code || null,
        unit: stockEdit.unit || null,
        current_balance: current,
        target_balance: target,
        reason: stockEdit.reason || "Koreksi manual stok gudang",
        actor: "operator",
      }, true);
      setMessage(`Stok ${result.itemName} diset ke ${qty(result.balanceAfter ?? target)} ${result.unit || ""}. Movement koreksi #${result.movementId}; delta ${signedQty(result.adjustmentDelta)} ${result.unit || ""}.`);
      setStockEdit(null);
      await load(search);
    } catch (err) {
      setError(err.message || "Gagal menyimpan koreksi manual stok");
    } finally {
      setSaving(false);
    }
  };

  const updateReviewed = (clientKey, patch) => {
    setReviewedItems((current) => current.map((item) => item.client_key === clientKey ? addStockComparison({ ...item, ...patch }) : item));
  };

  const selectMaster = (clientKey, code) => {
    const master = masters.find((item) => item.code === code);
    if (!master) return updateReviewed(clientKey, { inventory_item_code: "", classification_status: "USER_REVIEWED" });
    updateReviewed(clientKey, {
      inventory_item_code: master.code, canonical_item_name: master.canonical_name, unit: master.base_unit || "",
      classification_status: "MATCHED", classification_method: "USER_SELECTED_MASTER",
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
        code: masterForm.code.trim() || null, canonical_name: masterForm.canonical_name.trim(),
        category_code: masterForm.category_code.trim() || null, base_unit: masterForm.base_unit.trim() || null,
        aliases: masterForm.aliases.split(",").map((value) => value.trim()).filter(Boolean),
      }, true);
      const masterData = await operationsApi.getInventoryItems("");
      setMasters(masterData?.items || []);
      setMasterForm({ code: "", canonical_name: "", category_code: "", base_unit: "kg", aliases: "" });
      setMessage(`Master Barang ${result.canonicalName} (${result.code}) tersimpan. Laporan berikutnya dapat dikenali otomatis.`);
    } catch (err) {
      setError(err.message || "Gagal menyimpan Master Barang");
    } finally {
      setSaving(false);
    }
  };

  const editMaster = (master) => {
    setMasterForm({
      code: master.code || "", canonical_name: master.canonical_name || "", category_code: master.category_code || "",
      base_unit: master.base_unit || "", aliases: (master.aliases || []).join(", "),
    });
    setMessage(`Master ${master.canonical_name} dibuka untuk diedit.`);
  };

  const negativeCount = useMemo(() => items.filter((item) => Number(item.projected_balance ?? item.balance ?? 0) < 0).length, [items]);
  const lowConfidenceCount = useMemo(() => items.filter((item) => item.confidence === "LOW").length, [items]);
  const historyRows = useMemo(() => history.map((row) => ({ ...row, is_balance_active: Number(row.id) === Number(balanceMeta?.latestStockOpnameId) })), [history, balanceMeta?.latestStockOpnameId]);
  const transfersByDate = useMemo(() => transfers.reduce((all, item) => {
    const key = String(item.transfer_date || "");
    if (!key) return all;
    (all[key] ||= []).push(item);
    return all;
  }, {}), [transfers]);
  const calendarDays = useMemo(() => {
    const { first, last } = transferMonthBounds(transferMonth);
    const mondayOffset = (first.getDay() + 6) % 7;
    return Array.from({ length: mondayOffset + last.getDate() }, (_, index) => index < mondayOffset ? null : index - mondayOffset + 1);
  }, [transferMonth]);
  const selectedTransfers = selectedTransferDate ? (transfersByDate[selectedTransferDate] || []) : [];

  return (
    <div className="ops-domain-stack">
      <section className="ops-module" id="inventory-so-entry">
        <div className="ops-module-header">
          <div>
            <span className="ops-kicker">SO FISIK → STOK AKTUAL GUDANG</span>
            <h3>Masukkan Laporan Stok Gudang</h3>
            <p>SO adalah hitungan fisik terbaru. Setelah disimpan, angka ini menjadi stok aktual yang dipakai untuk PO — bukan ditambahkan ke SO lama.</p>
          </div>
          <div className="ops-inline-controls">
            <select value={activeSite} disabled={Boolean(fixedSite)} onChange={(e) => { setSite(e.target.value); setSearch(""); setPreview(null); setStockEdit(null); }}><option value="MAJA">Gudang Dapur Maja</option><option value="CEMPLANG">Gudang Dapur Cemplang</option><option value="KOPERASI">Gudang Koperasi</option></select>
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
          <button type="button" onClick={previewSo} disabled={saving || !soText.trim()}><ClipboardPaste size={15} /> {saving ? "Membaca…" : "Preview & Verifikasi SO"}</button>
          <button type="button" onClick={commitSo} disabled={saving || !preview?.canCommit || !reviewedItems.some((item) => item.include)}><CheckCircle2 size={15} /> Jadikan Stok Aktual ({reviewedItems.filter((item) => item.include).length})</button>
        </div>

        {preview && <div className="ops-draft-group">
          <div className="ops-summary-strip"><span>Tanggal <strong>{preview.stockDate}</strong></span><span>Baris SO <strong>{reviewedItems.length}</strong></span><span>Masuk stok <strong>{reviewedItems.filter((item) => item.include).length}</strong></span><span>Dikeluarkan <strong>{reviewedItems.filter((item) => !item.include).length}</strong></span></div>
          <div className="ops-notice"><strong>Yang terjadi saat disimpan:</strong> jumlah pada SO menjadi hitungan stok fisik terbaru. Kolom selisih hanya menunjukkan perbedaan dari stok yang tercatat sebelumnya; sistem tidak menambahkan selisih dua kali.</div>
          {preview.warnings?.length > 0 && <div className="ops-notice">{preview.warnings.map((warning) => <div key={warning}>⚠ {warning}</div>)}</div>}
          <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Simpan?</th><th>Area</th><th>Nama dari SO</th><th>Master Barang</th><th>Jenis kanonik — EDIT</th><th>Qty SO — EDIT</th><th>Unit — EDIT</th><th>Stok tercatat sebelum SO</th><th>Selisih verifikasi</th><th>Status</th></tr></thead><tbody>{reviewedItems.map((item) => <tr key={item.client_key}>
            <td><button type="button" onClick={() => updateReviewed(item.client_key, { include: !item.include })}>{item.include ? <XCircle size={14} /> : <Plus size={14} />} {item.include ? "Keluarkan" : "Masukkan"}</button></td>
            <td><input value={item.area_code} disabled={!item.include} onChange={(e) => updateReviewed(item.client_key, { area_code: e.target.value })} /></td>
            <td><strong>{item.raw_item_name}</strong><div className="ops-muted">{item.raw_line}</div></td>
            <td><select value={item.inventory_item_code} disabled={!item.include} onChange={(e) => selectMaster(item.client_key, e.target.value)}><option value="">Tanpa Master / nama manual</option>{masters.map((master) => <option key={master.code} value={master.code}>{master.canonical_name} · {master.base_unit || "-"}</option>)}</select></td>
            <td><input value={item.canonical_item_name} disabled={!item.include || Boolean(item.inventory_item_code)} onChange={(e) => updateReviewed(item.client_key, { canonical_item_name: e.target.value, classification_status: "USER_REVIEWED" })} /></td>
            <td><input className="ops-qty-input" type="number" min="0" step="0.0001" value={item.qty} disabled={!item.include} onChange={(e) => updateReviewed(item.client_key, { qty: Number(e.target.value) })} /></td>
            <td><input value={item.unit} disabled={!item.include} onChange={(e) => updateReviewed(item.client_key, { unit: e.target.value })} placeholder="kg / pcs / unit / dus" /></td>
            <td>{item.actual_before_qty === null ? <span className="ops-muted">belum tercatat</span> : `${qty(item.actual_before_qty)} ${item.unit || ""}`}</td>
            <td>{item.verification_delta === null ? "-" : `${signedQty(item.verification_delta)} ${item.unit || ""}`}</td>
            <td>{item.include ? item.classification_status : "DIKELUARKAN"}<div className="ops-muted">{item.classification_method}</div></td>
          </tr>)}</tbody></table></div>
        </div>}
      </section>

      {activeSite === "KOPERASI" && <section className="ops-module">
        <div className="ops-module-header">
          <div>
            <span className="ops-kicker">GUDANG KOPERASI → DAPUR</span>
            <h3>Daftar Kiriman Barang</h3>
            <p>Setiap penerimaan PO Koperasi ke MAJA atau CEMPLANG tercatat sebagai transfer: stok Gudang Koperasi berkurang dan stok dapur tujuan bertambah. Ini bukan pembelian atau beban baru.</p>
          </div>
          <div className="ops-inline-controls">
            <input type="month" value={transferMonth} onChange={(event) => setTransferMonth(event.target.value)} />
            <button type="button" onClick={() => loadTransfers()} disabled={loading}><RefreshCw size={15} /> Tampilkan</button>
            <button type="button" onClick={exportTransfersExcel} disabled={!transfers.length}>Ekspor Excel</button>
          </div>
        </div>
        <div className="ops-summary-strip"><span>Bulan <strong>{new Date(`${transferMonth}-01T12:00:00`).toLocaleDateString("id-ID", { month: "long", year: "numeric" })}</strong></span><span>Baris kiriman <strong>{transfers.length}</strong></span><span>Ke MAJA <strong>{transfers.filter((item) => item.to_location === "MAJA").length}</strong></span><span>Ke CEMPLANG <strong>{transfers.filter((item) => item.to_location === "CEMPLANG").length}</strong></span></div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(7, minmax(0, 1fr))", gap: 6, marginTop: 12 }}>
          {["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"].map((label) => <div key={label} className="ops-muted" style={{ textAlign: "center", fontWeight: 700 }}>{label}</div>)}
          {calendarDays.map((day, index) => {
            if (day === null) return <div key={`empty-${index}`} />;
            const date = `${transferMonth}-${String(day).padStart(2, "0")}`;
            const dayTransfers = transfersByDate[date] || [];
            const destinations = Array.from(new Set(dayTransfers.map((item) => item.to_location))).join(" · ");
            return <button key={date} type="button" onClick={() => dayTransfers.length && setSelectedTransferDate(date)} disabled={!dayTransfers.length} style={{ minHeight: 82, textAlign: "left", border: "1px solid #dbe4f0", borderRadius: 9, padding: 8, background: dayTransfers.length ? "#ecfdf5" : "#fff", color: "#1e293b", cursor: dayTransfers.length ? "pointer" : "default", opacity: dayTransfers.length ? 1 : .7 }}>
              <strong>{day}</strong>{dayTransfers.length > 0 && <><div style={{ fontSize: 12, color: "#047857", marginTop: 6 }}>{dayTransfers.length} baris kiriman</div><div className="ops-muted" style={{ fontSize: 11 }}>{destinations}</div></>}
            </button>;
          })}
        </div>
        {!transfers.length && !loading && <div className="ops-notice" style={{ marginTop: 12 }}>Belum ada transfer Koperasi ke dapur pada bulan ini.</div>}
        {selectedTransferDate && <div role="presentation" className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setSelectedTransferDate("")}>
          <div role="dialog" aria-modal="true" className="modal wide">
            <div className="modal-head"><h3>Kiriman Gudang Koperasi - {selectedTransferDate}</h3><button type="button" onClick={() => setSelectedTransferDate("")}><XCircle size={18} /></button></div>
            <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Tujuan</th><th>Barang</th><th>Qty</th><th>Unit</th><th>PO</th><th>Receipt</th><th>Penerima</th></tr></thead><tbody>{selectedTransfers.map((item) => <tr key={item.movement_id}><td><strong>{item.to_location}</strong></td><td>{item.item_name}</td><td>{qty(item.qty)}</td><td>{item.unit || "-"}</td><td>{item.po_code || "-"}</td><td>{item.receipt_code || "-"}</td><td>{item.reporter || "-"}</td></tr>)}</tbody></table></div>
          </div>
        </div>}
      </section>}

      <section className="ops-module">
        <div className="ops-module-header"><div><span className="ops-kicker">MASTER BARANG & ALIAS</span><h3>Tambah atau Perbarui Klasifikasi</h3><p>Contoh: buat “Mi telur ayam” sebagai jenis tersendiri lalu masukkan alias “mi telur”, “mie telur ayam”. Laporan berikutnya akan dikenali lebih cepat.</p></div></div>
        <div className="ops-form-grid">
          <label>Kode (opsional)<input value={masterForm.code} onChange={(e) => setMasterForm((current) => ({ ...current, code: e.target.value.toUpperCase() }))} placeholder="MI_TELUR_AYAM" /></label>
          <label>Nama kanonik<input value={masterForm.canonical_name} onChange={(e) => setMasterForm((current) => ({ ...current, canonical_name: e.target.value }))} placeholder="Mi telur ayam" /></label>
          <label>Kategori<input value={masterForm.category_code} onChange={(e) => setMasterForm((current) => ({ ...current, category_code: e.target.value.toUpperCase() }))} placeholder="BAHAN_KERING" /></label>
          <label>Satuan dasar<input value={masterForm.base_unit} onChange={(e) => setMasterForm((current) => ({ ...current, base_unit: e.target.value }))} placeholder="dus / pcs / kg" /></label>
          <label>Alias dipisah koma<input value={masterForm.aliases} onChange={(e) => setMasterForm((current) => ({ ...current, aliases: e.target.value }))} placeholder="mi telur, mie telur ayam" /></label>
          <label>Aksi<div className="ops-row-actions"><button type="button" onClick={saveMaster} disabled={saving || !masterForm.canonical_name.trim()}><Save size={14} /> Simpan Master</button></div></label>
        </div>
        <div className="ops-summary-strip"><span>Master aktif <strong>{masters.length}</strong></span></div>
        <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Kode</th><th>Nama Master</th><th>Kategori</th><th>Satuan</th><th>Alias</th><th>Aksi</th></tr></thead><tbody>{masters.map((master) => <tr key={master.code}><td>{master.code}</td><td><strong>{master.canonical_name}</strong></td><td>{master.category_code || "-"}</td><td>{master.base_unit || "-"}</td><td>{(master.aliases || []).join(" · ") || "-"}</td><td><button type="button" onClick={() => editMaster(master)}><Pencil size={14} /> Edit Master</button></td></tr>)}</tbody></table></div>
      </section>

      <section className="ops-module">
        <div className="ops-module-header">
          <div><span className="ops-kicker">STOK AKTUAL YANG DIPAKAI UNTUK PO</span><h3>Stok Gudang Saat Ini</h3><p>Satu angka yang perlu dilihat adalah <strong>Stok aktual sekarang</strong>. “Sisa untuk PO” hanya simulasi setelah kebutuhan planning berikutnya dikurangi.</p></div>
          <div className="ops-inline-controls"><input value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load(search)} placeholder="Cari barang" /><button type="button" onClick={() => load(search)} disabled={loading}><Search size={15} /> Cari</button><button type="button" onClick={() => { setSearch(""); load(""); }} disabled={loading}><RefreshCw size={15} /> Semua</button></div>
        </div>
        <div className="ops-stock-card"><div><span className="ops-kicker">STOK FISIK BERLAKU</span><strong>{balanceMeta?.latestStockOpnameId ? `SO #${balanceMeta.latestStockOpnameId} · ${balanceMeta.latestStockOpnameDate}` : "Belum ada SO aktif"}</strong><p>{balanceMeta?.latestStockOpnameId ? "Ini sumber hitungan stok aktual di bawah dan dipakai untuk rekomendasi PO." : "Masukkan satu laporan SO untuk memulai stok aktual gudang."}</p></div><div className="ops-summary-strip"><span>Item <strong>{items.length}</strong></span><span>Proyeksi s.d. <strong>{balanceMeta?.projectionThrough || "-"}</strong></span><span>Butuh PO <strong>{negativeCount}</strong></span><span>Perlu cek <strong>{lowConfidenceCount}</strong></span></div></div>
        {balanceMeta?.baselineNeedsConsolidation && <div className="ops-error"><strong>Stok aktual belum lengkap.</strong> Ada {balanceMeta.sameDateStockOpnameCount} potongan laporan SO tanggal {balanceMeta.latestStockOpnameDate}; saat ini sistem hanya membaca potongan terakhir. Klik sekali untuk menyatukan semuanya menjadi satu stok aktual.<div className="ops-row-actions"><button type="button" onClick={repairFragmentedStock} disabled={saving}><Plus size={14} /> Perbaiki Stok Aktual {balanceMeta.latestStockOpnameDate}</button></div></div>}
        <div className="ops-notice"><strong>Alur otomatis:</strong> SO baru mengganti hitungan fisik. Penerimaan sesudah SO menambah stok, pemakaian aktual mengurangi stok, lalu planning hanya mengurangi kolom “Sisa untuk PO”. Koreksi manual di bawah dicatat sebagai movement audit, bukan menghapus SO.</div>
        {stockEdit && <div className="ops-parse-result" id="inventory-manual-edit">
          <div><Pencil size={16} /><strong>Edit Manual Stok Gudang</strong></div>
          <div className="ops-form-grid">
            <label>Barang<input value={stockEdit.item_name} onChange={(e) => updateStockEdit({ item_name: e.target.value })} /></label>
            <label>Stok tercatat sekarang<input value={qty(stockEdit.current_balance)} disabled /></label>
            <label>Stok baru<input className="ops-qty-input" type="number" min="0" step="0.0001" value={stockEdit.target_balance} onChange={(e) => updateStockEdit({ target_balance: Number(e.target.value) })} /></label>
            <label>Unit<input value={stockEdit.unit} onChange={(e) => updateStockEdit({ unit: e.target.value })} placeholder="kg / pcs / ikat" /></label>
            <label>Alasan<input value={stockEdit.reason} onChange={(e) => updateStockEdit({ reason: e.target.value })} placeholder="contoh: koreksi hitung fisik" /></label>
            <label>Aksi<div className="ops-row-actions"><button type="button" onClick={commitManualStockEdit} disabled={saving}><Save size={14} /> Simpan Koreksi</button><button type="button" onClick={() => setStockEdit(null)} disabled={saving}><XCircle size={14} /> Batal</button></div></label>
          </div>
          <div className="ops-muted">Yang disimpan adalah selisih dari stok tercatat ke stok baru. Riwayat SO, PO, dan penerimaan tetap ada untuk audit.</div>
        </div>}
        <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Barang</th><th>SO fisik terakhir</th><th>Barang masuk / keluar sesudah SO</th><th>Pemakaian aktual</th><th>Stok aktual sekarang</th><th>Dikurangi planning</th><th>Sisa untuk PO</th><th>Unit</th><th>Status data</th><th>Aksi</th></tr></thead><tbody>
          {items.map((item, index) => <tr key={`${item.item_name}-${item.unit}-${index}`}><td><strong>{item.item_name}</strong><div className="ops-muted">{item.raw_item_names?.join(" · ")}</div></td><td>{qty(item.so_qty)}</td><td>{signedQty(item.movement_delta)}</td><td>−{qty(item.actual_usage_depletion)}</td><td><strong>{qty(item.actual_balance)}</strong></td><td>−{qty(item.planned_depletion)}</td><td><strong>{qty(item.projected_balance)}</strong></td><td>{item.unit || "-"}</td><td>{item.confidence === "LOW" ? "Perlu cek" : "Siap"}<div className="ops-muted">SO {item.stock_as_of || "-"}</div></td><td><button type="button" onClick={() => openManualStockEdit(item)} disabled={saving}><Pencil size={14} /> Edit Stok</button></td></tr>)}
          {!loading && items.length === 0 && <tr><td colSpan="10" className="ops-empty-cell">Belum ada SO aktif atau pergerakan stok untuk lokasi/filter ini.</td></tr>}
        </tbody></table></div>
      </section>

      <section className="ops-module">
        <details className="ops-stock-history"><summary>Riwayat SO & Hapus Data Salah <span>{history.length} SO aktif tersimpan</span></summary><div className="ops-stock-history-content">
          <p className="ops-muted">Riwayat ini tidak perlu dipakai sehari-hari. Gunakan hanya bila ingin memperbaiki atau menghapus input SO yang salah. Tombol Hapus mengeluarkan SO dari stok dan PO, tetapi bukti chat tetap ada untuk audit.</p>
          <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Status</th><th>Tanggal SO</th><th>Jumlah barang</th><th>Pelapor</th><th>Disimpan</th><th>Aksi</th></tr></thead><tbody>{historyRows.map((row) => <tr key={row.id} className={row.is_balance_active ? "ops-active-row" : ""}>
            <td>{row.is_balance_active ? <span className="ops-badge ops-badge-active">STOK AKTUAL</span> : <span className="ops-badge">RIWAYAT</span>}</td><td><strong>{row.stock_date}</strong><div className="ops-muted">#{row.id} · {row.location_code}</div></td><td><strong>{row.item_count} item</strong><div className="ops-muted">{row.warning_count} peringatan</div></td><td>{row.reporter || "-"}</td><td>{localDateTime(row.created_at)}<div className="ops-muted">WIB</div></td>
            <td><div className="ops-row-actions"><button type="button" onClick={() => prepareStockCorrection(row)} disabled={saving}>{row.is_balance_active ? <Eye size={14} /> : <Pencil size={14} />} Koreksi</button><button type="button" className="ops-danger-button" onClick={() => deleteStockOpname(row)} disabled={saving}><Trash2 size={14} /> Hapus</button></div></td>
          </tr>)}{!loading && history.length === 0 && <tr><td colSpan="6" className="ops-empty-cell">Belum ada SO tersimpan.</td></tr>}</tbody></table></div>
        </div></details>
      </section>
    </div>
  );
}
