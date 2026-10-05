import { ownerApiGuard } from "@/app/access";
import { ensureSchema, getD1, isoNow } from "@/db/runtime";
import { defaultOperationalItems, operationalCategoryLabels, operationalNote } from "@/app/operational-categories";

const allowedUnits = new Set(["maja", "cemplang"]);
const unitInfo: Record<string, { name: string; bank: string }> = {
  maja: { name: "SPPG Maja Baru", bank: "BNI Direct" },
  cemplang: { name: "SPPG Cemplang 02", bank: "Kopra" },
};

const defaultRules = [
  ["karbo", "Karbohidrat", 100, 150],
  ["protein", "Lauk / Protein", 50, 75],
  ["sayur", "Sayur", 50, 75],
  ["buah", "Buah", 80, 100],
  ["pelengkap", "Pelengkap", 25, 40],
] as const;

function safeJson<T>(value: string | null, fallback: T): T {
  try {
    return value ? (JSON.parse(value) as T) : fallback;
  } catch {
    return fallback;
  }
}

function itemKey(value: string) {
  return value
    .trim()
    .toLocaleLowerCase("id-ID")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

async function seedKitchen(unitId: string) {
  const db = getD1();
  const now = isoNow();
  const info = unitInfo[unitId];
  await db
    .prepare("INSERT OR IGNORE INTO units (id, name, bank_channel, active) VALUES (?, ?, ?, 1)")
    .bind(unitId, info.name, info.bank)
    .run();
  await db.batch(
    defaultRules.map(([id, name, small, large]) =>
      db
        .prepare(
          `INSERT OR IGNORE INTO portion_rules
          (id, unit_id, name, small_grams, large_grams, updated_at)
          VALUES (?, ?, ?, ?, ?, ?)`,
        )
        .bind(id, unitId, name, small, large, now),
    ),
  );
  await db.batch(defaultOperationalItems.map(([name, category, unit, price]) => db.prepare(
    `INSERT OR IGNORE INTO master_prices (unit_id, item_key, item_name, price, purchase_unit, category, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
  ).bind(unitId, itemKey(name), name, unitId === "maja" ? price : 0, unit, category, now)));
}

async function syncPlanToOperations(
  unitId: string,
  serviceDate: string,
  shopping: Array<Record<string, unknown>>,
) {
  const db = getD1();
  const now = isoNow();
  await db
    .prepare(
      `INSERT OR IGNORE INTO workflows
      (unit_id, service_date, status, invoice_status, payment_status, supplier_status,
       dry_goods_status, total_estimate, created_at, updated_at)
      VALUES (?, ?, 'draft', 'belum_diminta', 'belum_dibuat', 'belum_dikirim', 'belum_dikirim', 0, ?, ?)`,
    )
    .bind(unitId, serviceDate, now, now)
    .run();
  const workflow = await db
    .prepare("SELECT id FROM workflows WHERE unit_id = ? AND service_date = ?")
    .bind(unitId, serviceDate)
    .first<{ id: number }>();
  if (!workflow) return;

  await db.prepare("DELETE FROM purchase_items WHERE workflow_id = ?").bind(workflow.id).run();
  if (shopping.length) {
    await db.batch(
      shopping.slice(0, 1000).map((raw) => {
        const quantity = Math.max(0, Number(raw.quantity || 0));
        const unitPrice = Math.max(0, Math.round(Number(raw.unitPrice || 0)));
        return db
          .prepare(
            `INSERT INTO purchase_items
            (workflow_id, item_name, quantity, unit, unit_price, supplier_category,
             supplier_name, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
          )
          .bind(
            workflow.id,
            String(raw.itemName || "Bahan"),
            quantity,
            String(raw.unit || "kg"),
            unitPrice,
            String(raw.supplierCategory || "lainnya"),
            String(raw.supplierName || "").trim() || null,
            operationalNote(String(raw.operationalCategory || "lain_lain"), raw.note || "Dihitung dari rencana menu"),
            now,
            now,
          );
      }),
    );
  }
  const total = shopping.reduce(
    (sum, row) => sum + Number(row.quantity || 0) * Number(row.unitPrice || 0),
    0,
  );
  await db
    .prepare("UPDATE workflows SET total_estimate = ?, status = ?, updated_at = ? WHERE id = ?")
    .bind(Math.round(total), shopping.length ? "final" : "draft", now, workflow.id)
    .run();
}

export async function GET(request: Request) {
  try {
    const denied = await ownerApiGuard();
    if (denied) return denied;
    await ensureSchema();
    const unitId = new URL(request.url).searchParams.get("unitId") || "";
    if (!allowedUnits.has(unitId)) {
      return Response.json({ error: "Dapur tidak valid." }, { status: 400 });
    }
    await seedKitchen(unitId);
    const db = getD1();
    const [recipeRows, planRows, priceRows, ruleRows, settingRows] = await Promise.all([
      db
        .prepare(
          `SELECT id, name, english_name AS englishName, category, method,
          ingredients_json AS ingredientsJson, nutrition_json AS nutritionJson,
          created_at AS createdAt, updated_at AS updatedAt
          FROM recipes WHERE unit_id = ? ORDER BY name`,
        )
        .bind(unitId)
        .all<Record<string, unknown>>(),
      db
        .prepare(
          `SELECT id, plan_name AS planName, service_date AS serviceDate,
          portions_small AS portionsSmall, portions_large AS portionsLarge,
          menus_json AS menusJson, shopping_json AS shoppingJson, status,
          bgn_service_days AS bgnServiceDays, created_at AS createdAt, updated_at AS updatedAt
          FROM daily_plans WHERE unit_id = ? ORDER BY service_date DESC, updated_at DESC`,
        )
        .bind(unitId)
        .all<Record<string, unknown>>(),
      db
        .prepare(
          `SELECT id, item_key AS itemKey, item_name AS itemName, price,
          purchase_unit AS purchaseUnit, category, updated_at AS updatedAt
          FROM master_prices WHERE unit_id = ? ORDER BY item_name`,
        )
        .bind(unitId)
        .all<Record<string, unknown>>(),
      db
        .prepare(
          `SELECT id, name, small_grams AS smallGrams, large_grams AS largeGrams,
          updated_at AS updatedAt FROM portion_rules WHERE unit_id = ? ORDER BY name`,
        )
        .bind(unitId)
        .all<Record<string, unknown>>(),
      db
        .prepare(
          `SELECT setting_key AS settingKey, value_json AS valueJson
          FROM kitchen_settings WHERE unit_id = ?`,
        )
        .bind(unitId)
        .all<Record<string, unknown>>(),
    ]);

    const recipes = (recipeRows.results || []).map((row) => ({
      ...row,
      ingredients: safeJson(String(row.ingredientsJson || "[]"), []),
      nutrition: safeJson(String(row.nutritionJson || "{}"), {}),
      ingredientsJson: undefined,
      nutritionJson: undefined,
    }));
    const plans = (planRows.results || []).map((row) => ({
      ...row,
      menus: safeJson(String(row.menusJson || "[]"), []),
      shopping: safeJson(String(row.shoppingJson || "[]"), []),
      menusJson: undefined,
      shoppingJson: undefined,
    }));
    const settings = Object.fromEntries(
      (settingRows.results || []).map((row) => [
        String(row.settingKey),
        safeJson(String(row.valueJson || "{}"), {}),
      ]),
    );
    return Response.json({
      unitId,
      unit: unitInfo[unitId],
      recipes,
      plans,
      prices: priceRows.results || [],
      rules: ruleRows.results || [],
      settings,
    });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : "Gagal memuat aplikasi dapur." },
      { status: 500 },
    );
  }
}

export async function POST(request: Request) {
  try {
    const denied = await ownerApiGuard();
    if (denied) return denied;
    await ensureSchema();
    const payload = (await request.json()) as Record<string, unknown>;
    const action = String(payload.action || "");
    const unitId = String(payload.unitId || "");
    if (!allowedUnits.has(unitId)) {
      return Response.json({ error: "Dapur tidak valid." }, { status: 400 });
    }
    await seedKitchen(unitId);
    const db = getD1();
    const now = isoNow();

    if (action === "save_recipe") {
      const recipe = (payload.recipe || {}) as Record<string, unknown>;
      const name = String(recipe.name || "").trim().slice(0, 160);
      const ingredients = Array.isArray(recipe.ingredients) ? recipe.ingredients.slice(0, 500) : [];
      if (!name || !ingredients.length) {
        return Response.json({ error: "Nama dan bahan resep wajib diisi." }, { status: 400 });
      }
      const id = String(recipe.id || crypto.randomUUID());
      await db
        .prepare(
          `INSERT INTO recipes
          (id, unit_id, name, english_name, category, method, ingredients_json,
           nutrition_json, created_at, updated_at)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(id) DO UPDATE SET name = excluded.name,
          english_name = excluded.english_name, category = excluded.category,
          method = excluded.method, ingredients_json = excluded.ingredients_json,
          nutrition_json = excluded.nutrition_json, updated_at = excluded.updated_at`,
        )
        .bind(
          id,
          unitId,
          name,
          String(recipe.englishName || "").trim() || null,
          String(recipe.category || "").trim() || null,
          String(recipe.method || "").trim() || null,
          JSON.stringify(ingredients),
          JSON.stringify(recipe.nutrition || {}),
          now,
          now,
        )
        .run();
      return Response.json({ ok: true, id });
    }

    if (action === "delete_recipe") {
      await db
        .prepare("DELETE FROM recipes WHERE id = ? AND unit_id = ?")
        .bind(String(payload.id || ""), unitId)
        .run();
      return Response.json({ ok: true });
    }

    if (action === "save_plan") {
      const plan = (payload.plan || {}) as Record<string, unknown>;
      const planName = String(plan.planName || "").trim().slice(0, 160);
      const serviceDate = String(plan.serviceDate || "");
      const menus = Array.isArray(plan.menus) ? plan.menus.slice(0, 30) : [];
      const shopping = Array.isArray(plan.shopping) ? plan.shopping.slice(0, 1000) : [];
      if (!planName || !/^\d{4}-\d{2}-\d{2}$/.test(serviceDate) || !menus.length) {
        return Response.json({ error: "Nama, tanggal, dan menu rencana wajib diisi." }, { status: 400 });
      }
      const id = String(plan.id || crypto.randomUUID());
      await db
        .prepare(
          `INSERT INTO daily_plans
          (id, unit_id, plan_name, service_date, portions_small, portions_large,
           menus_json, shopping_json, status, bgn_service_days, created_at, updated_at)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(id) DO UPDATE SET plan_name = excluded.plan_name,
          service_date = excluded.service_date, portions_small = excluded.portions_small,
          portions_large = excluded.portions_large, menus_json = excluded.menus_json,
          shopping_json = excluded.shopping_json, status = excluded.status,
          bgn_service_days = excluded.bgn_service_days, updated_at = excluded.updated_at`,
        )
        .bind(
          id,
          unitId,
          planName,
          serviceDate,
          Math.max(0, Math.round(Number(plan.portionsSmall || 0))),
          Math.max(0, Math.round(Number(plan.portionsLarge || 0))),
          JSON.stringify(menus),
          JSON.stringify(shopping),
          String(plan.status || "draft"),
          Number(plan.bgnServiceDays || 1) === 2 ? 2 : 1,
          now,
          now,
        )
        .run();
      await syncPlanToOperations(unitId, serviceDate, shopping as Array<Record<string, unknown>>);
      return Response.json({ ok: true, id });
    }

    if (action === "delete_plan") {
      await db
        .prepare("DELETE FROM daily_plans WHERE id = ? AND unit_id = ?")
        .bind(String(payload.id || ""), unitId)
        .run();
      return Response.json({ ok: true });
    }

    if (action === "save_price") {
      const price = (payload.price || {}) as Record<string, unknown>;
      const itemName = String(price.itemName || "").trim().slice(0, 160);
      const key = itemKey(itemName);
      if (!itemName || !key) {
        return Response.json({ error: "Nama bahan wajib diisi." }, { status: 400 });
      }
      await db
        .prepare(
          `INSERT INTO master_prices
          (unit_id, item_key, item_name, price, purchase_unit, category, updated_at)
          VALUES (?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(unit_id, item_key) DO UPDATE SET item_name = excluded.item_name,
          price = excluded.price, purchase_unit = excluded.purchase_unit,
          category = excluded.category, updated_at = excluded.updated_at`,
        )
        .bind(
          unitId,
          key,
          itemName,
          Math.max(0, Math.round(Number(price.price || 0))),
          String(price.purchaseUnit || "kg"),
          operationalCategoryLabels[String(price.category || "lain_lain")] ? String(price.category || "lain_lain") : "lain_lain",
          now,
        )
        .run();
      return Response.json({ ok: true });
    }

    if (action === "delete_price") {
      await db
        .prepare("DELETE FROM master_prices WHERE id = ? AND unit_id = ?")
        .bind(Number(payload.id), unitId)
        .run();
      return Response.json({ ok: true });
    }

    if (action === "save_rule") {
      const rule = (payload.rule || {}) as Record<string, unknown>;
      const name = String(rule.name || "").trim().slice(0, 120);
      const id = itemKey(String(rule.id || name));
      if (!name || !id) return Response.json({ error: "Nama aturan wajib diisi." }, { status: 400 });
      await db
        .prepare(
          `INSERT INTO portion_rules (id, unit_id, name, small_grams, large_grams, updated_at)
          VALUES (?, ?, ?, ?, ?, ?)
          ON CONFLICT(unit_id, id) DO UPDATE SET name = excluded.name,
          small_grams = excluded.small_grams, large_grams = excluded.large_grams,
          updated_at = excluded.updated_at`,
        )
        .bind(
          id,
          unitId,
          name,
          Math.max(0, Number(rule.smallGrams || 0)),
          Math.max(0, Number(rule.largeGrams || 0)),
          now,
        )
        .run();
      return Response.json({ ok: true });
    }

    if (action === "delete_rule") {
      await db
        .prepare("DELETE FROM portion_rules WHERE id = ? AND unit_id = ?")
        .bind(String(payload.id || ""), unitId)
        .run();
      return Response.json({ ok: true });
    }

    if (action === "save_setting") {
      const key = itemKey(String(payload.key || ""));
      if (!key) return Response.json({ error: "Kunci pengaturan tidak valid." }, { status: 400 });
      await db
        .prepare(
          `INSERT INTO kitchen_settings (unit_id, setting_key, value_json, updated_at)
          VALUES (?, ?, ?, ?)
          ON CONFLICT(unit_id, setting_key) DO UPDATE SET value_json = excluded.value_json,
          updated_at = excluded.updated_at`,
        )
        .bind(unitId, key, JSON.stringify(payload.value || {}), now)
        .run();
      return Response.json({ ok: true });
    }

    return Response.json({ error: "Aksi tidak dikenali." }, { status: 400 });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : "Perubahan aplikasi dapur gagal." },
      { status: 500 },
    );
  }
}
