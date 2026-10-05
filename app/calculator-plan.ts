import type { D1DatabaseLike } from "@/db/runtime";
import { operationalCategoryLabels } from "@/app/operational-categories";

export type CalculatorExportItem = {
  itemName: string;
  quantity: number;
  unit: string;
  unitPrice: number;
  totalPrice: number;
  note: string;
  supplierTitle: string;
  operationalCategory: string;
};

export type CalculatorExport = {
  planName: string;
  serviceDate: string;
  portionsSmall: number;
  portionsLarge: number;
  items: CalculatorExportItem[];
  grandTotal: number;
  paguBgn: number;
  difference: number;
};

type StoredPlan = Record<string, unknown> & { _storedUpdatedAt?: string };

const supplierTitles: Record<string, string> = {
  supplier_ayam: "SUPPLIER AYAM",
  supplier_ikan: "SUPPLIER IKAN",
  supplier_tempe_tahu: "SUPPLIER TEMPE & TAHU",
  supplier_telur: "SUPPLIER TELUR",
  supplier_beras: "SUPPLIER BERAS",
  supplier_kering: "BAHAN KERING & KEMASAN",
  supplier_sayur: "SUPPLIER SAYUR/BUMBU",
};

function planDate(plan: StoredPlan) {
  return String(plan.date || plan.serviceDate || plan.tanggal || plan.planDate || "").slice(0, 10);
}

function shoppingPayload(plan: StoredPlan) {
  const raw = plan.shoppingListJSON;
  if (raw && typeof raw === "object") return raw as Record<string, unknown>;
  if (typeof raw === "string") {
    try { return JSON.parse(raw) as Record<string, unknown>; }
    catch { return {}; }
  }
  return {};
}

function shoppingItems(plan: StoredPlan) {
  const payload = shoppingPayload(plan);
  if (Array.isArray(payload.shoppingList)) return payload.shoppingList as Array<Record<string, unknown>>;
  if (Array.isArray(plan.shoppingList)) return plan.shoppingList as Array<Record<string, unknown>>;
  if (Array.isArray(plan.shopping)) return plan.shopping as Array<Record<string, unknown>>;
  return [];
}

function planTime(plan: StoredPlan) {
  for (const value of [plan.updatedAt, plan.createdAt, plan._storedUpdatedAt]) {
    if (value && typeof value === "object") {
      const seconds = Number((value as { seconds?: unknown }).seconds);
      if (Number.isFinite(seconds)) return seconds * 1000;
    }
    const timestamp = Date.parse(String(value || ""));
    if (Number.isFinite(timestamp)) return timestamp;
  }
  return 0;
}

function supplierTitle(item: Record<string, unknown>) {
  const override = String(item.supplierOverride || "").trim();
  if (override) return supplierTitles[override] || override;
  const name = String(item.item || item.name || "").toLocaleLowerCase("id");
  if (/ayam/.test(name)) return supplierTitles.supplier_ayam;
  if (/ikan|dori|tuna|tongkol|lele|nila|bandeng/.test(name)) return supplierTitles.supplier_ikan;
  if (/tempe|tahu/.test(name)) return supplierTitles.supplier_tempe_tahu;
  if (/telur/.test(name)) return supplierTitles.supplier_telur;
  if (/beras/.test(name) && !/tepung/.test(name)) return supplierTitles.supplier_beras;
  if (/tepung|minyak|gula|garam|kecap|saus|bumbu|kaldu|lada|ketumbar|kemiri|gas|plastik|mika|kotak|kemasan/.test(name)) return supplierTitles.supplier_kering;
  return supplierTitles.supplier_sayur;
}

export async function loadCalculatorExport(
  db: D1DatabaseLike,
  unitId: string,
  serviceDate: string,
): Promise<CalculatorExport | null> {
  const rows = await db.prepare(
    `SELECT data_json AS dataJson, updated_at AS storedUpdatedAt
    FROM legacy_documents WHERE unit_id = ? AND collection_path = ?
    ORDER BY updated_at DESC`,
  ).bind(unitId, `artifacts/${unitId}/public/data/dailyPlans`).all<{ dataJson: string; storedUpdatedAt: string }>();

  const candidates = (rows.results || []).flatMap((row) => {
    try {
      const plan = JSON.parse(row.dataJson || "{}") as StoredPlan;
      return [{ ...plan, _storedUpdatedAt: row.storedUpdatedAt }];
    } catch { return []; }
  }).filter((plan) => planDate(plan) === serviceDate);

  const activePlan = candidates.reduce<StoredPlan | null>((selected, plan) => {
    if (!selected) return plan;
    const hasEstimate = shoppingItems(plan).length > 0;
    const selectedHasEstimate = shoppingItems(selected).length > 0;
    if (hasEstimate !== selectedHasEstimate) return hasEstimate ? plan : selected;
    return planTime(plan) > planTime(selected) ? plan : selected;
  }, null);
  if (!activePlan) return null;

  const rawItems = shoppingItems(activePlan);
  const items = rawItems.map((item) => {
    const quantity = Math.max(0, Number(item.jumlah ?? item.quantity ?? 0));
    const unitPrice = Math.max(0, Math.round(Number(item.harga_satuan ?? item.unitPrice ?? 0)));
    const storedTotal = Number(item.total_harga ?? item.totalPrice);
    return {
      itemName: String(item.item || item.name || "Bahan"),
      quantity,
      unit: String(item.satuan || item.unit || "kg"),
      unitPrice,
      totalPrice: Math.round(Number.isFinite(storedTotal) ? storedTotal : quantity * unitPrice),
      note: String(item.note || ""),
      supplierTitle: supplierTitle(item),
      operationalCategory: operationalCategoryLabels[String(item.operationalCategory || "")] ? String(item.operationalCategory) : "lain_lain",
    };
  }).sort((a, b) => a.supplierTitle.localeCompare(b.supplierTitle, "id") || a.itemName.localeCompare(b.itemName, "id"));

  const payload = shoppingPayload(activePlan);
  const calculatedTotal = items.reduce((sum, item) => sum + item.totalPrice, 0);
  const storedGrandTotal = Number(payload.grand_total_num ?? payload.grandTotal);
  const grandTotal = Math.round(Number.isFinite(storedGrandTotal) ? storedGrandTotal : calculatedTotal);
  const portionsSmall = Math.max(0, Math.round(Number(activePlan.porsiKecil || activePlan.portionsSmall || 0)));
  const portionsLarge = Math.max(0, Math.round(Number(activePlan.porsiBesar || activePlan.portionsLarge || 0)));
  const paguBgn = portionsSmall * 8_000 + portionsLarge * 10_000;

  return {
    planName: String(activePlan.planName || activePlan.name || "Rencana Harian"),
    serviceDate,
    portionsSmall,
    portionsLarge,
    items,
    grandTotal,
    paguBgn,
    difference: paguBgn - grandTotal,
  };
}
