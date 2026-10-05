import { ownerApiGuard } from "@/app/access";
import { detectSupplierCategory } from "@/app/order-rules";
import { ensureSchema, getD1, isoNow } from "@/db/runtime";
import { operationalCategoryFromNote, operationalNote } from "@/app/operational-categories";

const units = new Set(["maja", "cemplang"]);
const defaultSupplierNames: Record<string, string> = {
  buah_sayur: "Haji Holil", ayam: "Supplier Ayam", ikan: "Supplier Ikan",
  tahu_tempe: "Supplier Tempe & Tahu", telur: "Supplier Telur", beras: "Supplier Beras",
  bahan_kering: "Admin Koperasi", lainnya: "Supplier Lainnya",
};

export async function POST(request: Request) {
  try {
    const denied = await ownerApiGuard();
    if (denied) return denied;
    await ensureSchema();
    const payload = (await request.json()) as { unitId?: string; serviceDate?: string };
    const unitId = String(payload.unitId || "");
    const serviceDate = String(payload.serviceDate || "");
    if (!units.has(unitId) || !/^\d{4}-\d{2}-\d{2}$/.test(serviceDate)) {
      return Response.json({ error: "Dapur atau tanggal tidak valid." }, { status: 400 });
    }
    const db = getD1();
    const rows = await db.prepare(
      `SELECT data_json AS dataJson, updated_at AS storedUpdatedAt FROM legacy_documents
      WHERE unit_id = ? AND collection_path = ? ORDER BY updated_at DESC`,
    ).bind(unitId, `artifacts/${unitId}/public/data/dailyPlans`).all<{ dataJson: string; storedUpdatedAt: string }>();
    const candidates = (rows.results || []).map((row) => {
      try { return { ...JSON.parse(row.dataJson || "{}") as Record<string, unknown>, _storedUpdatedAt: row.storedUpdatedAt }; }
      catch { return {} as Record<string, unknown>; }
    }).filter((plan) => String(plan.date || plan.serviceDate || "").slice(0, 10) === serviceDate);
    const shoppingFor = (plan: Record<string, unknown>) => {
      const raw = plan.shoppingListJSON;
      if (raw && typeof raw === "object" && Array.isArray((raw as { shoppingList?: unknown[] }).shoppingList)) {
        return (raw as { shoppingList: Array<Record<string, unknown>> }).shoppingList;
      }
      if (typeof raw === "string") {
        try {
          const parsed = JSON.parse(raw) as { shoppingList?: Array<Record<string, unknown>> };
          return Array.isArray(parsed.shoppingList) ? parsed.shoppingList : [];
        } catch { return []; }
      }
      return [];
    };
    const planTime = (plan: Record<string, unknown>) => {
      for (const value of [plan.updatedAt, plan.createdAt, plan._storedUpdatedAt]) {
        const timestamp = Date.parse(String(value || ""));
        if (Number.isFinite(timestamp)) return timestamp;
      }
      return 0;
    };
    const activePlan = candidates.reduce<Record<string, unknown> | null>((selected, plan) => {
      if (!selected) return plan;
      const hasEstimate = shoppingFor(plan).length > 0;
      const selectedHasEstimate = shoppingFor(selected).length > 0;
      if (hasEstimate !== selectedHasEstimate) return hasEstimate ? plan : selected;
      return planTime(plan) > planTime(selected) ? plan : selected;
    }, null);
    if (!activePlan) return Response.json({ error: "Tidak ada rencana dapur pada tanggal ini." }, { status: 404 });
    const shopping = shoppingFor(activePlan);
    if (!shopping.length) return Response.json({ error: "Rencana ditemukan, tetapi estimasi belanja belum dihitung di aplikasi kalkulator." }, { status: 409 });
    const workflow = await db.prepare("SELECT id FROM workflows WHERE unit_id = ? AND service_date = ?")
      .bind(unitId, serviceDate).first<{ id: number }>();
    if (!workflow) return Response.json({ error: "Workflow pusat kontrol belum tersedia. Muat ulang halaman lalu coba lagi." }, { status: 404 });
    const now = isoNow();
    await db.prepare(
      "DELETE FROM purchase_item_meta WHERE purchase_item_id IN (SELECT id FROM purchase_items WHERE workflow_id = ?)",
    ).bind(workflow.id).run();
    await db.prepare("DELETE FROM purchase_items WHERE workflow_id = ?").bind(workflow.id).run();
    for (let index = 0; index < shopping.length; index += 50) {
      await db.batch(shopping.slice(index, index + 50).map((item) => {
        const category = detectSupplierCategory(item);
        return db.prepare(
          `INSERT INTO purchase_items
          (workflow_id, item_name, quantity, unit, unit_price, supplier_category, supplier_name, note, created_at, updated_at)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        ).bind(
          workflow.id,
          String(item.item || item.name || "Bahan"),
          Math.max(0, Number(item.jumlah || item.quantity || 0)),
          String(item.satuan || item.unit || "kg"),
          Math.max(0, Math.round(Number(item.harga_satuan || item.unitPrice || 0))),
          category,
          defaultSupplierNames[category],
          operationalNote(String(item.operationalCategory || operationalCategoryFromNote(item.note)), item.note || "Ditarik dari aplikasi dapur"),
          now,
          now,
        );
      }));
    }
    const total = shopping.reduce((sum, item) => sum + (Number(item.jumlah || item.quantity || 0) * Number(item.harga_satuan || item.unitPrice || 0)), 0);
    const portionsSmall = Math.max(0, Math.round(Number(activePlan.porsiKecil || 0)));
    const portionsLarge = Math.max(0, Math.round(Number(activePlan.porsiBesar || 0)));
    const inserted = await db.prepare(
      `SELECT id, workflow_id AS workflowId, item_name AS itemName, quantity, unit,
      unit_price AS unitPrice, supplier_category AS supplierCategory,
      supplier_name AS supplierName, note FROM purchase_items
      WHERE workflow_id = ? ORDER BY supplier_category, item_name`,
    ).bind(workflow.id).all<{
      id: number; workflowId: number; itemName: string; quantity: number; unit: string;
      unitPrice: number; supplierCategory: string; supplierName: string | null; note: string | null;
    }>();
    const purchases = (inserted.results || []).map((item) => {
      const sources = [{ serviceDate, quantity: item.quantity, portionsSmall, portionsLarge }];
      return { ...item, operationalCategory: operationalCategoryFromNote(item.note), orderDate: serviceDate, sourceJson: JSON.stringify(sources), serviceDates: [serviceDate], portionsSmall, portionsLarge };
    });
    for (let index = 0; index < purchases.length; index += 50) {
      await db.batch(purchases.slice(index, index + 50).map((item) => db.prepare(
          `INSERT INTO purchase_item_meta
          (purchase_item_id, order_date, source_json, portions_small, portions_large, updated_at)
          VALUES (?, ?, ?, ?, ?, ?)`,
        ).bind(item.id, serviceDate, item.sourceJson, portionsSmall, portionsLarge, now)));
    }
    await db.prepare("UPDATE workflows SET total_estimate = ?, status = 'draft', updated_at = ? WHERE id = ?")
      .bind(Math.round(total), now, workflow.id).run();
    return Response.json({ ok: true, plans: 1, count: shopping.length, items: purchases, total: Math.round(total) });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Gagal menarik estimasi dapur." }, { status: 500 });
  }
}
