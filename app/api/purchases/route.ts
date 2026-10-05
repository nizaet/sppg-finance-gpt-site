import { ownerApiGuard } from "@/app/access";
import { legacySupplierKey } from "@/app/order-rules";
import { ensureSchema, getD1, isoNow, type D1Statement } from "@/db/runtime";
import { operationalCategoryLabels, operationalCategoryFromNote, operationalNote } from "@/app/operational-categories";

const categories = new Set([
  "buah_sayur",
  "ayam",
  "ikan",
  "tahu_tempe",
  "telur",
  "beras",
  "bahan_kering",
  "lainnya",
]);
const units = new Set(["maja", "cemplang"]);

const normalizeItem = (value: unknown) => String(value || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").trim().toLowerCase();

async function syncSupplierToKitchen({
  unitId,
  itemName,
  sourceUnit,
  serviceDates,
  supplierCategory,
  now,
}: {
  unitId: string;
  itemName: string;
  sourceUnit: string;
  serviceDates: string[];
  supplierCategory: string;
  now: string;
}) {
  if (!units.has(unitId) || !serviceDates.length || !legacySupplierKey[supplierCategory]) return 0;
  const db = getD1();
  const dates = [...new Set(serviceDates.filter((date) => /^\d{4}-\d{2}-\d{2}$/.test(date)))];
  if (!dates.length) return 0;
  const placeholders = dates.map(() => "?").join(",");
  const collectionPath = `artifacts/${unitId}/public/data/dailyPlans`;
  const rows = await db.prepare(
    `SELECT document_id AS documentId, data_json AS dataJson FROM legacy_documents
    WHERE unit_id = ? AND collection_path = ?
    AND COALESCE(
      substr(json_extract(data_json, '$.date'), 1, 10),
      substr(json_extract(data_json, '$.serviceDate'), 1, 10)
    ) IN (${placeholders})`,
  ).bind(unitId, collectionPath, ...dates).all<{ documentId: string; dataJson: string }>();
  const statements: D1Statement[] = [];
  for (const row of rows.results || []) {
    let plan: Record<string, unknown>;
    try { plan = JSON.parse(row.dataJson || "{}") as Record<string, unknown>; }
    catch { continue; }
    const rawShopping = plan.shoppingListJSON;
    let shopping: { shoppingList?: Array<Record<string, unknown>> };
    let storedAsString = false;
    if (typeof rawShopping === "string") {
      try { shopping = JSON.parse(rawShopping) as { shoppingList?: Array<Record<string, unknown>> }; storedAsString = true; }
      catch { continue; }
    } else {
      shopping = (rawShopping && typeof rawShopping === "object" ? rawShopping : {}) as { shoppingList?: Array<Record<string, unknown>> };
    }
    if (!Array.isArray(shopping.shoppingList)) continue;
    let changed = false;
    shopping.shoppingList.forEach((item) => {
      const sameName = normalizeItem(item.item || item.name || item.itemName) === normalizeItem(itemName);
      const itemUnit = normalizeItem(item.satuan || item.unit);
      const sameUnit = !sourceUnit || !itemUnit || itemUnit === normalizeItem(sourceUnit);
      if (!sameName || !sameUnit) return;
      item.supplierOverride = legacySupplierKey[supplierCategory];
      changed = true;
    });
    if (!changed) continue;
    plan.shoppingListJSON = storedAsString ? JSON.stringify(shopping) : shopping;
    plan.updatedAt = now;
    statements.push(db.prepare(
      `UPDATE legacy_documents SET data_json = ?, updated_at = ?
      WHERE unit_id = ? AND collection_path = ? AND document_id = ?`,
    ).bind(JSON.stringify(plan), now, unitId, collectionPath, row.documentId));
  }
  for (let index = 0; index < statements.length; index += 50) {
    await db.batch(statements.slice(index, index + 50));
  }
  return statements.length;
}

async function refreshWorkflowTotal(workflowId: number) {
  const db = getD1();
  await db
    .prepare(
      `UPDATE workflows SET total_estimate = COALESCE((
        SELECT SUM(quantity * unit_price) FROM purchase_items WHERE workflow_id = ?
      ), 0), updated_at = ? WHERE id = ?`,
    )
    .bind(workflowId, isoNow(), workflowId)
    .run();
}

export async function POST(request: Request) {
  try {
    const denied = await ownerApiGuard();
    if (denied) return denied;
    await ensureSchema();
    const payload = (await request.json()) as {
      workflowId?: number;
      itemName?: string;
      quantity?: number;
      unit?: string;
      unitPrice?: number;
      supplierCategory?: string;
      operationalCategory?: string;
      supplierName?: string;
      note?: string;
    };
    const workflowId = Number(payload.workflowId);
    const itemName = String(payload.itemName || "").trim();
    const quantity = Number(payload.quantity);
    const unit = String(payload.unit || "").trim();
    const unitPrice = Math.max(0, Math.round(Number(payload.unitPrice || 0)));
    const supplierCategory = String(payload.supplierCategory || "");
    const operationalCategory = operationalCategoryLabels[String(payload.operationalCategory || "")] ? String(payload.operationalCategory) : "lain_lain";
    if (
      !Number.isInteger(workflowId) ||
      !itemName ||
      !unit ||
      !Number.isFinite(quantity) ||
      quantity <= 0 ||
      !categories.has(supplierCategory)
    ) {
      return Response.json({ error: "Data item belanja belum lengkap." }, { status: 400 });
    }
    const now = isoNow();
    const inserted = await getD1()
      .prepare(
        `INSERT INTO purchase_items
        (workflow_id, item_name, quantity, unit, unit_price, supplier_category, supplier_name, note, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id`,
      )
      .bind(
        workflowId,
        itemName,
        quantity,
        unit,
        unitPrice,
        supplierCategory,
        String(payload.supplierName || "").trim() || null,
        operationalNote(operationalCategory, payload.note),
        now,
        now,
      )
      .first<{ id: number }>();
    if (!inserted) throw new Error("Item gagal dibuat.");
    await refreshWorkflowTotal(workflowId);
    return Response.json({
      ok: true,
      item: {
        id: inserted.id,
        workflowId,
        itemName,
        quantity,
        unit,
        unitPrice,
        supplierCategory,
        operationalCategory,
        supplierName: String(payload.supplierName || "").trim() || null,
        note: String(payload.note || "").trim() || null,
        orderDate: null,
        sourceJson: null,
        serviceDates: [],
        portionsSmall: 0,
        portionsLarge: 0,
      },
    }, { status: 201 });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : "Gagal menambahkan item." },
      { status: 500 },
    );
  }
}

export async function PATCH(request: Request) {
  try {
    const denied = await ownerApiGuard();
    if (denied) return denied;
    await ensureSchema();
    const payload = (await request.json()) as {
      id?: number; workflowId?: number; quantity?: number; unit?: string; unitPrice?: number;
      supplierCategory?: string; supplierName?: string; note?: string; operationalCategory?: string;
      unitId?: string; sourceItemName?: string; sourceUnit?: string; serviceDates?: string[]; syncSupplier?: boolean;
    };
    const id = Number(payload.id);
    const workflowId = Number(payload.workflowId);
    const quantity = Number(payload.quantity);
    const unit = String(payload.unit || "").trim();
    const unitPrice = Math.max(0, Math.round(Number(payload.unitPrice || 0)));
    const supplierCategory = String(payload.supplierCategory || "");
    const operationalCategory = operationalCategoryLabels[String(payload.operationalCategory || "")] ? String(payload.operationalCategory) : operationalCategoryFromNote(payload.note);
    if (!Number.isInteger(id) || !Number.isInteger(workflowId) || !Number.isFinite(quantity) || quantity < 0 || !unit || !categories.has(supplierCategory)) {
      return Response.json({ error: "Perubahan item belum lengkap." }, { status: 400 });
    }
    const db = getD1();
    const now = isoNow();
    const supplierName = String(payload.supplierName || "").trim() || null;
    const note = String(payload.note || "").trim() || null;
    await db.batch([
      db.prepare(
        `UPDATE purchase_items SET quantity = ?, unit = ?, unit_price = ?, supplier_category = ?,
        supplier_name = ?, note = ?, updated_at = ? WHERE id = ? AND workflow_id = ?`,
      ).bind(quantity, unit, unitPrice, supplierCategory, supplierName, operationalNote(operationalCategory, note), now, id, workflowId),
      db.prepare(
        `UPDATE workflows SET total_estimate = COALESCE((
          SELECT SUM(quantity * unit_price) FROM purchase_items WHERE workflow_id = ?
        ), 0), updated_at = ? WHERE id = ?`,
      ).bind(workflowId, now, workflowId),
    ]);
    const syncedPlans = payload.syncSupplier ? await syncSupplierToKitchen({
      unitId: String(payload.unitId || ""),
      itemName: String(payload.sourceItemName || ""),
      sourceUnit: String(payload.sourceUnit || ""),
      serviceDates: Array.isArray(payload.serviceDates) ? payload.serviceDates.map(String) : [],
      supplierCategory,
      now,
    }) : 0;
    return Response.json({ ok: true, syncedPlans, item: { id, workflowId, quantity, unit, unitPrice, supplierCategory, operationalCategory, supplierName, note } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Gagal menyimpan perubahan item." }, { status: 500 });
  }
}

export async function DELETE(request: Request) {
  try {
    const denied = await ownerApiGuard();
    if (denied) return denied;
    await ensureSchema();
    const url = new URL(request.url);
    const id = Number(url.searchParams.get("id"));
    let workflowId = Number(url.searchParams.get("workflowId"));
    if (!Number.isInteger(id)) {
      return Response.json({ error: "ID item tidak valid." }, { status: 400 });
    }
    const db = getD1();
    if (!Number.isInteger(workflowId)) {
      const row = await db.prepare("SELECT workflow_id AS workflowId FROM purchase_items WHERE id = ?")
        .bind(id).first<{ workflowId: number }>();
      workflowId = Number(row?.workflowId);
    }
    if (!Number.isInteger(workflowId)) return Response.json({ error: "Item tidak ditemukan." }, { status: 404 });
    const now = isoNow();
    await db.batch([
      db.prepare("DELETE FROM purchase_item_meta WHERE purchase_item_id = ?").bind(id),
      db.prepare("DELETE FROM purchase_items WHERE id = ? AND workflow_id = ?").bind(id, workflowId),
      db.prepare(
        `UPDATE workflows SET total_estimate = COALESCE((
          SELECT SUM(quantity * unit_price) FROM purchase_items WHERE workflow_id = ?
        ), 0), updated_at = ? WHERE id = ?`,
      ).bind(workflowId, now, workflowId),
    ]);
    return Response.json({ ok: true });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : "Gagal menghapus item." },
      { status: 500 },
    );
  }
}
