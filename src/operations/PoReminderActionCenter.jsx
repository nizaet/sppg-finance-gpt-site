import React, { useEffect, useMemo, useState } from "react";
import { CheckCircle2, RefreshCw, Save, ShoppingCart } from "lucide-react";
import { operationsApi } from "./apiClient.js";
import { confirmPoShortageStock } from "./poShortageStockClient.js";

const today = () => new Date().toISOString().slice(0, 10);
const qty = (value) => Number(value || 0).toLocaleString("id-ID", { maximumFractionDigits: 4 });

function normalize(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function normalizeUnit(value) {
  const unit = normalize(value);
  const aliases = { kilogram: "kg", kilograms: "kg", gram: "gr", liter: "liter", litre: "liter", pieces: "pcs", piece: "pcs", pc: "pcs" };
  return aliases[unit] || unit;
}

function shiftDate(value, days) {
  if (!value) return "";
  const result = new Date(`${value}T12:00:00`);
  result.setDate(result.getDate() + days);
  return result.toISOString().slice(0, 10);
}

function remainingQty(item) {
  return Number((item.requirement_details || []).reduce(
    (sum, detail) => sum + Math.max(0, Number(detail.remaining_po_qty || 0)),
    0,
  ).toFixed(4));
}

function itemNames(item) {
  const names = item.missing_item_names?.length ? item.missing_item_names : item.item_names || [];
  return Array.from(new Set(names.filter(Boolean)));
}

function buildShortagePo(item, site) {
  const details = (item.requirement_details || []).filter((detail) => Number(detail.remaining_po_qty || 0) > 0);
  const coverageMap = new Map();
  details.forEach((detail) => {
    const distribution = String(detail.distribution_date || item.distribution_date || "");
    if (!distribution) return;
    const names = (detail.item_names || []).filter(Boolean);
    const line = {
      item_code: null,
      item_name: names[0] || detail.stock_type_code || "Item kekurangan",
      planning_snapshot_item_id: null,
      planned_qty: Number(detail.recommended_po_qty || 0),
      po_qty: Number(detail.remaining_po_qty || 0),
      unit: detail.unit || null,
      planning_price: null,
      po_price: null,
      aliases: names.slice(1),
      notes: `PO dari reminder ${item.reminder_key || "-"}`,
    };
    const row = coverageMap.get(distribution) || {
      distribution_date: distribution,
      cooking_date: String((detail.cooking_dates || [])[0] || item.cooking_date || shiftDate(distribution, -1)),
      source_planning_snapshot_id: null,
      items: [],
    };
    row.items.push(line);
    coverageMap.set(distribution, row);
  });

  const coverage = Array.from(coverageMap.values()).sort((a, b) => a.distribution_date.localeCompare(b.distribution_date));
  if (!coverage.length) return null;
  const aggregate = new Map();
  coverage.forEach((row) => row.items.forEach((line) => {
    const key = `${normalize(line.item_name)}|${normalizeUnit(line.unit)}`;
    const current = aggregate.get(key);
    if (!current) aggregate.set(key, { ...line });
    else current.po_qty = Number((Number(current.po_qty || 0) + Number(line.po_qty || 0)).toFixed(4));
  }));
  const suffix = String(item.reminder_key || "REMINDER").slice(-8).toUpperCase();
  const vendor = String(item.vendor_code || "").toUpperCase();
  return {
    po_code: `PO-${site}-${coverage[0].distribution_date.replaceAll("-", "")}-${vendor}-KURANG-${suffix}`,
    site,
    vendor_code: vendor,
    distribution_date: coverage[0].distribution_date,
    cooking_at: `${coverage[0].cooking_date}T03:00:00+07:00`,
    source_planning_snapshot_id: null,
    status: "DRAFT",
    items: Array.from(aggregate.values()),
    coverage,
  };
}

export default function PoReminderActionCenter() {
  const [site, setSite] = useState("MAJA");
  const [reminders, setReminders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busyKey, setBusyKey] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await operationsApi.getPoReminders({ site, date: today(), horizonDays: 21 });
      setReminders(data?.items || []);
    } catch (err) {
      setError(err.message || "Gagal mengambil tindakan reminder PO");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [site]);

  const ordering = useMemo(() => reminders.filter((item) => {
    const status = String(item.reminder_status || "").toUpperCase();
    return ["OVERDUE", "DUE_TODAY"].includes(status) && !item.po_already_done && remainingQty(item) > 0;
  }), [reminders]);

  const review = useMemo(() => reminders.filter(
    (item) => String(item.reminder_status || "").toUpperCase() === "SHORTAGE_REVIEW",
  ), [reminders]);

  const createPo = async (item) => {
    const payload = buildShortagePo(item, site);
    if (!payload) {
      setError("Rincian sisa kebutuhan tidak cukup untuk membuat PO.");
      return;
    }
    const names = itemNames(item).join(", ") || "item kekurangan";
    if (!window.confirm(
      `Buat DRAFT PO ${item.vendor_name || item.vendor_code} dari kebutuhan yang benar-benar belum tercakup?\n\n` +
      `${names}\nTotal sisa: ${qty(remainingQty(item))} (unit mengikuti masing-masing item).`,
    )) return;
    setBusyKey(item.reminder_key || payload.po_code);
    setError("");
    setMessage("");
    try {
      const result = await operationsApi.createSplitPurchaseOrder(payload);
      setMessage(`${result.poCode} dibuat dari sisa kebutuhan. Silakan cek/edit lalu finalkan.`);
      await load();
    } catch (err) {
      setError(err.message || "Gagal membuat PO dari reminder");
    } finally {
      setBusyKey("");
    }
  };

  const markChecked = async (item) => {
    if (!item.reminder_key) return;
    if (!window.confirm(
      "Tandai sisa kebutuhan ini SUDAH DICEK / BIARKAN?\n\n" +
      "Gunakan ini jika qty PO memang sengaja Anda kurangi karena kondisi dapur. Tidak ada PO baru dan stok tidak diubah.",
    )) return;
    const note = window.prompt("Catatan singkat (opsional):", "Qty PO sengaja disesuaikan kondisi dapur") ?? "";
    setBusyKey(item.reminder_key);
    setError("");
    setMessage("");
    try {
      await operationsApi.overridePoReminder({
        site,
        reminder_key: item.reminder_key,
        vendor_code: item.vendor_code,
        resolution: "SUFFICIENT",
        note: `[CHECKED/BIARKAN] ${note}`.trim(),
        metadata: {
          review_mode: "CHECKED_ACCEPTED_SHORTAGE",
          purchase_order_id: item.purchase_order_id || null,
          po_code: item.po_code || null,
          shortage_item_names: item.shortage_item_names || itemNames(item),
          shortage_qty_total: item.shortage_qty_total ?? remainingQty(item),
        },
      });
      setMessage("Sisa kebutuhan ditandai sudah dicek / dibiarkan dan tidak lagi masuk pekerjaan PO.");
      await load();
    } catch (err) {
      setError(err.message || "Gagal menyimpan konfirmasi reminder");
    } finally {
      setBusyKey("");
    }
  };

  const correctStock = async (item) => {
    if (!item.reminder_key) return;
    const targets = new Map();
    (item.requirement_details || []).filter((detail) => Number(detail.remaining_po_qty || 0) > 0).forEach((detail) => {
      const names = (detail.item_names || []).filter(Boolean);
      const itemName = names[0] || detail.stock_type_code || "Item";
      const unit = detail.unit || "";
      targets.set(`${detail.stock_type_code || normalize(itemName)}|${normalizeUnit(unit)}`, { item_name: itemName, unit });
    });
    if (!targets.size) {
      setError("Tidak ada rincian item yang dapat dikoreksi stoknya.");
      return;
    }

    const updates = [];
    for (const target of targets.values()) {
      if (!target.unit) {
        setError(`Satuan ${target.item_name} belum tersedia; koreksi dibatalkan agar tidak salah unit.`);
        return;
      }
      const answer = window.prompt(
        `Stok fisik AKTUAL dapur untuk ${target.item_name} (${target.unit}) sekarang berapa?\n\n` +
        "Isi jumlah yang benar-benar ada saat ini, BUKAN selisih. Kosongkan jika item ini tidak ingin dikoreksi.",
        "",
      );
      if (answer === null) return;
      if (!String(answer).trim()) continue;
      const value = Number(String(answer).replace(",", "."));
      if (!Number.isFinite(value) || value < 0) {
        setError(`Stok ${target.item_name} tidak valid.`);
        return;
      }
      updates.push({ ...target, actual_stock_qty: value });
    }
    if (!updates.length) {
      setMessage("Tidak ada stok yang diubah. Gunakan ‘Sudah dicek / biarkan’ jika selisih memang disengaja.");
      return;
    }
    if (!window.confirm(
      `Catat ${updates.length} stok fisik sebagai koreksi gudang ${site}?\n\n` +
      "Sistem hanya menambah/mengurangi SELISIH terhadap saldo aktual saat ini. SO terakhir tetap utuh.",
    )) return;

    setBusyKey(item.reminder_key);
    setError("");
    setMessage("");
    try {
      const result = await confirmPoShortageStock({
        site,
        reminder_key: item.reminder_key,
        items: updates,
        note: `Cek stok dari residual ${item.po_code || item.vendor_code}`,
      });
      setMessage(result?.message || "Stok dapur dikoreksi. Reminder dihitung ulang.");
      await load();
    } catch (err) {
      setError(err.message || "Gagal mencatat stok dapur");
    } finally {
      setBusyKey("");
    }
  };

  if (!loading && !ordering.length && !review.length && !error && !message) return null;

  return (
    <section className="ops-module">
      <div className="ops-module-header">
        <div>
          <span className="ops-kicker">TINDAKAN PENGINGAT PO</span>
          <h3>Yang Benar-benar Perlu Tindakan</h3>
          <p><strong>Merah</strong> hanya PO yang belum dilakukan. <strong>Kuning</strong> adalah PO yang sudah dilakukan tetapi masih ada selisih planning/stok yang perlu Anda cek.</p>
        </div>
        <button type="button" onClick={load} disabled={loading}><RefreshCw size={15} /> {loading ? "Memuat…" : "Refresh"}</button>
      </div>
      <div className="ops-form-grid">
        <label>Site<select value={site} onChange={(event) => setSite(event.target.value)}><option value="MAJA">MAJA</option><option value="CEMPLANG">CEMPLANG</option></select></label>
      </div>
      {error && <div className="ops-error">{error}</div>}
      {message && <div className="ops-success">{message}</div>}

      {ordering.length > 0 && <div className="ops-draft-group">
        <div className="ops-draft-group-head"><div><strong>🔴 PO belum dilakukan</strong><span>{ordering.length} kebutuhan benar-benar masih harus dibuat/dikirim</span></div></div>
        <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Status</th><th>Vendor</th><th>Masak</th><th>Distribusi</th><th>Item kurang</th><th>Sisa</th><th>Aksi</th></tr></thead><tbody>
          {ordering.map((item, index) => <tr className="ops-reminder-overdue" key={item.reminder_key || `${item.vendor_code}-${index}`}>
            <td><strong>{item.reminder_status === "OVERDUE" ? "Terlambat" : "Hari ini"}</strong><div className="ops-muted">Pesan: {item.po_date || "-"}</div></td>
            <td>{item.vendor_name || item.vendor_code}</td>
            <td>{(item.cooking_dates || []).join(", ") || item.cooking_date || "-"}</td>
            <td>{(item.distribution_dates || []).join(", ") || item.distribution_date || "-"}</td>
            <td>{itemNames(item).join(", ") || "-"}</td>
            <td><strong>{qty(remainingQty(item))}</strong></td>
            <td><button className="ops-button-primary" type="button" onClick={() => createPo(item)} disabled={busyKey === item.reminder_key}><ShoppingCart size={13} /> Buat PO</button></td>
          </tr>)}
        </tbody></table></div>
      </div>}

      {review.length > 0 && <div className="ops-draft-group">
        <div className="ops-draft-group-head"><div><strong>🟡 PO sudah dilakukan — cek selisih</strong><span>{review.length} reminder bukan pekerjaan PO lagi</span></div></div>
        <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>PO</th><th>Vendor</th><th>Distribusi</th><th>Item kurang</th><th>Sisa</th><th>Konfirmasi</th></tr></thead><tbody>
          {review.map((item, index) => <tr className="ops-reminder-shortage" key={item.reminder_key || `${item.vendor_code}-review-${index}`}>
            <td><strong>{item.po_code || "PO sudah dilakukan"}</strong><div className="ops-muted">{item.po_status || "DONE"} · asal reminder {item.shortage_reminder_status || "-"}</div></td>
            <td>{item.vendor_name || item.vendor_code}</td>
            <td>{(item.shortage_distribution_dates || item.distribution_dates || []).join(", ") || item.distribution_date || "-"}</td>
            <td>{(item.shortage_item_names?.length ? item.shortage_item_names : itemNames(item)).join(", ") || "-"}</td>
            <td><strong>{qty(item.shortage_qty_total ?? remainingQty(item))}</strong></td>
            <td><div className="ops-row-actions">
              <button className="ops-button-success" type="button" onClick={() => markChecked(item)} disabled={busyKey === item.reminder_key}><CheckCircle2 size={13} /> Sudah dicek / biarkan</button>
              <button type="button" onClick={() => correctStock(item)} disabled={busyKey === item.reminder_key}><Save size={13} /> Isi stok dapur</button>
            </div></td>
          </tr>)}
        </tbody></table></div>
      </div>}
    </section>
  );
}
