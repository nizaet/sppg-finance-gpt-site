import React, { useEffect, useMemo, useState } from "react";
import { BellRing, CalendarDays, CheckCircle2, ClipboardCopy, Layers3, MessageCircle, Pencil, RefreshCw, RotateCcw, Save, Send, ShoppingCart, Trash2, XCircle } from "lucide-react";
import { operationsApi } from "./apiClient";

const today = () => new Date().toISOString().slice(0, 10);
const money = (v) => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(Number(v || 0));
const qty = (v) => Number(v || 0).toLocaleString("id-ID", { maximumFractionDigits: 4 });

const FALLBACK_VENDORS = [
  ["HOLIL", "Haji Holil"],
  ["WIKIAN", "Wikian"],
  ["RUMAH_DUTA_PANGAN", "Rumah Duta Pangan"],
  ["HERU", "Heru"],
  ["DEDE", "Dede"],
  ["HAJI_BADRI", "Haji Badri"],
  ["KOPERASI", "Koperasi / Mungki"],
];

const WHATSAPP_PO_STATUSES = new Set(["FINALIZED", "SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED"]);
const REVISABLE_PO_STATUSES = new Set(["FINALIZED", "SENT", "ACKNOWLEDGED"]);
const REMINDER_LABELS = {
  DONE: "Selesai / sudah dikirim",
  READY_TO_SEND: "Siap dikirim",
  DRAFT_NEEDS_FINAL: "Draft perlu difinalkan",
  LEAD_TIME_MISSING: "Lead time belum diisi",
  OVERDUE: "Terlambat",
  DUE_TODAY: "Kirim hari ini",
  UPCOMING: "Akan datang",
};

function normalize(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function normalizeUnit(value) {
  const unit = normalize(value);
  const aliases = { kilogram: "kg", kilograms: "kg", gram: "gr", liter: "liter", litre: "liter", pieces: "pcs", piece: "pcs", pc: "pcs" };
  return aliases[unit] || unit;
}

function safeVendorForPlanningItem(item, site) {
  const preferred = String(item.preferred_vendor_code || "").trim().toUpperCase();
  if (preferred) return { vendor: preferred, method: "preferred_vendor" };

  const category = normalize(item.category_code);
  const name = normalize(item.item_name);
  const text = `${category} ${name}`;

  if (/\b(ayam|chicken)\b/.test(text)) return { vendor: "WIKIAN", method: "item_rule" };
  if (/\b(dori|ikan|fish)\b/.test(text)) return { vendor: "RUMAH_DUTA_PANGAN", method: "item_rule" };
  if (/\b(gas|lpg)\b/.test(text)) return { vendor: "HERU", method: "item_rule" };
  if (/\bberas\b/.test(text)) return { vendor: "DEDE", method: "item_rule" };
  if (/\btelur\b/.test(text)) return { vendor: "KOPERASI", method: "confirmed_internal_rule" };
  if (/\btahu\b/.test(text)) {
    return site === "CEMPLANG"
      ? { vendor: "HAJI_BADRI", method: "confirmed_site_rule" }
      : { vendor: "KOPERASI", method: "confirmed_internal_rule" };
  }
  if (/\btempe\b/.test(text)) {
    return site === "MAJA"
      ? { vendor: "KOPERASI", method: "confirmed_internal_rule" }
      : { vendor: "", method: "unassigned" };
  }
  if (/\b(bahan kering|sembako|dry goods|packaging)\b/.test(category)) return { vendor: "KOPERASI", method: "confirmed_internal_rule" };
  if (/\b(sayur|buah|bumbu|vegetable|fruit)\b/.test(category)) return { vendor: "HOLIL", method: "category_rule" };
  return { vendor: "", method: "unassigned" };
}

function buildStockLookup(items = []) {
  const exact = new Map();
  const byName = new Map();
  const entries = [];
  items.forEach((item) => {
    const names = Array.from(new Set([item.item_name, ...(item.raw_item_names || [])].map(normalize).filter(Boolean)));
    const unit = normalizeUnit(item.unit);
    const stock = {
      balance: Math.max(0, Number(item.available_for_po ?? item.balance ?? 0)),
      actualBalance: Number(item.actual_balance ?? item.balance ?? 0),
      projectedBalance: Number(item.projected_balance ?? item.balance ?? 0),
      plannedDepletion: Number(item.planned_depletion || 0),
      stockAsOf: item.stock_as_of || null,
      basis: item.stock_basis || "LEDGER_ONLY",
      confidence: item.confidence || "LOW",
    };
    names.forEach((name) => {
      exact.set(`${name}|${unit}`, stock);
      if (!byName.has(name)) byName.set(name, []);
      byName.get(name).push({ unit, ...stock });
      entries.push({ name, unit, stock });
    });
  });
  return { exact, byName, entries };
}

function stockForItem(item, lookup) {
  const name = normalize(item.item_name);
  const unit = normalizeUnit(item.unit);
  const exact = lookup.exact.get(`${name}|${unit}`);
  if (exact != null) return exact;
  const contained = (lookup.entries || []).filter((candidate) => candidate.unit === unit && candidate.name.length >= 4 && (` ${name} `.includes(` ${candidate.name} `) || ` ${candidate.name} `.includes(` ${name} `)));
  if (contained.length) {
    const longest = Math.max(...contained.map((candidate) => candidate.name.length));
    const best = contained.filter((candidate) => candidate.name.length === longest);
    if (best.length === 1) return best[0].stock;
  }
  const candidates = lookup.byName.get(name) || [];
  return candidates.length === 1 ? candidates[0] : { balance: 0, actualBalance: 0, projectedBalance: 0, plannedDepletion: 0, stockAsOf: null, basis: "NO_MATCHING_STOCK", confidence: "LOW" };
}

function dateRange(from, to, maxDays = 7) {
  if (!from || !to || to < from) return [];
  const dates = [];
  const current = new Date(`${from}T12:00:00`);
  const end = new Date(`${to}T12:00:00`);
  while (current <= end && dates.length < maxDays) {
    dates.push(current.toISOString().slice(0, 10));
    current.setDate(current.getDate() + 1);
  }
  return dates;
}

function shiftDate(value, days) {
  const result = new Date(`${value}T12:00:00`);
  result.setDate(result.getDate() + days);
  return result.toISOString().slice(0, 10);
}

function draftItemsForSnapshot(snapshot, inventoryItems, cooperativeItems, site) {
  const stockLookup = buildStockLookup(inventoryItems);
  const cooperativeLookup = buildStockLookup(cooperativeItems);
  return (snapshot?.items || []).map((item) => {
    const assignment = safeVendorForPlanningItem(item, site);
    const planned = item.planned_qty == null ? 0 : Number(item.planned_qty);
    const stock = stockForItem(item, stockLookup);
    const cooperativeStock = assignment.vendor === "KOPERASI" ? stockForItem(item, cooperativeLookup) : null;
    const recommended = Math.max(0, Number((planned - stock.balance).toFixed(4)));
    return {
      planning_snapshot_item_id: item.id,
      item_code: item.item_code || null,
      item_name: item.item_name,
      category_code: item.category_code || "",
      planned_qty: planned,
      stock_qty: stock.balance,
      actual_stock_qty: stock.actualBalance,
      projected_stock_qty: stock.projectedBalance,
      planned_depletion_qty: stock.plannedDepletion,
      stock_as_of: stock.stockAsOf,
      stock_basis: stock.basis,
      stock_confidence: stock.confidence,
      cooperative_stock_qty: cooperativeStock?.balance ?? null,
      cooperative_shortfall_qty: cooperativeStock ? Math.max(0, Number((recommended - cooperativeStock.balance).toFixed(4))) : null,
      recommended_po_qty: recommended,
      po_qty: recommended,
      unit: item.unit || "",
      planning_price: item.planning_price == null ? null : Number(item.planning_price),
      vendor_code: assignment.vendor,
      assignment_method: assignment.method,
      notes: item.notes || "",
      excluded: false,
    };
  });
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  document.body.removeChild(area);
}

function poItemPayload(item) {
  let aliases = item.aliases || item.item_aliases || [];
  if (typeof aliases === "string") {
    try { aliases = JSON.parse(aliases); } catch { aliases = []; }
  }
  if (!Array.isArray(aliases)) aliases = [];
  return {
    item_code: item.item_code || null,
    item_name: String(item.item_name || "").trim(),
    planning_snapshot_item_id: item.planning_snapshot_item_id || null,
    planned_qty: item.planned_qty == null ? null : Number(item.planned_qty),
    po_qty: Number(item.po_qty || 0),
    unit: item.unit || null,
    planning_price: item.planning_price == null ? null : Number(item.planning_price),
    po_price: item.po_price == null ? null : Number(item.po_price),
    aliases,
    notes: item.notes || null,
  };
}

export default function OperationsPoPlanner({ fixedSite = "" }) {
  const [distributionDate, setDistributionDate] = useState(today());
  const [cookingDate, setCookingDate] = useState(today());
  const [site, setSite] = useState(fixedSite || "MAJA");
  const [schedule, setSchedule] = useState([]);
  const [purchaseOrders, setPurchaseOrders] = useState([]);
  const [planningSnapshot, setPlanningSnapshot] = useState(null);
  const [draftItems, setDraftItems] = useState([]);
  const [vendorOptions, setVendorOptions] = useState(FALLBACK_VENDORS.map(([code, name]) => ({ code, name })));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [actionId, setActionId] = useState(null);
  const [creatingVendor, setCreatingVendor] = useState("");
  const [reminders, setReminders] = useState([]);
  const [vendorPhones, setVendorPhones] = useState({});
  const [phoneVendor, setPhoneVendor] = useState("WIKIAN");
  const [phoneValue, setPhoneValue] = useState("");
  const [savingPhone, setSavingPhone] = useState(false);
  const [editingPo, setEditingPo] = useState(null);
  const [editVendor, setEditVendor] = useState("");
  const [editItems, setEditItems] = useState([]);
  const [rangeFrom, setRangeFrom] = useState(today());
  const [rangeTo, setRangeTo] = useState(today());
  const [rangeVendor, setRangeVendor] = useState("WIKIAN");
  const [rangeRows, setRangeRows] = useState([]);
  const [rangeLoading, setRangeLoading] = useState(false);

  useEffect(() => {
    if (fixedSite && site !== fixedSite) setSite(fixedSite);
  }, [fixedSite, site]);

  useEffect(() => {
    setPhoneValue(vendorPhones[phoneVendor] || "");
  }, [phoneVendor, vendorPhones]);

  const activeSite = fixedSite || site;

  const applyPlanningSnapshot = (snapshot, inventoryItems = [], cooperativeItems = []) => {
    setPlanningSnapshot(snapshot || null);
    setDraftItems(draftItemsForSnapshot(snapshot, inventoryItems, cooperativeItems, activeSite));
  };

  const load = async () => {
    setLoading(true);
    setError("");
    setMessage("");
    try {
      const [scheduleData, poData, snapshotsData, vendorsData, inventoryData, cooperativeData] = await Promise.all([
        operationsApi.previewPoSchedule({ distributionDate, cookingDate, site: activeSite }),
        operationsApi.getPurchaseOrders({ site: activeSite, limit: 50 }),
        operationsApi.getPlanningSnapshots({ site: activeSite, distributionDate, activeOnly: true }),
        operationsApi.getReferenceVendors(activeSite),
        operationsApi.getInventoryBalances({ site: activeSite, search: "", limit: 1000, forDate: distributionDate }),
        operationsApi.getInventoryBalances({ site: "KOPERASI", search: "", limit: 1000, forDate: distributionDate }),
      ]);
      const reminderData = await operationsApi.getPoReminders({ site: activeSite, date: today(), horizonDays: 21 });
      setSchedule(scheduleData?.items || []);
      setPurchaseOrders(poData?.items || []);
      setReminders(reminderData?.items || []);

      const uniqueVendors = new Map(FALLBACK_VENDORS.map(([code, name]) => [code, { code, name }]));
      (vendorsData?.items || []).forEach((item) => {
        if (item?.code) uniqueVendors.set(String(item.code).toUpperCase(), { code: String(item.code).toUpperCase(), name: item.name || item.code });
      });
      setVendorOptions(Array.from(uniqueVendors.values()).sort((a, b) => a.name.localeCompare(b.name, "id")));
      const phones = {};
      (vendorsData?.items || []).forEach((item) => {
        if (item?.code && item?.metadata?.whatsapp_phone) phones[String(item.code).toUpperCase()] = String(item.metadata.whatsapp_phone);
      });
      setVendorPhones(phones);
      setPhoneValue(phones[phoneVendor] || "");

      const snapshots = snapshotsData?.items || [];
      if (!snapshots.length) {
        applyPlanningSnapshot(null, inventoryData?.items || [], cooperativeData?.items || []);
      } else {
        const detail = await operationsApi.getPlanningSnapshot(snapshots[0].id);
        applyPlanningSnapshot(detail, inventoryData?.items || [], cooperativeData?.items || []);
      }
    } catch (err) {
      setError(err.message || "Gagal menarik planning Kalkulator / stok / jadwal PO");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [distributionDate, cookingDate, activeSite]);

  const groupedDrafts = useMemo(() => {
    const groups = new Map();
    draftItems.forEach((item) => {
      const vendor = item.vendor_code || "UNASSIGNED";
      if (!groups.has(vendor)) groups.set(vendor, []);
      groups.get(vendor).push(item);
    });
    return Array.from(groups.entries()).map(([vendor, items]) => ({ vendor, items }));
  }, [draftItems]);

  const updateDraftItem = (planningItemId, patch) => {
    setDraftItems((current) => current.map((item) => item.planning_snapshot_item_id === planningItemId ? { ...item, ...patch } : item));
  };

  const createVendorPo = async (vendor) => {
    if (!planningSnapshot?.id || !vendor || vendor === "UNASSIGNED") return;
    const lines = draftItems.filter((item) => item.vendor_code === vendor && !item.excluded && Number(item.po_qty || 0) > 0);
    if (!lines.length) return;

    const code = `PO-${activeSite}-${distributionDate.replaceAll("-", "")}-${vendor}`;
    const confirmed = window.confirm(
      `Buat DRAFT PO ${vendor} untuk ${activeSite} tanggal distribusi ${distributionDate}?\n\n` +
      `${lines.length} item akan disimpan. PO Qty yang disimpan adalah nilai EDIT terakhir, bukan planned_qty dan bukan rekomendasi otomatis.`
    );
    if (!confirmed) return;

    setCreatingVendor(vendor);
    setError("");
    setMessage("");
    try {
      const result = await operationsApi.createPurchaseOrder({
        po_code: code,
        site: activeSite,
        vendor_code: vendor,
        distribution_date: distributionDate,
        cooking_at: cookingDate ? `${cookingDate}T03:00:00+07:00` : null,
        source_planning_snapshot_id: planningSnapshot.id,
        status: "DRAFT",
        items: lines.map((item) => ({
          item_code: item.item_code || null,
          item_name: item.item_name,
          planning_snapshot_item_id: item.planning_snapshot_item_id,
          planned_qty: Number(item.planned_qty || 0),
          po_qty: Number(item.po_qty || 0),
          unit: item.unit || null,
          planning_price: item.planning_price,
          po_price: null,
          aliases: [],
          notes: [item.notes, `stok_proyeksi_saat_draft=${item.stock_qty}`, `stok_aktual_terhitung=${item.actual_stock_qty}`, `so_terakhir=${item.stock_as_of || "tidak_ada"}`, `dasar_stok=${item.stock_basis}`, `keyakinan_stok=${item.stock_confidence}`, `rekomendasi_po=${item.recommended_po_qty}`, item.cooperative_stock_qty != null ? `stok_koperasi=${item.cooperative_stock_qty}` : ""].filter(Boolean).join(" | ") || null,
        })),
      });
      setMessage(`Draft PO ${result.poCode} rev ${result.revisionNo} berhasil dibuat. Belum dianggap terkirim ke vendor.`);
      const poData = await operationsApi.getPurchaseOrders({ site: activeSite, limit: 50 });
      setPurchaseOrders(poData?.items || []);
    } catch (err) {
      setError(err.message || "Gagal membuat draft PO");
    } finally {
      setCreatingVendor("");
    }
  };

  const loadPoPreview = async (poId) => {
    setActionId(poId);
    setError("");
    try {
      return await operationsApi.getPoWhatsAppPreview({ purchaseOrderId: poId });
    } catch (err) {
      setError(err.message || "Gagal menyiapkan pesan PO");
      return null;
    } finally {
      setActionId(null);
    }
  };

  const copyPo = async (poId) => {
    const preview = await loadPoPreview(poId);
    if (!preview?.message) return;
    await copyText(preview.message);
    setMessage("Teks PO sudah disalin. Tinggal paste ke chat vendor.");
  };

  const openWhatsApp = async (poId) => {
    const whatsappWindow = window.open("about:blank", "_blank");
    if (whatsappWindow) whatsappWindow.opener = null;
    const preview = await loadPoPreview(poId);
    if (!preview?.message) {
      whatsappWindow?.close();
      return;
    }
    if (!preview.whatsappBaseUrl) {
      whatsappWindow?.close();
      setPhoneVendor(preview.vendorCode || "");
      setPhoneValue(preview.whatsappPhone || "");
      setError(`Nomor WhatsApp ${preview.vendorName || preview.vendorCode} belum tersimpan. Isi dahulu di menu Vendor & Lead Time.`);
      return;
    }
    const targetUrl = `${preview.whatsappBaseUrl}${encodeURIComponent(preview.message)}`;
    if (whatsappWindow) whatsappWindow.location.replace(targetUrl);
    else window.open(targetUrl, "_blank", "noopener,noreferrer");
    setMessage(`WhatsApp ${preview.vendorName} dibuka dengan pesan PO final. Setelah benar-benar terkirim, klik “Tandai Terkirim”.`);
  };

  const refreshPurchaseOrders = async () => {
    const poData = await operationsApi.getPurchaseOrders({ site: activeSite, limit: 50 });
    setPurchaseOrders(poData?.items || []);
  };

  const saveQuickPhone = async () => {
    if (!phoneVendor || !phoneValue.trim()) {
      setError("Pilih vendor dan isi nomor WhatsApp terlebih dahulu.");
      return;
    }
    setSavingPhone(true);
    setError("");
    setMessage("");
    try {
      const result = await operationsApi.updateVendorWhatsApp(phoneVendor, phoneValue);
      setVendorPhones((current) => ({ ...current, [phoneVendor]: result.whatsappPhone }));
      setPhoneValue(result.whatsappPhone);
      setMessage(`Nomor WhatsApp ${result.vendorName} tersimpan dan sekarang dapat diklik dari PO.`);
    } catch (err) {
      setError(err.message || "Gagal menyimpan nomor WhatsApp vendor");
    } finally {
      setSavingPhone(false);
    }
  };

  const beginEditPo = async (po) => {
    setActionId(po.id);
    setError("");
    setMessage("");
    try {
      let poId = po.id;
      if (String(po.status).toUpperCase() !== "DRAFT") {
        if (!window.confirm(`Buat revisi DRAFT baru dari ${po.po_code} rev ${po.revision_no}?\n\nPO lama tetap disimpan sebagai histori dan tidak ditimpa.`)) return;
        const revised = await operationsApi.revisePurchaseOrder(po.id);
        poId = revised.purchaseOrderId;
        await refreshPurchaseOrders();
      }
      const detail = await operationsApi.getPurchaseOrder(poId);
      setEditingPo(detail);
      setEditVendor(String(detail.vendor_code || ""));
      setEditItems((detail.items || []).map((item) => ({ ...item, po_qty: Number(item.po_qty || 0) })));
    } catch (err) {
      setError(err.message || "Gagal membuka PO untuk diedit");
    } finally {
      setActionId(null);
    }
  };

  const savePoEdit = async () => {
    if (!editingPo) return;
    const lines = editItems.filter((item) => String(item.item_name || "").trim() && Number(item.po_qty || 0) > 0);
    if (!lines.length) {
      setError("PO harus memiliki minimal satu item dengan qty lebih dari 0.");
      return;
    }
    setActionId(editingPo.id);
    setError("");
    setMessage("");
    try {
      await operationsApi.editPurchaseOrder(editingPo.id, { vendor_code: editVendor, items: lines.map(poItemPayload) });
      setEditingPo(null);
      setEditItems([]);
      await refreshPurchaseOrders();
      setMessage(`${editingPo.po_code} rev ${editingPo.revision_no} berhasil diperbarui sebagai DRAFT.`);
    } catch (err) {
      setError(err.message || "Gagal menyimpan edit PO");
    } finally {
      setActionId(null);
    }
  };

  const deletePo = async (po) => {
    if (!window.confirm(`Hapus permanen DRAFT ${po.po_code} rev ${po.revision_no}?`)) return;
    setActionId(po.id);
    setError("");
    try {
      await operationsApi.deletePurchaseOrder(po.id);
      if (editingPo?.id === po.id) setEditingPo(null);
      await refreshPurchaseOrders();
      setMessage(`${po.po_code} rev ${po.revision_no} dihapus.`);
    } catch (err) {
      setError(err.message || "Gagal menghapus DRAFT PO");
    } finally {
      setActionId(null);
    }
  };

  const cancelPo = async (po) => {
    if (!window.confirm(`Batalkan ${po.po_code} rev ${po.revision_no}?\n\nHistori tetap disimpan, tetapi PO tidak lagi aktif.`)) return;
    setActionId(po.id);
    setError("");
    try {
      await operationsApi.cancelPurchaseOrder(po.id);
      await refreshPurchaseOrders();
      setMessage(`${po.po_code} rev ${po.revision_no} dibatalkan.`);
    } catch (err) {
      setError(err.message || "Gagal membatalkan PO");
    } finally {
      setActionId(null);
    }
  };

  const loadRange = async () => {
    const dates = dateRange(rangeFrom, rangeTo, 8);
    if (!dates.length) {
      setError("Rentang tanggal tidak valid.");
      return;
    }
    if (dates.length > 7 || dates[dates.length - 1] !== rangeTo) {
      setError("Maksimal 7 tanggal distribusi dalam satu penarikan.");
      return;
    }
    setRangeLoading(true);
    setError("");
    setMessage("");
    try {
      const rows = await Promise.all(dates.map(async (date) => {
        const [snapshots, stock, cooperative] = await Promise.all([
          operationsApi.getPlanningSnapshots({ site: activeSite, distributionDate: date, activeOnly: true }),
          operationsApi.getInventoryBalances({ site: activeSite, search: "", limit: 1000, forDate: date }),
          operationsApi.getInventoryBalances({ site: "KOPERASI", search: "", limit: 1000, forDate: date }),
        ]);
        const header = snapshots?.items?.[0];
        if (!header) return { date, snapshot: null, items: [] };
        const detail = await operationsApi.getPlanningSnapshot(header.id);
        const items = draftItemsForSnapshot(detail, stock?.items || [], cooperative?.items || [], activeSite)
          .filter((item) => item.vendor_code === rangeVendor);
        return { date, snapshot: detail, items };
      }));
      setRangeRows(rows);
      const count = rows.reduce((sum, row) => sum + row.items.length, 0);
      setMessage(`${count} item ${rangeVendor} ditarik dari ${rows.filter((row) => row.snapshot).length} tanggal planning. Qty masih dapat diedit sebelum dibuat menjadi PO.`);
    } catch (err) {
      setError(err.message || "Gagal menarik planning beberapa tanggal");
    } finally {
      setRangeLoading(false);
    }
  };

  const updateRangeItem = (date, itemId, patch) => {
    setRangeRows((current) => current.map((row) => row.date !== date ? row : {
      ...row,
      items: row.items.map((item) => item.planning_snapshot_item_id === itemId ? { ...item, ...patch } : item),
    }));
  };

  const createRangeDrafts = async () => {
    const candidates = rangeRows.map((row) => ({
      ...row,
      selected: row.items.filter((item) => !item.excluded && Number(item.po_qty || 0) > 0),
    })).filter((row) => row.snapshot && row.selected.length);
    if (!candidates.length) {
      setError("Tidak ada item rentang yang dipilih untuk dibuatkan PO.");
      return;
    }
    if (!window.confirm(`Buat ${candidates.length} DRAFT PO ${rangeVendor}, masing-masing terpisah per tanggal distribusi?\n\nPemisahan tanggal diperlukan agar penerimaan dan stok tidak bercampur.`)) return;
    setRangeLoading(true);
    setError("");
    setMessage("");
    try {
      const created = [];
      for (const row of candidates) {
        const code = `PO-${activeSite}-${row.date.replaceAll("-", "")}-${rangeVendor}`;
        const result = await operationsApi.createPurchaseOrder({
          po_code: code,
          site: activeSite,
          vendor_code: rangeVendor,
          distribution_date: row.date,
          cooking_at: `${shiftDate(row.date, -1)}T03:00:00+07:00`,
          source_planning_snapshot_id: row.snapshot.id,
          status: "DRAFT",
          items: row.selected.map(poItemPayload),
        });
        created.push(result);
      }
      await refreshPurchaseOrders();
      const reminderData = await operationsApi.getPoReminders({ site: activeSite, date: today(), horizonDays: 21 });
      setReminders(reminderData?.items || []);
      setMessage(`${created.length} DRAFT PO ${rangeVendor} berhasil dibuat untuk ${candidates.map((row) => row.date).join(", ")}.`);
    } catch (err) {
      setError(err.message || "Gagal membuat PO rentang tanggal");
    } finally {
      setRangeLoading(false);
    }
  };

  const finalizePo = async (po) => {
    if (!window.confirm(`Finalkan ${po.po_code} rev ${po.revision_no}?\n\nSetelah final, GPTS dan tombol WhatsApp akan memakai PO ini. Data kalkulator tidak berubah.`)) return;
    setActionId(po.id);
    setError("");
    setMessage("");
    try {
      await operationsApi.finalizePurchaseOrder(po.id);
      await refreshPurchaseOrders();
      setMessage(`${po.po_code} sudah FINAL. GPTS sekarang dapat mengambil pesan WhatsApp dari PO hasil edit ini.`);
    } catch (err) {
      setError(err.message || "Gagal memfinalkan PO");
    } finally {
      setActionId(null);
    }
  };

  const markSent = async (po) => {
    if (!window.confirm(`Konfirmasi bahwa ${po.po_code} sudah benar-benar dikirim ke ${po.vendor_code} melalui WhatsApp?`)) return;
    setActionId(po.id);
    setError("");
    setMessage("");
    try {
      await operationsApi.markPurchaseOrderSent(po.id);
      await refreshPurchaseOrders();
      setMessage(`${po.po_code} tercatat sebagai SENT.`);
    } catch (err) {
      setError(err.message || "Gagal menandai PO terkirim");
    } finally {
      setActionId(null);
    }
  };

  const reducedByStock = draftItems.filter((x) => Number(x.stock_qty || 0) > 0 && Number(x.recommended_po_qty) < Number(x.planned_qty)).length;
  const manuallyEdited = draftItems.filter((x) => Number(x.po_qty) !== Number(x.recommended_po_qty)).length;

  return (
    <div className="ops-domain-stack">
      <section className="ops-module">
        <div className="ops-module-header">
          <div>
            <span className="ops-kicker">KALKULATOR + GUDANG → PO EDITABLE</span>
            <h3>Tarik Planning dan Susun PO Vendor</h3>
            <p><strong>Rumus rekomendasi:</strong> Planning Qty − stok proyeksi sebelum tanggal distribusi. Proyeksi berasal dari SO terakhir + movement/aktual − planning hari sebelumnya. <strong>PO Qty tetap bebas Anda edit</strong> tanpa mengubah Kalkulator atau histori SO.</p>
          </div>
          <button type="button" onClick={load} disabled={loading}><RefreshCw size={15} /> {loading ? "Menarik..." : "Tarik Data Kalkulator + Stok"}</button>
        </div>

        <div className="ops-form-grid">
          <label>Site<select value={activeSite} disabled={Boolean(fixedSite)} onChange={(e) => setSite(e.target.value)}><option value="MAJA">MAJA</option><option value="CEMPLANG">CEMPLANG</option></select></label>
          <label>Distribusi<input type="date" value={distributionDate} onChange={(e) => setDistributionDate(e.target.value)} /></label>
          <label>Masak<input type="date" value={cookingDate} onChange={(e) => setCookingDate(e.target.value)} /></label>
        </div>

        <div className="ops-draft-group">
          <div className="ops-draft-group-head">
            <div><strong>Kontak WhatsApp Vendor</strong><span>Isi di sini agar tombol WhatsApp langsung membuka chat orang yang benar.</span></div>
          </div>
          <div className="ops-form-grid">
            <label>Vendor<select value={phoneVendor} onChange={(e) => setPhoneVendor(e.target.value)}>{vendorOptions.map((vendor) => <option key={vendor.code} value={vendor.code}>{vendor.name}</option>)}</select></label>
            <label>Nomor WhatsApp<input value={phoneValue} onChange={(e) => setPhoneValue(e.target.value)} placeholder="contoh: 081234567890 atau 6281234567890" /></label>
            <label>Aksi<div className="ops-row-actions"><button type="button" onClick={saveQuickPhone} disabled={savingPhone || !phoneValue.trim()}><Save size={14} /> {savingPhone ? "Menyimpan…" : "Simpan Nomor"}</button>{vendorPhones[phoneVendor] && <a className="ops-button-link" href={`https://wa.me/${vendorPhones[phoneVendor]}`} target="_blank" rel="noreferrer"><MessageCircle size={14} /> Buka Chat</a>}</div></label>
          </div>
          {!vendorPhones[phoneVendor] && <div className="ops-notice">Nomor {phoneVendor} belum tersimpan. Inilah penyebab tanda merah pada PO; setelah nomor disimpan, tanda itu hilang.</div>}
        </div>

        {error && <div className="ops-error">{error}</div>}
        {message && <div className="ops-success">{message}</div>}

        {!loading && !planningSnapshot && (
          <div className="ops-notice">
            Belum ada planning snapshot Kalkulator untuk <strong>{activeSite}</strong> tanggal {distributionDate}. PO tidak dibuat dari tebakan.
          </div>
        )}

        {planningSnapshot && (
          <>
            <div className="ops-summary-strip">
              <span>Site <strong>{activeSite}</strong></span>
              <span>Snapshot <strong>#{planningSnapshot.id}</strong></span>
              <span>Item <strong>{draftItems.length}</strong></span>
              <span>Dikurangi stok <strong>{reducedByStock}</strong></span>
              <span>PO diedit manual <strong>{manuallyEdited}</strong></span>
              <span>Belum ada vendor <strong>{draftItems.filter((x) => !x.vendor_code).length}</strong></span>
            </div>

            {groupedDrafts.map((group) => (
              <div className="ops-draft-group" key={group.vendor}>
                <div className="ops-draft-group-head">
                  <div>
                    <strong>{group.vendor === "UNASSIGNED" ? "⚠ Vendor belum ditentukan" : group.vendor}</strong>
                    <span>{group.items.length} item</span>
                  </div>
                  {group.vendor !== "UNASSIGNED" && (
                    <button type="button" onClick={() => createVendorPo(group.vendor)} disabled={creatingVendor === group.vendor || group.items.every((x) => x.excluded || Number(x.po_qty || 0) <= 0)}>
                      <ShoppingCart size={15} /> {creatingVendor === group.vendor ? "Menyimpan..." : "Buat Draft PO"}
                    </button>
                  )}
                </div>
                <div className="ops-table-wrap">
                  <table className="ops-table">
                    <thead><tr><th>Ikut PO?</th><th>Item</th><th>Planning</th><th>Stok Gudang</th><th>Rekomendasi PO</th><th>PO Qty — EDIT</th><th>Unit</th><th>Vendor</th><th>Dasar</th></tr></thead>
                    <tbody>
                      {group.items.map((item) => {
                        const isManual = Number(item.po_qty) !== Number(item.recommended_po_qty);
                        return (
                          <tr key={item.planning_snapshot_item_id}>
                            <td>
                              <button type="button" onClick={() => updateDraftItem(item.planning_snapshot_item_id, { excluded: !item.excluded })} title={item.excluded ? "Masukkan kembali ke PO" : "Hapus item dari PO ini"}>
                                {item.excluded ? <RotateCcw size={14} /> : <XCircle size={14} />} {item.excluded ? "Kembalikan" : "Hapus"}
                              </button>
                              {item.excluded && <div className="ops-muted">Tidak dipesan</div>}
                            </td>
                            <td><strong>{item.item_name}</strong><div className="ops-muted">{item.category_code || "-"}</div></td>
                            <td>{qty(item.planned_qty)}</td>
                            <td>
                              <strong>{qty(item.stock_qty)}</strong>
                              <div className="ops-muted">Aktual terhitung {qty(item.actual_stock_qty)} · SO {item.stock_as_of || "belum ada"}</div>
                              {item.planned_depletion_qty > 0 && <div className="ops-muted">− rencana sebelumnya {qty(item.planned_depletion_qty)}</div>}
                              <div className="ops-muted">Keyakinan {item.stock_confidence}</div>
                              {item.cooperative_stock_qty != null && <div className="ops-muted">Koperasi {qty(item.cooperative_stock_qty)}{item.cooperative_shortfall_qty > 0 ? ` · kurang ${qty(item.cooperative_shortfall_qty)}` : ""}</div>}
                            </td>
                            <td><strong>{qty(item.recommended_po_qty)}</strong></td>
                            <td>
                              <div className="ops-row-actions">
                                <input className="ops-qty-input" type="number" min="0" step="0.0001" value={item.po_qty} disabled={item.excluded} onChange={(e) => updateDraftItem(item.planning_snapshot_item_id, { po_qty: Number(e.target.value) })} />
                                {isManual && <button type="button" title="Kembalikan ke rekomendasi" onClick={() => updateDraftItem(item.planning_snapshot_item_id, { po_qty: item.recommended_po_qty })}><RotateCcw size={13} /></button>}
                              </div>
                              {isManual && <div className="ops-muted">Manual override</div>}
                            </td>
                            <td>{item.unit || "-"}</td>
                            <td>
                              <select value={item.vendor_code} disabled={item.excluded} onChange={(e) => updateDraftItem(item.planning_snapshot_item_id, { vendor_code: e.target.value, assignment_method: "manual" })}>
                                <option value="">Pilih vendor</option>
                                {vendorOptions.map((vendor) => <option key={vendor.code} value={vendor.code}>{vendor.name}</option>)}
                              </select>
                            </td>
                            <td>{item.assignment_method === "manual" ? "Manual" : item.assignment_method === "preferred_vendor" ? "Planning" : item.assignment_method === "unassigned" ? "Perlu dipilih" : "Rule operasional"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </>
        )}
      </section>

      <section className="ops-module">
        <div className="ops-module-header">
          <div><span className="ops-kicker">PO AYAM / BERAS / IKAN BEBERAPA HARI</span><h3>Tarik Planning Berdasarkan Rentang Tanggal</h3><p>Pilih vendor dan sampai 7 tanggal distribusi. Qty setiap tanggal tetap dapat diedit; sistem membuat DRAFT terpisah per tanggal agar penerimaan dan stok tidak bercampur.</p></div>
          <Layers3 size={32} />
        </div>
        <div className="ops-form-grid">
          <label>Dari tanggal<input type="date" value={rangeFrom} onChange={(e) => setRangeFrom(e.target.value)} /></label>
          <label>Sampai tanggal<input type="date" value={rangeTo} onChange={(e) => setRangeTo(e.target.value)} /></label>
          <label>Vendor<select value={rangeVendor} onChange={(e) => { setRangeVendor(e.target.value); setRangeRows([]); }}>{vendorOptions.map((vendor) => <option key={vendor.code} value={vendor.code}>{vendor.name}</option>)}</select></label>
        </div>
        <div className="ops-chat-actions">
          <button type="button" onClick={loadRange} disabled={rangeLoading}><RefreshCw size={15} /> {rangeLoading ? "Menarik…" : "Tarik Tanggal Terpilih"}</button>
          <button type="button" onClick={createRangeDrafts} disabled={rangeLoading || !rangeRows.some((row) => row.items.some((item) => !item.excluded && Number(item.po_qty || 0) > 0))}><ShoppingCart size={15} /> Buat Draft PO per Tanggal</button>
        </div>
        {rangeRows.map((row) => (
          <div className="ops-draft-group" key={row.date}>
            <div className="ops-draft-group-head"><div><strong>Distribusi {row.date}</strong><span>{row.snapshot ? `${row.items.length} item ${rangeVendor}` : "Planning belum ada"}</span></div></div>
            {row.snapshot && <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Ikut PO?</th><th>Item</th><th>Planning</th><th>Stok</th><th>Rekomendasi</th><th>PO Qty — EDIT</th><th>Unit</th></tr></thead><tbody>
              {row.items.map((item) => <tr key={`${row.date}-${item.planning_snapshot_item_id}`}>
                <td><button type="button" onClick={() => updateRangeItem(row.date, item.planning_snapshot_item_id, { excluded: !item.excluded })}>{item.excluded ? <RotateCcw size={14} /> : <XCircle size={14} />} {item.excluded ? "Kembalikan" : "Hapus"}</button></td>
                <td><strong>{item.item_name}</strong></td><td>{qty(item.planned_qty)}</td><td>{qty(item.stock_qty)}</td><td>{qty(item.recommended_po_qty)}</td>
                <td><input className="ops-qty-input" type="number" min="0" step="0.0001" value={item.po_qty} disabled={item.excluded} onChange={(e) => updateRangeItem(row.date, item.planning_snapshot_item_id, { po_qty: Number(e.target.value) })} /></td><td>{item.unit || "-"}</td>
              </tr>)}
              {!row.items.length && <tr><td colSpan="7" className="ops-empty-cell">Tidak ada item yang terhubung ke vendor {rangeVendor} pada tanggal ini.</td></tr>}
            </tbody></table></div>}
          </div>
        ))}
      </section>

      <section className="ops-module">
        <div className="ops-module-header">
          <div><span className="ops-kicker">PENGINGAT OTOMATIS</span><h3>PO yang Harus Dikerjakan</h3><p>Pengingat dihitung dari planning aktif dan lead time vendor. PO yang sudah SENT tidak diingatkan lagi untuk tanggal yang sama.</p></div>
          <BellRing size={32} />
        </div>
        <div className="ops-summary-strip"><span>Perlu tindakan <strong>{reminders.filter((item) => ["DUE_TODAY", "OVERDUE", "DRAFT_NEEDS_FINAL", "READY_TO_SEND"].includes(item.reminder_status)).length}</strong></span><span>Cakupan <strong>21 hari</strong></span></div>
        <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Status</th><th>Tanggal Pesan</th><th>Vendor</th><th>Masak</th><th>Distribusi</th><th>Item</th><th>PO</th></tr></thead><tbody>
          {reminders.map((item, index) => <tr key={`${item.vendor_code}-${item.distribution_date}-${index}`}><td><strong>{REMINDER_LABELS[item.reminder_status] || item.reminder_status}</strong></td><td>{item.po_date || "Lead time belum ada"}</td><td>{item.vendor_name || item.vendor_code}</td><td>{item.cooking_date}</td><td>{item.distribution_date}</td><td>{item.item_count}</td><td>{item.po_status || "Belum dibuat"}</td></tr>)}
          {!loading && reminders.length === 0 && <tr><td colSpan="7" className="ops-empty-cell">Belum ada planning aktif dalam 21 hari ke depan.</td></tr>}
        </tbody></table></div>
      </section>

      <section className="ops-module">
        <div className="ops-module-header">
          <div><span className="ops-kicker">JADWAL PO</span><h3>Waktu Pesan Vendor</h3><p>Lead time dihitung dari tanggal masak. Ubah lead time di menu Vendor & Lead Time.</p></div>
        </div>
        <div className="ops-table-wrap">
          <table className="ops-table">
            <thead><tr><th>Vendor</th><th>Kategori</th><th>Lead Time</th><th>Tanggal Pesan</th><th>Flow</th><th>Catatan</th></tr></thead>
            <tbody>
              {schedule.map((item, idx) => (
                <tr key={`${item.vendor_code}-${item.category_code}-${idx}`}>
                  <td><strong>{item.vendor_name}</strong><div className="ops-muted">{item.vendor_code}</div></td>
                  <td>{item.category_code || "-"}</td>
                  <td>{item.lead_time_days_before_cooking == null ? "Belum dikunci" : `H-${item.lead_time_days_before_cooking}`}</td>
                  <td>{item.po_date || "Perlu review"}</td>
                  <td>{item.internal_reimbursement ? "Reimbursement internal" : "Vendor / stok"}{item.intermediary_code ? ` via ${item.intermediary_code}` : ""}</td>
                  <td>{item.notes || "-"}</td>
                </tr>
              ))}
              {!loading && schedule.length === 0 && <tr><td colSpan="6" className="ops-empty-cell"><CalendarDays size={18} /> Belum ada rule aktif.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="ops-module">
        <div className="ops-module-header">
          <div><span className="ops-kicker">PO TERCATAT</span><h3>Purchase Order Aktual</h3><p>Planning, stok, PO, receiving, invoice dan pembayaran tetap layer terpisah.</p></div>
        </div>
        {editingPo && <div className="ops-draft-group">
          <div className="ops-draft-group-head"><div><strong>Edit {editingPo.po_code} · Rev {editingPo.revision_no}</strong><span>PO ini tetap DRAFT sampai difinalkan kembali.</span></div><button type="button" onClick={() => { setEditingPo(null); setEditItems([]); }}><XCircle size={14} /> Tutup</button></div>
          <div className="ops-form-grid"><label>Vendor<select value={editVendor} onChange={(e) => setEditVendor(e.target.value)}>{vendorOptions.map((vendor) => <option key={vendor.code} value={vendor.code}>{vendor.name}</option>)}</select></label></div>
          <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Item</th><th>Qty</th><th>Unit</th><th>Harga PO</th><th>Aksi</th></tr></thead><tbody>
            {editItems.map((item, index) => <tr key={`${item.id || "new"}-${index}`}>
              <td><input value={item.item_name || ""} onChange={(e) => setEditItems((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, item_name: e.target.value } : row))} /></td>
              <td><input className="ops-qty-input" type="number" min="0" step="0.0001" value={item.po_qty ?? 0} onChange={(e) => setEditItems((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, po_qty: Number(e.target.value) } : row))} /></td>
              <td><input value={item.unit || ""} onChange={(e) => setEditItems((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, unit: e.target.value } : row))} /></td>
              <td><input className="ops-qty-input" type="number" min="0" value={item.po_price ?? ""} onChange={(e) => setEditItems((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, po_price: e.target.value === "" ? null : Number(e.target.value) } : row))} /></td>
              <td><button type="button" onClick={() => setEditItems((current) => current.filter((_, rowIndex) => rowIndex !== index))}><Trash2 size={14} /> Hapus Baris</button></td>
            </tr>)}
          </tbody></table></div>
          <div className="ops-chat-actions"><button type="button" onClick={() => setEditItems((current) => [...current, { item_name: "", po_qty: 0, unit: "kg", po_price: null, aliases: [] }])}>+ Tambah Baris</button><button type="button" onClick={savePoEdit} disabled={actionId === editingPo.id}><Save size={14} /> Simpan Edit</button></div>
        </div>}
        <div className="ops-table-wrap">
          <table className="ops-table">
            <thead><tr><th>Distribusi</th><th>PO</th><th>Vendor</th><th>Revisi</th><th>Item</th><th>Total PO</th><th>Status</th><th>Aksi</th></tr></thead>
            <tbody>
              {purchaseOrders.map((po) => {
                const status = String(po.status || "").toUpperCase();
                return <tr key={po.id}>
                  <td>{po.distribution_date || "-"}</td>
                  <td><strong>{po.po_code}</strong><div className="ops-muted">{po.sent_at ? `Sent: ${po.sent_at}` : "Belum ada bukti kirim"}</div></td>
                  <td>{po.vendor_code}</td>
                  <td>{po.revision_no}</td>
                  <td>{po.item_count}</td>
                  <td>{money(po.po_total)}</td>
                  <td>{po.status}</td>
                  <td>
                    <div className="ops-row-actions">
                      {status === "DRAFT" && <button type="button" onClick={() => beginEditPo(po)} disabled={actionId === po.id}><Pencil size={14} /> Edit</button>}
                      {status === "DRAFT" && <button type="button" onClick={() => deletePo(po)} disabled={actionId === po.id}><Trash2 size={14} /> Hapus</button>}
                      {status === "DRAFT" && <button type="button" onClick={() => finalizePo(po)} disabled={actionId === po.id}><CheckCircle2 size={14} /> Finalkan</button>}
                      {REVISABLE_PO_STATUSES.has(status) && <button type="button" onClick={() => beginEditPo(po)} disabled={actionId === po.id}><Pencil size={14} /> Buat Revisi</button>}
                      {WHATSAPP_PO_STATUSES.has(status) && <button type="button" onClick={() => copyPo(po.id)} disabled={actionId === po.id}><ClipboardCopy size={14} /> Copy PO</button>}
                      {WHATSAPP_PO_STATUSES.has(status) && <button type="button" onClick={() => openWhatsApp(po.id)} disabled={actionId === po.id}><MessageCircle size={14} /> WhatsApp Vendor</button>}
                      {status === "FINALIZED" && <button type="button" onClick={() => markSent(po)} disabled={actionId === po.id}><Send size={14} /> Tandai Terkirim</button>}
                      {REVISABLE_PO_STATUSES.has(status) && <button type="button" onClick={() => cancelPo(po)} disabled={actionId === po.id}><XCircle size={14} /> Batalkan</button>}
                    </div>
                  </td>
                </tr>;
              })}
              {!loading && purchaseOrders.length === 0 && <tr><td colSpan="8" className="ops-empty-cell">Belum ada PO tercatat untuk site ini.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
