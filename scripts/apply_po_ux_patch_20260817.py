from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    start_at = text.find(start)
    if start_at < 0:
        raise RuntimeError(f"{label}: start marker not found")
    end_at = text.find(end, start_at)
    if end_at < 0:
        raise RuntimeError(f"{label}: end marker not found")
    return text[:start_at] + replacement + text[end_at:]


# ---------------------------------------------------------------------------
# PO planner
# ---------------------------------------------------------------------------
path = ROOT / "src" / "operations" / "OperationsPoPlanner.jsx"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    'import { operationsApi } from "./apiClient";\n',
    'import { operationsApi } from "./apiClient";\nimport PoQtyMath from "./PoQtyMath.jsx";\n',
    "planner import PoQtyMath",
)

marker = '''function compactTimestamp(value) {
  if (!value) return "";
  return String(value).replace("T", " ").replace(/\\.\\d+Z$/, " WIB");
}
'''
helpers = marker + '''
function poItemSlug(value) {
  return normalize(value).toUpperCase().replace(/\\s+/g, "-").slice(0, 22) || "ITEM";
}

function itemSplitPoCode(site, distributionDate, item) {
  return `PO-${site}-${String(distributionDate || "").replaceAll("-", "")}-${String(item.vendor_code || "").toUpperCase()}-ITEM-${poItemSlug(item.item_name)}`;
}

function remainingReminderQty(item) {
  return Number((item.requirement_details || []).reduce((sum, detail) => sum + Math.max(0, Number(detail.remaining_po_qty || 0)), 0).toFixed(4));
}

function reminderVisual(item) {
  const status = String(item.reminder_status || "").toUpperCase();
  if (item.reminder_override || status === "DONE") {
    return { rowClass: "ops-reminder-done", pillClass: "ops-pill-green", label: item.reminder_override_label || "Selesai / sudah dikirim" };
  }
  if (item.po_already_done && item.shortage_only) {
    return { rowClass: "ops-reminder-shortage", pillClass: "ops-pill-amber", label: "PO sudah dilakukan · cek sisa" };
  }
  if (status === "OVERDUE") return { rowClass: "ops-reminder-overdue", pillClass: "ops-pill-red", label: "Terlambat" };
  if (status === "DUE_TODAY") return { rowClass: "ops-reminder-today", pillClass: "ops-pill-amber", label: "Kirim hari ini" };
  if (status === "UPCOMING") return { rowClass: "ops-reminder-upcoming", pillClass: "ops-pill-blue", label: "Akan datang" };
  if (status === "READY_TO_SEND") return { rowClass: "ops-reminder-ready", pillClass: "ops-pill-blue", label: "Siap dikirim" };
  if (status === "DRAFT_NEEDS_FINAL") return { rowClass: "ops-reminder-draft", pillClass: "ops-pill-purple", label: "Draft perlu difinalkan" };
  return { rowClass: "", pillClass: "", label: REMINDER_LABELS[status] || status || "-" };
}

function poRowClass(status, isHistory) {
  if (isHistory) return "ops-history-row";
  const normalized = String(status || "").toUpperCase();
  if (["SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED"].includes(normalized)) return "ops-po-row-done";
  if (normalized === "DRAFT") return "ops-po-row-draft";
  if (normalized === "FINALIZED") return "ops-po-row-ready";
  return "";
}
'''
text = replace_once(text, marker, helpers, "planner helpers")

text = replace_once(
    text,
    '  const [viewingPo, setViewingPo] = useState(null);\n',
    '  const [viewingPo, setViewingPo] = useState(null);\n  const [reminderActionKey, setReminderActionKey] = useState("");\n',
    "planner reminder action state",
)

text = replace_once(
    text,
    '  const activeSite = fixedSite || site;\n\n  const applyPlanningSnapshot',
    '''  const activeSite = fixedSite || site;

  const findActiveItemSplitPo = (item, forDate = distributionDate) => {
    const expected = itemSplitPoCode(activeSite, forDate, item);
    return purchaseOrders.find((po) => isActivePurchaseOrder(po) && String(po.po_code || "") === expected) || null;
  };

  const refreshReminders = async () => {
    const reminderData = await operationsApi.getPoReminders({ site: activeSite, date: today(), horizonDays: 21 });
    setReminders(reminderData?.items || []);
  };

  const applyPlanningSnapshot''',
    "planner active site helpers",
)

text = replace_once(
    text,
    '    const lines = draftItems.filter((item) => item.vendor_code === vendor && !item.excluded && Number(item.po_qty || 0) > 0);',
    '    const lines = draftItems.filter((item) => item.vendor_code === vendor && !item.excluded && Number(item.po_qty || 0) > 0 && !findActiveItemSplitPo(item, distributionDate));',
    "planner broad PO excludes item split",
)
text = text.replace('operationsApi.createPurchaseOrder({', 'operationsApi.createSplitPurchaseOrder({')
if text.count('operationsApi.createSplitPurchaseOrder({') != 2:
    raise RuntimeError("planner expected two create PO call sites")

insert_marker = '  const loadPoPreview = async (poId) => {'
actions = '''  const createSingleItemPo = async (item) => {
    if (!planningSnapshot?.id || !item?.vendor_code || Number(item.po_qty || 0) <= 0) return;
    const existingSplit = findActiveItemSplitPo(item, distributionDate);
    if (existingSplit) {
      await viewPoDetail(existingSplit);
      return;
    }
    const broadPo = activePoByVendorDate.get(`${item.vendor_code}|${distributionDate}`);
    if (broadPo && !window.confirm(`${broadPo.po_code} (${broadPo.status}) sudah ada untuk vendor/tanggal ini. Buat PO item terpisah hanya jika ini memang pesanan tambahan atau berbeda lead time. Lanjut?`)) return;
    if (!window.confirm(`Buat DRAFT PO SENDIRI untuk ${item.item_name}?\\n\\nQty: ${qty(item.po_qty)} ${item.unit || ""}\\nVendor: ${item.vendor_code}\\nDistribusi: ${distributionDate}\\n\\nItem ini tidak akan ikut PO gabungan pada sesi ini.`)) return;

    const code = itemSplitPoCode(activeSite, distributionDate, item);
    setCreatingVendor(`${item.vendor_code}:${item.planning_snapshot_item_id}`);
    setError("");
    setMessage("");
    try {
      const line = { ...poItemPayload(item), notes: [item.notes, "PO item terpisah berdasarkan lead time/item"].filter(Boolean).join(" | ") || null };
      const result = await operationsApi.createSplitPurchaseOrder({
        po_code: code,
        site: activeSite,
        vendor_code: item.vendor_code,
        distribution_date: distributionDate,
        cooking_at: cookingDate ? `${cookingDate}T03:00:00+07:00` : null,
        source_planning_snapshot_id: planningSnapshot.id,
        status: "DRAFT",
        items: [line],
        coverage: [{
          distribution_date: distributionDate,
          cooking_date: cookingDate || shiftDate(distributionDate, -1),
          source_planning_snapshot_id: planningSnapshot.id,
          items: [line],
        }],
      });
      updateDraftItem(item.planning_snapshot_item_id, { excluded: true, split_po_code: result.poCode });
      await refreshPurchaseOrders();
      await refreshReminders();
      setMessage(`${result.poCode} dibuat khusus ${item.item_name}. Item ini sekarang terpisah dari PO ${item.vendor_code} lainnya.`);
    } catch (err) {
      setError(err.message || "Gagal membuat PO item terpisah");
    } finally {
      setCreatingVendor("");
    }
  };

  const createReminderShortagePo = async (item) => {
    const details = (item.requirement_details || []).filter((detail) => Number(detail.remaining_po_qty || 0) > 0);
    if (!details.length) {
      setError("Tidak ada sisa qty reminder yang dapat ditarik menjadi PO.");
      return;
    }
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
        notes: `PO kekurangan dari reminder ${item.reminder_key || "-"}`,
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
    if (!coverage.length) return;
    const aggregate = new Map();
    coverage.forEach((row) => row.items.forEach((line) => {
      const key = `${normalize(line.item_name)}|${normalizeUnit(line.unit)}`;
      const current = aggregate.get(key);
      if (!current) aggregate.set(key, { ...line });
      else current.po_qty = Number((Number(current.po_qty || 0) + Number(line.po_qty || 0)).toFixed(4));
    }));
    const suffix = String(item.reminder_key || "REMINDER").slice(-8).toUpperCase();
    const code = `PO-${activeSite}-${coverage[0].distribution_date.replaceAll("-", "")}-${item.vendor_code}-KURANG-${suffix}`;
    if (!window.confirm(`Buat DRAFT PO dari sisa kekurangan ${item.vendor_name || item.vendor_code}?\\n\\n${details.length} kebutuhan, total sisa ${qty(remainingReminderQty(item))} (sesuai unit masing-masing). Hanya qty yang belum tercakup yang ditarik.`)) return;
    setReminderActionKey(item.reminder_key || code);
    setError("");
    setMessage("");
    try {
      const result = await operationsApi.createSplitPurchaseOrder({
        po_code: code,
        site: activeSite,
        vendor_code: item.vendor_code,
        distribution_date: coverage[0].distribution_date,
        cooking_at: `${coverage[0].cooking_date}T03:00:00+07:00`,
        source_planning_snapshot_id: null,
        status: "DRAFT",
        items: Array.from(aggregate.values()),
        coverage,
      });
      await refreshPurchaseOrders();
      await refreshReminders();
      setMessage(`${result.poCode} berhasil dibuat dari sisa kekurangan reminder. Silakan cek/edit lalu finalkan.`);
    } catch (err) {
      setError(err.message || "Gagal membuat PO dari kekurangan reminder");
    } finally {
      setReminderActionKey("");
    }
  };

  const saveReminderOverride = async (item, resolution) => {
    if (!item.reminder_key) return;
    const label = resolution === "SUFFICIENT" ? "SUDAH MENCUKUPI" : "PO SUDAH DILAKUKAN MANUAL";
    if (!window.confirm(`${label}?\\n\\nReminder ini akan ditutup dan berwarna hijau. Data planning, stok gudang, dan PO yang sudah ada TIDAK diubah.`)) return;
    const note = window.prompt("Catatan / referensi (opsional):", "") ?? "";
    setReminderActionKey(item.reminder_key);
    setError("");
    setMessage("");
    try {
      await operationsApi.overridePoReminder({
        site: activeSite,
        reminder_key: item.reminder_key,
        vendor_code: item.vendor_code,
        resolution,
        note: note || null,
        metadata: {
          po_date: item.po_date || null,
          distribution_dates: item.distribution_dates || [],
          item_names: item.missing_item_names?.length ? item.missing_item_names : item.item_names || [],
        },
      });
      await refreshReminders();
      setMessage(resolution === "SUFFICIENT" ? "Reminder ditutup: kebutuhan dikonfirmasi sudah mencukupi." : "Reminder ditutup: PO manual dikonfirmasi sudah dilakukan.");
    } catch (err) {
      setError(err.message || "Gagal menyimpan override reminder");
    } finally {
      setReminderActionKey("");
    }
  };

  const clearReminderOverride = async (item) => {
    if (!item.reminder_key || !window.confirm("Batalkan override ini dan kembalikan reminder ke hasil perhitungan sistem?")) return;
    setReminderActionKey(item.reminder_key);
    try {
      await operationsApi.clearPoReminderOverride(item.reminder_key);
      await refreshReminders();
      setMessage("Override dibatalkan. Reminder kembali mengikuti perhitungan sistem.");
    } catch (err) {
      setError(err.message || "Gagal membatalkan override");
    } finally {
      setReminderActionKey("");
    }
  };

'''
text = replace_once(text, insert_marker, actions + insert_marker, "planner action helpers")

text = replace_once(
    text,
    '      selected: row.items.filter((item) => !item.excluded && Number(item.po_qty || 0) > 0),',
    '      selected: row.items.filter((item) => !item.excluded && Number(item.po_qty || 0) > 0 && !findActiveItemSplitPo(item, row.date)),',
    "range excludes split item",
)
text = replace_once(
    text,
    '    purchaseOrders.filter(isActivePurchaseOrder).forEach((po) => {',
    '    purchaseOrders.filter((po) => isActivePurchaseOrder(po) && !String(po.po_code || "").includes("-ITEM-")).forEach((po) => {',
    "active broad PO map ignores item splits",
)

text = replace_once(
    text,
    '''                      {group.items.map((item) => {
                        const isManual = Number(item.po_qty) !== Number(item.recommended_po_qty);
                        return (
                          <tr key={item.planning_snapshot_item_id}>''',
    '''                      {group.items.map((item) => {
                        const isManual = Number(item.po_qty) !== Number(item.recommended_po_qty);
                        const splitPo = findActiveItemSplitPo(item, distributionDate);
                        const hasStock = Number(item.stock_qty || 0) > 0;
                        const coveredByStock = hasStock && Number(item.recommended_po_qty || 0) <= 0;
                        return (
                          <tr key={item.planning_snapshot_item_id} className={coveredByStock ? "ops-row-covered" : hasStock ? "ops-row-has-stock" : ""}>''',
    "planner row stock classes",
)

old_cell = '''                            <td>
                              <button type="button" onClick={() => updateDraftItem(item.planning_snapshot_item_id, { excluded: !item.excluded })} title={item.excluded ? "Masukkan kembali ke PO" : "Hapus item dari PO ini"}>
                                {item.excluded ? <RotateCcw size={14} /> : <XCircle size={14} />} {item.excluded ? "Kembalikan" : "Hapus"}
                              </button>
                              {item.excluded && <div className="ops-muted">Tidak dipesan</div>}
                            </td>'''
new_cell = '''                            <td>
                              {splitPo ? <>
                                <span className="ops-stock-badge ops-stock-covered">✓ PO sendiri</span>
                                <div className="ops-muted">{splitPo.po_code}</div>
                                <button type="button" onClick={() => viewPoDetail(splitPo)}><Eye size={13} /> Lihat</button>
                              </> : <>
                                <button type="button" onClick={() => updateDraftItem(item.planning_snapshot_item_id, { excluded: !item.excluded })} title={item.excluded ? "Masukkan kembali ke PO" : "Hapus item dari PO ini"}>
                                  {item.excluded ? <RotateCcw size={14} /> : <XCircle size={14} />} {item.excluded ? "Kembalikan" : "Hapus"}
                                </button>
                                {item.excluded && <div className="ops-muted">Tidak dipesan</div>}
                                {!item.excluded && item.vendor_code && Number(item.po_qty || 0) > 0 && <button className="ops-button-primary" type="button" onClick={() => createSingleItemPo(item)} disabled={creatingVendor === `${item.vendor_code}:${item.planning_snapshot_item_id}`}><ShoppingCart size={13} /> PO Sendiri</button>}
                              </>}
                            </td>'''
text = replace_once(text, old_cell, new_cell, "planner item split controls")
text = replace_once(
    text,
    '                              <strong>{qty(item.stock_qty)}</strong>\n',
    '                              <strong className={Number(item.stock_qty || 0) > 0 ? "ops-stock-positive" : ""}>{qty(item.stock_qty)}</strong>\n                              {Number(item.stock_qty || 0) > 0 && <div><span className={`ops-stock-badge ${Number(item.recommended_po_qty || 0) <= 0 ? "ops-stock-covered" : "ops-stock-partial"}`}>{Number(item.recommended_po_qty || 0) <= 0 ? "✓ CUKUP DARI GUDANG" : "✓ ADA STOK"}</span></div>}\n',
    "planner stock badge",
)

planning_input = '<input className="ops-qty-input" type="number" min="0" step="0.0001" value={item.po_qty} disabled={item.excluded} onChange={(e) => updateDraftItem(item.planning_snapshot_item_id, { po_qty: Number(e.target.value) })} />'
planning_math = '<PoQtyMath value={item.po_qty} disabled={item.excluded || Boolean(splitPo)} title={item.item_name} onChange={(value) => updateDraftItem(item.planning_snapshot_item_id, { po_qty: value })} />'
text = replace_once(text, planning_input, planning_math, "planner qty math")

range_input = '<input className="ops-qty-input" type="number" min="0" step="0.0001" value={item.po_qty} disabled={item.excluded} onChange={(e) => updateRangeItem(row.date, item.planning_snapshot_item_id, { po_qty: Number(e.target.value) })} />'
range_math = '<PoQtyMath value={item.po_qty} disabled={item.excluded || Boolean(findActiveItemSplitPo(item, row.date))} title={`${item.item_name} ${row.date}`} onChange={(value) => updateRangeItem(row.date, item.planning_snapshot_item_id, { po_qty: value })} />'
text = replace_once(text, range_input, range_math, "range qty math")
text = replace_once(
    text,
    '<tr key={`${row.date}-${item.planning_snapshot_item_id}`}>',
    '<tr key={`${row.date}-${item.planning_snapshot_item_id}`} className={Number(item.stock_qty || 0) > 0 ? Number(item.recommended_po_qty || 0) <= 0 ? "ops-row-covered" : "ops-row-has-stock" : ""}>',
    "range stock row color",
)
text = replace_once(
    text,
    '<td><strong>{item.item_name}</strong></td><td>{qty(item.planned_qty)}</td><td>{qty(item.stock_qty)}</td><td>{qty(item.recommended_po_qty)}</td>',
    '<td><strong>{item.item_name}</strong>{findActiveItemSplitPo(item, row.date) && <div><span className="ops-stock-badge ops-stock-covered">✓ PO sendiri sudah ada</span></div>}</td><td>{qty(item.planned_qty)}</td><td><strong className={Number(item.stock_qty || 0) > 0 ? "ops-stock-positive" : ""}>{qty(item.stock_qty)}</strong></td><td>{qty(item.recommended_po_qty)}</td>',
    "range split badge",
)

edit_input = '<input className="ops-qty-input" type="number" min="0" step="0.0001" value={item.po_qty ?? 0} onChange={(e) => setEditItems((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, po_qty: Number(e.target.value) } : row))} />'
edit_math = '<PoQtyMath value={item.po_qty ?? 0} title={item.item_name || "PO Qty"} onChange={(value) => setEditItems((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, po_qty: value } : row))} />'
text = replace_once(text, edit_input, edit_math, "edit PO qty math")

reminder_start = '      <section className="ops-module">\n        <div className="ops-module-header">\n          <div><span className="ops-kicker">PENGINGAT OTOMATIS</span>'
reminder_end = '      <section className="ops-module">\n        <div className="ops-module-header">\n          <div><span className="ops-kicker">JADWAL PO</span>'
reminder_section = '''      <section className="ops-module">
        <div className="ops-module-header">
          <div><span className="ops-kicker">PENGINGAT OTOMATIS</span><h3>PO yang Harus Dikerjakan</h3><p>Hijau = selesai. Kuning = PO sudah dilakukan tetapi masih ada sisa yang perlu dicek. Merah = terlambat dan belum selesai. Override hanya menutup reminder; tidak mengubah planning, stok, atau PO.</p></div>
          <BellRing size={32} />
        </div>
        <div className="ops-summary-strip">
          <span>Perlu tindakan <strong>{reminders.filter((item) => ["DUE_TODAY", "OVERDUE", "DRAFT_NEEDS_FINAL", "READY_TO_SEND"].includes(item.reminder_status)).length}</strong></span>
          <span className="ops-summary-green">Selesai <strong>{reminders.filter((item) => item.reminder_status === "DONE").length}</strong></span>
          <span>Cakupan <strong>21 hari</strong></span>
        </div>
        <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Status</th><th>Tanggal Pesan</th><th>Vendor</th><th>Masak</th><th>Distribusi</th><th>Item / Sisa</th><th>PO</th><th>Aksi</th></tr></thead><tbody>
          {reminders.map((item, index) => {
            const visual = reminderVisual(item);
            const remaining = remainingReminderQty(item);
            const names = (item.missing_item_names?.length ? item.missing_item_names : item.item_names || []).filter(Boolean);
            const actionableShortage = ["OVERDUE", "DUE_TODAY"].includes(String(item.reminder_status || "").toUpperCase()) && remaining > 0;
            return <tr className={visual.rowClass} key={item.reminder_key || `${item.vendor_code}-${item.distribution_date}-${index}`}>
              <td><span className={`ops-reminder-pill ${visual.pillClass}`}>{visual.label}</span>{item.reminder_override && <div className="ops-muted">Asal: {REMINDER_LABELS[item.override_original_status] || item.override_original_status}</div>}</td>
              <td><strong>{item.po_date || "Lead time belum ada"}</strong></td>
              <td>{item.vendor_name || item.vendor_code}</td>
              <td>{(item.cooking_dates || []).join(", ") || item.cooking_date || "-"}</td>
              <td>{(item.distribution_dates || []).join(", ") || item.distribution_date || "-"}</td>
              <td><strong>{names.length || item.item_count || 0}</strong>{names.length > 0 && <div className="ops-muted ops-item-list">{names.join(", ")}</div>}{remaining > 0 && <div className="ops-shortage-qty">Sisa qty: {qty(remaining)} <small>(unit mengikuti item)</small></div>}</td>
              <td>{item.purchase_order_id ? <div><strong>{item.po_code || item.po_status}</strong><div className="ops-muted">{item.po_status}{item.po_already_done && item.shortage_only ? " · PO sudah dilakukan" : ""}</div><div className="ops-muted">{item.po_sent_at ? `Terkirim: ${compactTimestamp(item.po_sent_at)}` : `Sudah dibuat: ${compactTimestamp(item.po_created_at)}`}</div><button type="button" onClick={() => viewPoDetail(item.purchase_order_id)}><Eye size={13} /> Lihat PO</button></div> : item.manual_po_confirmed ? <span className="ops-stock-badge ops-stock-covered">✓ PO manual dikonfirmasi</span> : <span className="ops-muted">Belum ada PO aplikasi</span>}</td>
              <td><div className="ops-row-actions">
                {item.reminder_override ? <button type="button" onClick={() => clearReminderOverride(item)} disabled={reminderActionKey === item.reminder_key}><RotateCcw size={13} /> Batalkan Override</button> : <>
                  {actionableShortage && <button className="ops-button-primary" type="button" onClick={() => createReminderShortagePo(item)} disabled={reminderActionKey === item.reminder_key}><ShoppingCart size={13} /> {item.po_already_done ? "Buat PO Kekurangan" : "Buat PO"}</button>}
                  {item.reminder_status === "OVERDUE" && item.reminder_key && <button className="ops-button-success" type="button" onClick={() => saveReminderOverride(item, "SUFFICIENT")} disabled={reminderActionKey === item.reminder_key}><CheckCircle2 size={13} /> Sudah mencukupi</button>}
                  {item.reminder_status === "OVERDUE" && item.reminder_key && <button className="ops-button-success" type="button" onClick={() => saveReminderOverride(item, "MANUAL_PO")} disabled={reminderActionKey === item.reminder_key}><Send size={13} /> PO manual sudah dilakukan</button>}
                </>}
              </div></td>
            </tr>;
          })}
          {!loading && reminders.length === 0 && <tr><td colSpan="8" className="ops-empty-cell">Belum ada planning aktif dalam 21 hari ke depan.</td></tr>}
        </tbody></table></div>
      </section>

'''
text = replace_between(text, reminder_start, reminder_end, reminder_section, "replace reminder section")

text = replace_once(
    text,
    'return <tr key={po.id} className={isHistory ? "ops-history-row" : ""}>',
    'return <tr key={po.id} className={poRowClass(status, isHistory)}>',
    "PO actual row color",
)
text = replace_once(
    text,
    '{isHistory ? "HISTORI" : status === "DRAFT" ? "PERLU FINAL" : "PO AKTIF"}',
    '{isHistory ? "HISTORI" : status === "DRAFT" ? "PERLU FINAL" : ["SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED"].includes(status) ? "✓ SELESAI" : "SIAP KIRIM"}',
    "PO actual status label",
)
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------
path = ROOT / "src" / "operations" / "apiClient.js"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '  getPoReminders: ({ site = "", date = "", horizonDays = 14 } = {}) => { const q = new URLSearchParams({ horizonDays: String(horizonDays) }); if (site) q.set("site", site); if (date) q.set("date", date); return request(`/v1/po-reminders-v3?${q}`); },\n',
    '  getPoReminders: ({ site = "", date = "", horizonDays = 14 } = {}) => { const q = new URLSearchParams({ horizonDays: String(horizonDays) }); if (site) q.set("site", site); if (date) q.set("date", date); return request(`/v1/po-reminders-v3?${q}`); },\n  overridePoReminder: (payload) => request("/v1/po-reminders/override", { method: "POST", body: JSON.stringify(payload) }),\n  clearPoReminderOverride: (reminderKey) => request(`/v1/po-reminders/override/${encodeURIComponent(reminderKey)}`, { method: "DELETE" }),\n',
    "api reminder override methods",
)
text = replace_once(
    text,
    '  createPurchaseOrder: (payload) => request("/v1/purchase-orders", { method: "POST", body: JSON.stringify(payload) }),\n',
    '  createPurchaseOrder: (payload) => request("/v1/purchase-orders", { method: "POST", body: JSON.stringify(payload) }),\n  createSplitPurchaseOrder: (payload) => request("/v1/purchase-orders/split", { method: "POST", body: JSON.stringify(payload) }),\n',
    "api split PO method",
)
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Operations CSS colors and compact qty math
# ---------------------------------------------------------------------------
path = ROOT / "src" / "operations" / "workspace.css"
text = path.read_text(encoding="utf-8")
css = r'''

/* PO visual language v0.27: stock, reminder state, and completed workflows */
.ops-row-has-stock { background: rgba(16, 185, 129, 0.075); }
.ops-row-has-stock td:first-child { box-shadow: inset 3px 0 #10b981; }
.ops-row-covered { background: rgba(34, 197, 94, 0.14); }
.ops-row-covered td:first-child { box-shadow: inset 4px 0 #22c55e; }
.ops-stock-positive { color: #86efac; font-size: 13px; }
.ops-stock-badge { display: inline-flex; margin-top: 4px; border-radius: 999px; padding: 3px 7px; font-size: 9px; font-weight: 850; letter-spacing: .025em; border: 1px solid transparent; }
.ops-stock-partial { color: #a7f3d0; background: rgba(5, 150, 105, .22); border-color: rgba(52, 211, 153, .35); }
.ops-stock-covered { color: #bbf7d0; background: rgba(21, 128, 61, .28); border-color: rgba(74, 222, 128, .42); }
.ops-qty-math { display: grid; gap: 4px; width: 118px; }
.ops-qty-math .ops-qty-input { width: 118px; }
.ops-qty-math-buttons { display: grid; grid-template-columns: repeat(4, 1fr); gap: 3px; }
.ops-qty-math-buttons button { min-width: 0 !important; padding: 3px 0 !important; border-radius: 5px !important; font-size: 12px !important; font-weight: 900; }
.ops-button-primary { border-color: rgba(96, 165, 250, .52) !important; background: rgba(30, 64, 175, .32) !important; color: #dbeafe !important; }
.ops-button-success { border-color: rgba(74, 222, 128, .45) !important; background: rgba(21, 128, 61, .25) !important; color: #dcfce7 !important; }
.ops-reminder-pill { display: inline-flex; border-radius: 999px; padding: 5px 8px; font-size: 10px; font-weight: 850; border: 1px solid transparent; white-space: nowrap; }
.ops-pill-green { color: #dcfce7; background: rgba(21, 128, 61, .3); border-color: rgba(74, 222, 128, .42); }
.ops-pill-amber { color: #fef3c7; background: rgba(180, 83, 9, .28); border-color: rgba(251, 191, 36, .45); }
.ops-pill-red { color: #fee2e2; background: rgba(153, 27, 27, .3); border-color: rgba(248, 113, 113, .48); }
.ops-pill-blue { color: #dbeafe; background: rgba(30, 64, 175, .28); border-color: rgba(96, 165, 250, .44); }
.ops-pill-purple { color: #f3e8ff; background: rgba(107, 33, 168, .28); border-color: rgba(192, 132, 252, .42); }
.ops-reminder-done { background: rgba(21, 128, 61, .12); }
.ops-reminder-done td:first-child { box-shadow: inset 4px 0 #22c55e; }
.ops-reminder-shortage { background: rgba(180, 83, 9, .12); }
.ops-reminder-shortage td:first-child { box-shadow: inset 4px 0 #f59e0b; }
.ops-reminder-overdue { background: rgba(153, 27, 27, .095); }
.ops-reminder-overdue td:first-child { box-shadow: inset 4px 0 #ef4444; }
.ops-reminder-today { background: rgba(180, 83, 9, .08); }
.ops-reminder-today td:first-child { box-shadow: inset 4px 0 #f59e0b; }
.ops-reminder-upcoming, .ops-reminder-ready { background: rgba(30, 64, 175, .07); }
.ops-reminder-upcoming td:first-child, .ops-reminder-ready td:first-child { box-shadow: inset 3px 0 #3b82f6; }
.ops-reminder-draft { background: rgba(107, 33, 168, .075); }
.ops-reminder-draft td:first-child { box-shadow: inset 3px 0 #a855f7; }
.ops-shortage-qty { margin-top: 5px; color: #fbbf24; font-weight: 800; }
.ops-shortage-qty small { opacity: .65; font-weight: 500; }
.ops-item-list { max-width: 360px; line-height: 1.35; }
.ops-summary-green { border-color: rgba(74, 222, 128, .38) !important; background: rgba(21, 128, 61, .16) !important; }
.ops-po-row-done { background: rgba(21, 128, 61, .1); }
.ops-po-row-done td:first-child { box-shadow: inset 4px 0 #22c55e; }
.ops-po-row-draft { background: rgba(180, 83, 9, .07); }
.ops-po-row-draft td:first-child { box-shadow: inset 3px 0 #f59e0b; }
.ops-po-row-ready { background: rgba(30, 64, 175, .07); }
.ops-po-row-ready td:first-child { box-shadow: inset 3px 0 #3b82f6; }

html[data-app-theme="light"] .ops-row-has-stock { background: #f0fdf4; }
html[data-app-theme="light"] .ops-row-covered { background: #dcfce7; }
html[data-app-theme="light"] .ops-stock-positive { color: #15803d; }
html[data-app-theme="light"] .ops-stock-partial { color: #047857; background: #d1fae5; border-color: #a7f3d0; }
html[data-app-theme="light"] .ops-stock-covered { color: #166534; background: #dcfce7; border-color: #bbf7d0; }
html[data-app-theme="light"] .ops-button-primary { color: #1e40af !important; background: #dbeafe !important; border-color: #93c5fd !important; }
html[data-app-theme="light"] .ops-button-success { color: #166534 !important; background: #dcfce7 !important; border-color: #86efac !important; }
html[data-app-theme="light"] .ops-pill-green { color: #166534; background: #dcfce7; border-color: #86efac; }
html[data-app-theme="light"] .ops-pill-amber { color: #92400e; background: #fef3c7; border-color: #fcd34d; }
html[data-app-theme="light"] .ops-pill-red { color: #991b1b; background: #fee2e2; border-color: #fca5a5; }
html[data-app-theme="light"] .ops-pill-blue { color: #1e40af; background: #dbeafe; border-color: #93c5fd; }
html[data-app-theme="light"] .ops-pill-purple { color: #6b21a8; background: #f3e8ff; border-color: #d8b4fe; }
html[data-app-theme="light"] .ops-reminder-done, html[data-app-theme="light"] .ops-po-row-done { background: #f0fdf4; }
html[data-app-theme="light"] .ops-reminder-shortage, html[data-app-theme="light"] .ops-reminder-today, html[data-app-theme="light"] .ops-po-row-draft { background: #fffbeb; }
html[data-app-theme="light"] .ops-reminder-overdue { background: #fff1f2; }
html[data-app-theme="light"] .ops-reminder-upcoming, html[data-app-theme="light"] .ops-reminder-ready, html[data-app-theme="light"] .ops-po-row-ready { background: #eff6ff; }
html[data-app-theme="light"] .ops-reminder-draft { background: #faf5ff; }
html[data-app-theme="light"] .ops-shortage-qty { color: #b45309; }
'''
if "/* PO visual language v0.27" not in text:
    text += css
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Operations browser branding
# ---------------------------------------------------------------------------
path = ROOT / "src" / "operations" / "OperationsWorkspace.jsx"
text = path.read_text(encoding="utf-8")
text = replace_once(text, 'import React, { Suspense, lazy, useState } from "react";', 'import React, { Suspense, lazy, useEffect, useState } from "react";', "workspace useEffect import")
text = replace_once(
    text,
    '  const [theme, setTheme] = useAppTheme();\n',
    '''  const [theme, setTheme] = useAppTheme();

  useEffect(() => {
    document.title = "Pusat Operasional | SPPG";
    ["icon", "shortcut icon"].forEach((rel) => {
      let link = document.querySelector(`link[rel='${rel}']`);
      if (!link) {
        link = document.createElement("link");
        link.rel = rel;
        document.head.appendChild(link);
      }
      link.href = "/favicon-operations.svg?v=27";
      link.type = "image/svg+xml";
    });
  }, []);
''',
    "workspace branding effect",
)
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Accountant browser branding (route-aware, not host-only)
# ---------------------------------------------------------------------------
path = ROOT / "src" / "App.jsx"
text = path.read_text(encoding="utf-8")
start = '// BEGIN RUNTIME BROWSER BRAND V8.3'
end = '// END RUNTIME BROWSER BRAND V8.3'
replacement = '''// BEGIN RUNTIME BROWSER BRAND V9.0
const browserPathname = typeof window !== "undefined" ? window.location.pathname.toLowerCase() : "";
const browserIsCemplangAccountant = browserPathname === "/accountant/cemplang" || browserPathname.startsWith("/accountant/cemplang/");
const browserBrand = browserIsCemplangAccountant
  ? { title: "Akuntan Cemplang | SPPG", favicon: "/favicon-accountant-cemplang.svg?v=90" }
  : { title: "Akuntan Maja | SPPG", favicon: "/favicon-accountant-maja.svg?v=90" };

if (typeof document !== "undefined") {
  document.title = browserBrand.title;
  ["icon", "shortcut icon"].forEach((rel) => {
    let favicon = document.querySelector(`link[rel='${rel}']`);
    if (!favicon) {
      favicon = document.createElement("link");
      favicon.rel = rel;
      document.head.appendChild(favicon);
    }
    favicon.type = "image/svg+xml";
    favicon.sizes = "any";
    favicon.href = browserBrand.favicon;
  });
}
// END RUNTIME BROWSER BRAND V9.0'''
start_at = text.find(start)
end_at = text.find(end, start_at)
if start_at < 0 or end_at < 0:
    raise RuntimeError("App browser branding markers not found")
end_at += len(end)
text = text[:start_at] + replacement + text[end_at:]
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Calculator browser branding: generated legacy pages have distinct KM/KC icons
# ---------------------------------------------------------------------------
path = ROOT / "backend" / "calculator_pages.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '    boot = f"""\n    <script>\n',
    '''    calculator_favicon = "/favicon-calc-cemplang.svg?v=27" if unit == "cemplang" else "/favicon-calc-maja.svg?v=27"
    calculator_title = "Kalkulator Cemplang | SPPG" if unit == "cemplang" else "Kalkulator Maja | SPPG"
    boot = f"""
    <link rel="icon" type="image/svg+xml" href="{calculator_favicon}" />
    <link rel="shortcut icon" type="image/svg+xml" href="{calculator_favicon}" />
    <script>
      document.title = {json.dumps(calculator_title)};
''',
    "calculator favicon injection",
)
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Initial HTML brand before React loads
# ---------------------------------------------------------------------------
path = ROOT / "index.html"
text = path.read_text(encoding="utf-8")
script_start = '    <!-- STATIC FAVICON V8.5 -->'
script_end = '<meta charset="UTF-8" />'
initial_brand = '''    <!-- ROUTE-AWARE FAVICON V9.0 -->
    <link id="app-favicon" rel="icon" type="image/svg+xml" href="/favicon-accountant-maja.svg?v=90" />
    <link id="app-shortcut-icon" rel="shortcut icon" type="image/svg+xml" href="/favicon-accountant-maja.svg?v=90" />
    <script>
      (function () {
        var path = window.location.pathname.toLowerCase();
        var icon = "/favicon-accountant-maja.svg?v=90";
        var title = "Akuntan Maja | SPPG";
        if (path === "/operations" || path.indexOf("/operations/") === 0) {
          icon = "/favicon-operations.svg?v=90";
          title = "Pusat Operasional | SPPG";
        } else if (path === "/accountant/cemplang" || path.indexOf("/accountant/cemplang/") === 0) {
          icon = "/favicon-accountant-cemplang.svg?v=90";
          title = "Akuntan Cemplang | SPPG";
        }
        document.getElementById("app-favicon").href = icon;
        document.getElementById("app-shortcut-icon").href = icon;
        document.title = title;
      })();
    </script>

'''
text = replace_between(text, script_start, script_end, initial_brand, "index route branding")
path.write_text(text, encoding="utf-8")

print("PO UX patch applied successfully")
