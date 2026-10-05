import { ownerApiGuard } from "@/app/access";
import { loadCalculatorExport } from "@/app/calculator-plan";
import { loadOrderRules } from "@/app/order-rules";
import { syncSupplierPayments } from "@/app/supplier-payment-sync";
import { operationalCategoryFromNote } from "@/app/operational-categories";
import { ensureSchema, getD1, isoNow, jakartaDate } from "@/db/runtime";

type UnitRow = { id: string; name: string; bankChannel: string };
type WorkflowRow = {
  id: number;
  unitId: string;
  serviceDate: string;
  status: string;
  invoiceStatus: string;
  paymentStatus: string;
  supplierStatus: string;
  dryGoodsStatus: string;
  totalEstimate: number;
  invoiceAmount: number;
  paymentReference: string | null;
};
type TaskRow = {
  id: number;
  workflowId: number;
  taskType: string;
  title: string;
  dueTime: string;
  status: string;
  assignee: string | null;
  completedAt: string | null;
};
type PurchaseRow = {
  id: number;
  workflowId: number;
  itemName: string;
  quantity: number;
  unit: string;
  unitPrice: number;
  supplierCategory: string;
  supplierName: string | null;
  note: string | null;
  orderDate: string | null;
  sourceJson: string | null;
  portionsSmall: number;
  portionsLarge: number;
};
type ImportRow = {
  id: number;
  unitId: string;
  fileName: string;
  sizeBytes: number;
  status: string;
  importedAt: string;
};
type SupplierRow = {
  id: number;
  name: string;
  category: string;
  phone: string | null;
  role: string;
  unitScope: string;
  active: number;
};
type DailyPaymentRow = {
  id: number; unitId: string; serviceDate: string; recipientType: string; recipientName: string; role: string;
  rate: number; amount: number; proofNumber: string; receiptStatus: string; paymentStatus: string;
  paymentReference: string | null; note: string | null;
};
const unitSeeds = [
  { id: "maja", name: "SPPG Maja Baru", bank: "BNI Direct" },
  { id: "cemplang", name: "SPPG Cemplang 02", bank: "Kopra" },
];

const taskSeeds = [
  ["maker", "Lakukan maker pembayaran bank", "06:00"],
  ["cek_pembayaran", "Pastikan transaksi berhasil / menunggu checker", "09:00"],
  ["invoice", "Unduh Excel kalkulator dan kirim ke akuntan", "13:00"],
  ["buah_sayur", "Pesan buah dan sayur ke Haji Holil", "14:00"],
  ["protein", "Pesan tahu, tempe, dan/atau telur", "14:15"],
  ["bahan_kering", "Kirim daftar bahan kering ke admin koperasi", "14:30"],
  ["final", "Pemeriksaan akhir PO dan invoice", "17:00"],
] as const;

const supplierSeeds = [
  ["Haji Holil", "buah_sayur", "supplier"],
  ["Supplier Ayam", "ayam", "supplier"],
  ["Supplier Ikan", "ikan", "supplier"],
  ["Supplier Tempe & Tahu", "tahu_tempe", "supplier"],
  ["Supplier Telur", "telur", "supplier"],
  ["Supplier Beras", "beras", "supplier"],
  ["Admin Koperasi", "bahan_kering", "supplier"],
  ["Supplier Lainnya", "lainnya", "supplier"],
  ["Akuntan", "akuntan", "accountant"],
] as const;

async function seedDay(serviceDate: string) {
  const db = getD1();
  const now = isoNow();
  await db.batch(
    unitSeeds.map((unit) =>
      db
        .prepare(
          "INSERT OR IGNORE INTO units (id, name, bank_channel, active) VALUES (?, ?, ?, 1)",
        )
        .bind(unit.id, unit.name, unit.bank),
    ),
  );
  await db.batch(supplierSeeds.map(([name, category, role]) => db.prepare(
    `INSERT INTO suppliers (name, category, phone, role, unit_scope, active)
    SELECT ?, ?, NULL, ?, 'all', 1
    WHERE NOT EXISTS (SELECT 1 FROM suppliers WHERE name = ? AND unit_scope = 'all')`,
  ).bind(name, category, role, name)));

  for (const unit of unitSeeds) {
    await db
      .prepare(
        `INSERT OR IGNORE INTO workflows
        (unit_id, service_date, status, invoice_status, payment_status, supplier_status, dry_goods_status, total_estimate, created_at, updated_at)
        VALUES (?, ?, 'draft', 'belum_diminta', 'belum_dibuat', 'belum_dikirim', 'belum_dikirim', 0, ?, ?)`,
      )
      .bind(unit.id, serviceDate, now, now)
      .run();
    const workflow = await db
      .prepare("SELECT id FROM workflows WHERE unit_id = ? AND service_date = ?")
      .bind(unit.id, serviceDate)
      .first<{ id: number }>();
    if (!workflow) continue;
    await db.batch(
      taskSeeds.map(([type, title, time]) =>
        db
          .prepare(
            `INSERT OR IGNORE INTO tasks
            (workflow_id, task_type, title, due_time, status, updated_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
            ON CONFLICT(workflow_id, task_type) DO UPDATE SET
              title = excluded.title, due_time = excluded.due_time, updated_at = excluded.updated_at`,
          )
          .bind(workflow.id, type, title, time, now),
      ),
    );
  }
}

export async function GET(request: Request) {
  try {
    const denied = await ownerApiGuard();
    if (denied) return denied;
    await ensureSchema();
    const url = new URL(request.url);
    const serviceDate = url.searchParams.get("date") || jakartaDate();
    await seedDay(serviceDate);
    const db = getD1();

    const units = await db
      .prepare(
        "SELECT id, name, bank_channel AS bankChannel FROM units WHERE active = 1 ORDER BY id DESC",
      )
      .all<UnitRow>();
    const workflows = await db
      .prepare(
        `SELECT id, unit_id AS unitId, service_date AS serviceDate, status,
        invoice_status AS invoiceStatus, payment_status AS paymentStatus,
        supplier_status AS supplierStatus, dry_goods_status AS dryGoodsStatus,
        total_estimate AS totalEstimate, invoice_amount AS invoiceAmount,
        payment_reference AS paymentReference
        FROM workflows WHERE service_date = ? ORDER BY unit_id DESC`,
      )
      .bind(serviceDate)
      .all<WorkflowRow>();
    const workflowIds = (workflows.results || []).map((row) => row.id);

    let tasks: TaskRow[] = [];
    let purchases: PurchaseRow[] = [];
    if (workflowIds.length) {
      const placeholders = workflowIds.map(() => "?").join(",");
      tasks =
        (
          await db
            .prepare(
              `SELECT id, workflow_id AS workflowId, task_type AS taskType, title,
              due_time AS dueTime, status, assignee, completed_at AS completedAt
              FROM tasks WHERE workflow_id IN (${placeholders}) ORDER BY due_time, id`,
            )
            .bind(...workflowIds)
            .all<TaskRow>()
        ).results || [];
      purchases =
        (
          await db
            .prepare(
              `SELECT purchase_items.id, workflow_id AS workflowId, item_name AS itemName, quantity,
              unit, unit_price AS unitPrice, supplier_category AS supplierCategory,
              supplier_name AS supplierName, note, purchase_item_meta.order_date AS orderDate,
              purchase_item_meta.source_json AS sourceJson,
              COALESCE(purchase_item_meta.portions_small, 0) AS portionsSmall,
              COALESCE(purchase_item_meta.portions_large, 0) AS portionsLarge
              FROM purchase_items
              LEFT JOIN purchase_item_meta ON purchase_item_meta.purchase_item_id = purchase_items.id
              WHERE workflow_id IN (${placeholders}) ORDER BY supplier_category, item_name`,
            )
            .bind(...workflowIds)
            .all<PurchaseRow>()
        ).results || [];
    }

    const imports = await db
      .prepare(
        `SELECT id, unit_id AS unitId, file_name AS fileName, size_bytes AS sizeBytes,
        status, imported_at AS importedAt FROM legacy_imports ORDER BY id DESC LIMIT 20`,
      )
      .all<ImportRow>();
    const suppliers = await db.prepare(
      `SELECT id, name, category, phone, role, unit_scope AS unitScope, active
      FROM suppliers WHERE active = 1 ORDER BY role, category, name`,
    ).all<SupplierRow>();
    const dailyPayments = await db.prepare(`SELECT id, unit_id AS unitId, service_date AS serviceDate,
      recipient_type AS recipientType, recipient_name AS recipientName, role, rate, amount,
      proof_number AS proofNumber, receipt_status AS receiptStatus, payment_status AS paymentStatus,
      payment_reference AS paymentReference, note FROM daily_payments WHERE service_date = ? ORDER BY unit_id, recipient_name, id`)
      .bind(serviceDate).all<DailyPaymentRow>();

    const workflowRows = workflows.results || [];
    const supplierPayments = await syncSupplierPayments(db, workflowRows, purchases);
    const calculatorTotals = new Map<number, number>();
    await Promise.all(workflowRows.map(async (workflow) => {
      const calculator = await loadCalculatorExport(db, workflow.unitId, workflow.serviceDate);
      calculatorTotals.set(workflow.id, calculator?.grandTotal || 0);
    }));
    const orderRules = await loadOrderRules();
    return Response.json({
      date: serviceDate,
      units: units.results || [],
      workflows: workflowRows.map((workflow) => ({ ...workflow, calculatorInvoiceTotal: calculatorTotals.get(workflow.id) || 0 })),
      tasks,
      purchases: purchases.map((item) => {
        let serviceDates: string[] = [];
        try {
          const sources = JSON.parse(item.sourceJson || "[]") as Array<{ serviceDate?: string }>;
          serviceDates = [...new Set(sources.map((source) => String(source.serviceDate || "")).filter(Boolean))].sort();
        } catch { serviceDates = []; }
        return { ...item, operationalCategory: operationalCategoryFromNote(item.note), serviceDates };
      }),
      imports: imports.results || [],
      suppliers: suppliers.results || [],
      supplierPayments,
      dailyPayments: dailyPayments.results || [],
      orderRules,
    });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : "Gagal memuat pusat kontrol." },
      { status: 500 },
    );
  }
}
