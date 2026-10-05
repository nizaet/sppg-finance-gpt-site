"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { downloadXlsx } from "./xlsx";
import InvoiceDocumentsClient from "./invoice-documents-client";
import { operationalCategories, operationalCategoryLabels, operationalCategoryFromNote, operationalNote } from "./operational-categories";

type Unit = { id: string; name: string; bankChannel: string };
type Workflow = {
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
  calculatorInvoiceTotal: number;
};
type Task = {
  id: number;
  workflowId: number;
  taskType: string;
  title: string;
  dueTime: string;
  status: string;
  assignee: string | null;
  completedAt: string | null;
};
type Purchase = {
  id: number;
  workflowId: number;
  itemName: string;
  quantity: number;
  unit: string;
  unitPrice: number;
  supplierCategory: string;
  operationalCategory?: string;
  supplierName: string | null;
  note: string | null;
  orderDate: string | null;
  sourceJson: string | null;
  serviceDates: string[];
  portionsSmall: number;
  portionsLarge: number;
};
type OrderRule = { category: string; leadDays: number; coverageDays: number };
type ScheduleRule = OrderRule & {
  itemCount: number;
  serviceDates: string[];
  status: "siap" | "rencana_tidak_ada" | "estimasi_kosong" | "kategori_tidak_ada";
  message: string;
};
type LegacyImport = {
  id: number;
  unitId: string;
  fileName: string;
  sizeBytes: number;
  status: string;
  importedAt: string;
};
type Supplier = {
  id: number;
  name: string;
  category: string;
  phone: string | null;
  role: string;
  unitScope: string;
  active: number;
};
type SupplierPayment = {
  id: number;
  workflowId: number;
  supplierKey: string;
  supplierName: string;
  supplierCategory: string;
  referenceAmount: number;
  vendorAmount: number;
  dueDate: string;
  dueNote: string;
  paymentMode: string;
  status: string;
};
type DailyPayment = {
  id: number; unitId: string; serviceDate: string; recipientType: string; recipientName: string; role: string;
  rate: number; amount: number; proofNumber: string; receiptStatus: string; paymentStatus: string;
  paymentReference: string | null; note: string | null;
};
type CalculatorExport = {
  planName: string;
  serviceDate: string;
  portionsSmall: number;
  portionsLarge: number;
  items: Array<{
    itemName: string;
    quantity: number;
    unit: string;
    unitPrice: number;
    totalPrice: number;
    note: string;
    supplierTitle: string;
    operationalCategory?: string;
  }>;
  grandTotal: number;
  paguBgn: number;
  difference: number;
};
type DashboardData = {
  date: string;
  units: Unit[];
  workflows: Workflow[];
  tasks: Task[];
  purchases: Purchase[];
  imports: LegacyImport[];
  suppliers: Supplier[];
  supplierPayments: SupplierPayment[];
  dailyPayments: DailyPayment[];
  orderRules: OrderRule[];
};

const tabs = [
  ["today", "Hari Ini", "01"],
  ["purchase", "Belanja & PO", "02"],
  ["payment", "Invoice & Bank", "03"],
  ["daily-payments", "Upah & Insentif", "05"],
  ["ai", "Asisten AI", "06"],
  ["migration", "Migrasi Data", "07"],
  ["access", "Akses Tim", "08"],
  ["settings", "Pengaturan AI", "09"],
] as const;

const categoryLabels: Record<string, string> = {
  buah_sayur: "SUPPLIER SAYUR/BUMBU",
  ayam: "SUPPLIER AYAM",
  ikan: "SUPPLIER IKAN",
  tahu_tempe: "SUPPLIER TEMPE & TAHU",
  telur: "SUPPLIER TELUR",
  beras: "SUPPLIER BERAS",
  bahan_kering: "BAHAN KERING & KEMASAN",
  lainnya: "SUPPLIER LAINNYA",
};

const statusLabels: Record<string, string> = {
  pending: "Belum",
  in_progress: "Diproses",
  done: "Selesai",
  blocked: "Terkendala",
  draft: "Draf",
  final: "Final",
  closed: "Ditutup",
  belum_diminta: "Belum diminta",
  diminta: "Sudah diminta",
  diterima: "Diterima",
  selisih: "Ada selisih",
  belum_dibuat: "Belum dibuat",
  maker: "Maker selesai",
  menunggu_checker: "Menunggu checker",
  dibayar: "Dibayar",
  gagal: "Gagal",
  belum_dikirim: "Belum dikirim",
  dikirim: "Dikirim",
  sebagian: "Sebagian",
  dikonfirmasi: "Dikonfirmasi",
  paid: "Dibayar",
};

const formatMoney = (value: number) =>
  new Intl.NumberFormat("id-ID", {
    style: "currency",
    currency: "IDR",
    maximumFractionDigits: 0,
  }).format(value || 0);

const localDate = () =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Jakarta",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());

const addDateDays = (value: string, days: number) => {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
};

const formatDate = (value: string) => new Intl.DateTimeFormat("id-ID", {
  timeZone: "UTC", weekday: "short", day: "numeric", month: "short",
}).format(new Date(`${value}T00:00:00Z`));

const formatQuantity = (value: number) => new Intl.NumberFormat("id-ID", {
  maximumFractionDigits: 3,
}).format(value || 0);

function evaluateQuantityExpression(input: string) {
  const expression = String(input || "").replace(/,/g, ".").replace(/[×x]/gi, "*").replace(/÷/g, "/").replace(/\s+/g, "");
  if (!expression || expression.length > 80 || !/^[0-9.+\-*/()]+$/.test(expression)) return null;
  let index = 0;
  const parseFactor = (): number => {
    if (expression[index] === "+") { index += 1; return parseFactor(); }
    if (expression[index] === "-") { index += 1; return -parseFactor(); }
    if (expression[index] === "(") {
      index += 1;
      const value = parseExpression();
      if (expression[index] !== ")") return Number.NaN;
      index += 1;
      return value;
    }
    const start = index;
    while (index < expression.length && /[0-9.]/.test(expression[index])) index += 1;
    if (start === index) return Number.NaN;
    return Number(expression.slice(start, index));
  };
  const parseTerm = (): number => {
    let value = parseFactor();
    while (expression[index] === "*" || expression[index] === "/") {
      const operator = expression[index++];
      const operand = parseFactor();
      value = operator === "*" ? value * operand : value / operand;
    }
    return value;
  };
  const parseExpression = (): number => {
    let value = parseTerm();
    while (expression[index] === "+" || expression[index] === "-") {
      const operator = expression[index++];
      const operand = parseTerm();
      value = operator === "+" ? value + operand : value - operand;
    }
    return value;
  };
  const result = parseExpression();
  if (index !== expression.length || !Number.isFinite(result) || result < 0) return null;
  return Math.round((result + Number.EPSILON) * 1_000_000) / 1_000_000;
}

class RequestError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.name = "RequestError"; this.status = status; }
}

async function requestJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  const text = await response.text();
  let data: (T & { error?: string }) | null = null;
  try { data = text ? JSON.parse(text) as T & { error?: string } : null; }
  catch {
    if (response.status === 413 || /payload too large/i.test(text)) {
      throw new RequestError("Ukuran unggahan melewati batas hosting.", 413);
    }
    throw new RequestError(response.ok ? "Respons server tidak dapat dibaca." : text.trim().slice(0, 180) || "Permintaan gagal.", response.status);
  }
  if (!response.ok) throw new RequestError(data?.error || `Permintaan gagal (${response.status}).`, response.status);
  if (!data) throw new Error("Respons server kosong.");
  return data;
}

export default function OperationsClient({ displayName, onOpenKitchen }: { displayName?: string | null; onOpenKitchen: (unitId: "maja" | "cemplang") => void }) {
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number][0]>("today");
  const [activeUnit, setActiveUnit] = useState("maja");
  const [date, setDate] = useState(localDate());
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = async (quiet = false) => {
    if (!quiet) setLoading(true);
    setError("");
    try {
      const result = await requestJson<DashboardData>(`/api/dashboard?date=${date}`);
      setData(result);
      if (!result.units.some((unit) => unit.id === activeUnit) && result.units[0]) {
        setActiveUnit(result.units[0].id);
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Gagal memuat data.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Loading from the server is the external synchronization performed by this effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date]);

  const unit = data?.units.find((item) => item.id === activeUnit) || null;
  const workflow = data?.workflows.find((item) => item.unitId === activeUnit) || null;
  const tasks = data?.tasks.filter((item) => item.workflowId === workflow?.id) || [];
  const purchases = data?.purchases.filter((item) => item.workflowId === workflow?.id) || [];
  const supplierPayments = data?.supplierPayments.filter((item) => item.workflowId === workflow?.id) || [];
  const doneTasks = tasks.filter((task) => task.status === "done").length;
  const progress = tasks.length ? Math.round((doneTasks / tasks.length) * 100) : 0;
  const total = purchases.reduce((sum, item) => sum + item.quantity * item.unitPrice, 0);
  const allPending = data?.tasks.filter((task) => task.status !== "done").length || 0;
  const invoicePending = data?.workflows.filter((item) => item.invoiceStatus !== "diterima").length || 0;

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 3200);
  };

  const updateTask = async (task: Task) => {
    const nextStatus = task.status === "done" ? "pending" : "done";
    setData((current) => current ? {
      ...current,
      tasks: current.tasks.map((item) => item.id === task.id ? {
        ...item,
        status: nextStatus,
        completedAt: nextStatus === "done" ? new Date().toISOString() : null,
      } : item),
    } : current);
    try {
      await requestJson("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: task.id, status: nextStatus }),
      });
    } catch (taskError) {
      setData((current) => current ? {
        ...current,
        tasks: current.tasks.map((item) => item.id === task.id ? task : item),
      } : current);
      setError(taskError instanceof Error ? taskError.message : "Gagal memperbarui tugas.");
    }
  };

  const updateWorkflow = async (field: string, value: string | number) => {
    if (!workflow) return;
    const previousValue = workflow[field as keyof Workflow];
    setData((current) => current ? {
      ...current,
      workflows: current.workflows.map((item) => item.id === workflow.id ? { ...item, [field]: value } : item),
    } : current);
    setBusy(true);
    try {
      await requestJson("/api/workflows", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: workflow.id, field, value }),
      });
      showNotice("Status berhasil diperbarui.");
    } catch (workflowError) {
      setData((current) => current ? {
        ...current,
        workflows: current.workflows.map((item) => item.id === workflow.id ? { ...item, [field]: previousValue } : item),
      } : current);
      setError(workflowError instanceof Error ? workflowError.message : "Gagal memperbarui status.");
    } finally {
      setBusy(false);
    }
  };

  const replacePurchases = (workflowId: number, nextItems: Purchase[]) => {
    setData((current) => {
      if (!current) return current;
      const nextPurchases = [...current.purchases.filter((item) => item.workflowId !== workflowId), ...nextItems];
      const nextTotal = nextItems.reduce((sum, item) => sum + item.quantity * item.unitPrice, 0);
      return {
        ...current,
        purchases: nextPurchases,
        workflows: current.workflows.map((item) => item.id === workflowId ? { ...item, totalEstimate: nextTotal, status: "draft" } : item),
      };
    });
  };

  const patchPurchase = (nextItem: Purchase) => {
    setData((current) => {
      if (!current) return current;
      const nextPurchases = current.purchases.map((item) => item.id === nextItem.id ? nextItem : item);
      const nextTotal = nextPurchases.filter((item) => item.workflowId === nextItem.workflowId)
        .reduce((sum, item) => sum + item.quantity * item.unitPrice, 0);
      return {
        ...current,
        purchases: nextPurchases,
        workflows: current.workflows.map((item) => item.id === nextItem.workflowId ? { ...item, totalEstimate: nextTotal } : item),
      };
    });
  };

  const addPurchase = (nextItem: Purchase) => {
    setData((current) => {
      if (!current) return current;
      const nextPurchases = [...current.purchases.filter((item) => item.id !== nextItem.id), nextItem];
      const nextTotal = nextPurchases.filter((item) => item.workflowId === nextItem.workflowId)
        .reduce((sum, item) => sum + item.quantity * item.unitPrice, 0);
      return {
        ...current,
        purchases: nextPurchases,
        workflows: current.workflows.map((item) => item.id === nextItem.workflowId ? { ...item, totalEstimate: nextTotal } : item),
      };
    });
  };

  const removePurchase = (purchase: Purchase) => {
    setData((current) => {
      if (!current) return current;
      const nextPurchases = current.purchases.filter((item) => item.id !== purchase.id);
      const nextTotal = nextPurchases.filter((item) => item.workflowId === purchase.workflowId)
        .reduce((sum, item) => sum + item.quantity * item.unitPrice, 0);
      return {
        ...current,
        purchases: nextPurchases,
        workflows: current.workflows.map((item) => item.id === purchase.workflowId ? { ...item, totalEstimate: nextTotal } : item),
      };
    });
  };

  const patchSupplier = (nextSupplier: Supplier) => {
    setData((current) => current ? {
      ...current,
      suppliers: current.suppliers.map((item) => item.id === nextSupplier.id ? nextSupplier : item),
    } : current);
  };

  const patchOrderRule = (nextRule: OrderRule) => {
    setData((current) => current ? {
      ...current,
      orderRules: current.orderRules.map((item) => item.category === nextRule.category ? nextRule : item),
    } : current);
  };

  const updateSupplierPayment = async (nextPayment: SupplierPayment) => {
    const previous = data?.supplierPayments.find((item) => item.id === nextPayment.id);
    setData((current) => current ? {
      ...current,
      supplierPayments: current.supplierPayments.map((item) => item.id === nextPayment.id ? nextPayment : item),
    } : current);
    try {
      await requestJson("/api/supplier-payments", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: nextPayment.id,
          vendorAmount: nextPayment.vendorAmount,
          dueDate: nextPayment.dueDate,
          status: nextPayment.status,
        }),
      });
      showNotice(nextPayment.status === "paid" ? "Pembayaran supplier ditandai selesai." : "Nilai bayar vendor disimpan.");
    } catch (paymentError) {
      if (previous) {
        setData((current) => current ? {
          ...current,
          supplierPayments: current.supplierPayments.map((item) => item.id === previous.id ? previous : item),
        } : current);
      }
      setError(paymentError instanceof Error ? paymentError.message : "Gagal menyimpan pembayaran supplier.");
    }
  };

  const syncSupplierPaymentRows = async (workflowId: number) => {
    try {
      const result = await requestJson<{ payments: SupplierPayment[] }>("/api/supplier-payments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflowId }),
      });
      setData((current) => current ? {
        ...current,
        supplierPayments: [
          ...current.supplierPayments.filter((payment) => payment.workflowId !== workflowId),
          ...result.payments,
        ],
      } : current);
    } catch (syncError) {
      setError(syncError instanceof Error ? syncError.message : "Gagal menyelaraskan checklist pembayaran.");
    }
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <span className="brand-mark">SP</span>
          <div>
            <strong>Pusat Operasional</strong>
            <small>SPPG Maja & Cemplang</small>
          </div>
        </div>
        <div className="source-apps">
          <p>APLIKASI SUMBER</p>
          <button type="button" onClick={() => onOpenKitchen("maja")}><span>M</span><div><strong>Buka Aplikasi Maja</strong><small>Resep · rencana · estimasi</small></div></button>
          <button type="button" onClick={() => onOpenKitchen("cemplang")}><span>C</span><div><strong>Buka Aplikasi Cemplang</strong><small>Resep · rencana · estimasi</small></div></button>
        </div>
        <nav className="side-nav" aria-label="Navigasi utama">
          {tabs.map(([id, label, number]) => (
            <button
              key={id}
              type="button"
              className={activeTab === id ? "active" : ""}
              onClick={() => setActiveTab(id)}
            >
              <span>{number}</span>
              {label}
            </button>
          ))}
        </nav>
        <div className="sidebar-security">
          <span className="security-dot" />
          <div>
            <strong>Mode aman</strong>
            <small>Data tersimpan di server</small>
          </div>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div>
            <p className="eyebrow">OPERASIONAL HARIAN</p>
            <h1>{tabs.find(([id]) => id === activeTab)?.[1]}</h1>
          </div>
          <div className="topbar-actions">
            <label className="date-control">
              <span>Tanggal kerja / pesan</span>
              <input type="date" value={date} onChange={(event) => setDate(event.target.value)} />
            </label>
            <div className="user-chip">
              <span>{(displayName || "ZR").slice(0, 2).toUpperCase()}</span>
              <div>
                <strong>{displayName || "Owner"}</strong>
                <small>Akses pemilik</small>
              </div>
            </div>
            <a className="logout-link" href="/api/auth/logout">Ganti akun</a>
          </div>
        </header>

        <div className="unit-switch" role="tablist" aria-label="Pilih dapur">
          {(data?.units || [
            { id: "maja", name: "SPPG Maja Baru", bankChannel: "BNI Direct" },
            { id: "cemplang", name: "SPPG Cemplang 02", bankChannel: "Kopra" },
          ]).map((item) => (
            <button
              key={item.id}
              type="button"
              className={activeUnit === item.id ? "active" : ""}
              onClick={() => setActiveUnit(item.id)}
            >
              <span className="unit-initial">{item.id === "maja" ? "M" : "C"}</span>
              <span>
                <strong>{item.name}</strong>
                <small>{item.bankChannel}</small>
              </span>
            </button>
          ))}
        </div>

        {error && <div className="alert error">{error}</div>}
        {notice && <div className="toast">{notice}</div>}
        {loading ? (
          <LoadingState />
        ) : !workflow || !unit ? (
          <div className="empty-state">Data dapur belum tersedia.</div>
        ) : (
          <>
            {activeTab === "today" && (
              <TodayView
                unit={unit}
                workflow={workflow}
                tasks={tasks}
                progress={progress}
                busy={busy}
                updateTask={updateTask}
                allPending={allPending}
                invoicePending={invoicePending}
                payments={supplierPayments}
                updateSupplierPayment={updateSupplierPayment}
              />
            )}
            {activeTab === "purchase" && (
              <PurchaseView
                unit={unit}
                workflow={workflow}
                items={purchases}
                suppliers={data?.suppliers || []}
                orderRules={data?.orderRules || []}
                total={total}
                busy={busy}
                setBusy={setBusy}
                setError={setError}
                updateWorkflow={updateWorkflow}
                notify={showNotice}
                replacePurchases={replacePurchases}
                patchPurchase={patchPurchase}
                addPurchase={addPurchase}
                removePurchase={removePurchase}
                patchSupplier={patchSupplier}
                patchOrderRule={patchOrderRule}
                syncSupplierPayments={syncSupplierPaymentRows}
              />
            )}
            {activeTab === "documents" && <InvoiceDocumentsClient unit={unit} workflow={workflow} date={date} />}
            {activeTab === "payment" && (
              <PaymentView
                unit={unit}
                workflow={workflow}
                busy={busy}
                updateWorkflow={updateWorkflow}
              />
            )}
            {activeTab === "daily-payments" && (
              <DailyPaymentsView
                unit={unit}
                date={date}
                payments={(data?.dailyPayments || []).filter((item) => item.unitId === activeUnit)}
                reload={() => load(true)}
                notify={showNotice}
              />
            )}
            {activeTab === "ai" && (
              <AiView unit={unit} workflow={workflow} items={purchases} />
            )}
            {activeTab === "migration" && (
              <MigrationView
                imports={data?.imports || []}
                reload={() => load(true)}
              />
            )}
            {activeTab === "access" && <AccessView />}
            {activeTab === "settings" && <AiSettingsView />}
          </>
        )}
      </main>
    </div>
  );
}

function TodayView({
  unit,
  workflow,
  tasks,
  progress,
  busy,
  updateTask,
  allPending,
  invoicePending,
  payments,
  updateSupplierPayment,
}: {
  unit: Unit;
  workflow: Workflow;
  tasks: Task[];
  progress: number;
  busy: boolean;
  updateTask: (task: Task) => Promise<void>;
  allPending: number;
  invoicePending: number;
  payments: SupplierPayment[];
  updateSupplierPayment: (payment: SupplierPayment) => Promise<void>;
}) {
  const pendingPayments = payments.filter((payment) => payment.status !== "paid").length;
  return (
    <>
      <section className="metric-grid">
        <article className="metric-card primary">
          <p>Progres {unit.name}</p>
          <strong>{progress}%</strong>
          <div className="mini-progress"><span style={{ width: `${progress}%` }} /></div>
          <small>{tasks.filter((task) => task.status === "done").length} dari {tasks.length} tugas selesai</small>
        </article>
        <article className="metric-card">
          <p>Nilai Invoice Kalkulator</p>
          <strong>{formatMoney(workflow.calculatorInvoiceTotal)}</strong>
          <small>Harga estimasi termasuk margin</small>
        </article>
        <article className="metric-card warning">
          <p>Perlu perhatian</p>
          <strong>{allPending + invoicePending + pendingPayments}</strong>
          <small>{allPending} tugas · {invoicePending} invoice · {pendingPayments} supplier</small>
        </article>
        <article className="metric-card dark">
          <p>Kanal pembayaran</p>
          <strong>{unit.bankChannel}</strong>
          <small>{statusLabels[workflow.paymentStatus]}</small>
        </article>
      </section>

      <section className="content-grid">
        <article className="panel task-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">CHECKLIST TERKENDALI</p>
              <h2>Urutan kerja hari ini</h2>
            </div>
            <span className="date-badge">WIB</span>
          </div>
          <div className="task-list">
            {tasks.map((task) => (
              <button
                type="button"
                key={task.id}
                className={`task-row ${task.status === "done" ? "done" : ""}`}
                onClick={() => void updateTask(task)}
                disabled={busy}
              >
                <span className="task-check">{task.status === "done" ? "✓" : ""}</span>
                <span className="task-time">{task.dueTime}</span>
                <span className="task-title">
                  <strong>{task.title}</strong>
                  <small>{task.status === "done" ? "Sudah dicatat" : "Ketuk setelah selesai"}</small>
                </span>
                <span className={`status-pill ${task.status}`}>{statusLabels[task.status]}</span>
              </button>
            ))}
          </div>
        </article>

        <aside className="panel control-panel">
          <div className="panel-heading compact">
            <div>
              <p className="eyebrow">KONTROL PROSES</p>
              <h2>Status utama</h2>
            </div>
          </div>
          <StatusLine label="Invoice akuntan" value={workflow.invoiceStatus} />
          <StatusLine label={`Maker ${unit.bankChannel}`} value={workflow.paymentStatus} />
          <StatusLine label="Pesanan supplier" value={workflow.supplierStatus} />
          <StatusLine label="Bahan kering koperasi" value={workflow.dryGoodsStatus} />
          <div className="callout">
            <strong>Urutan aman</strong>
            <p>Finalkan PO → unduh Excel kalkulator → terima invoice → lakukan maker.</p>
          </div>
        </aside>
      </section>

      <section className="panel supplier-payment-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">PEMBAYARAN SUPPLIER BERDASARKAN PO</p>
            <h2>Checklist Nilai Bayar Vendor</h2>
            <p className="payment-helper">Nilai acuan PO memakai harga estimasi yang sudah termasuk margin. Ubah <strong>Nilai Bayar Vendor</strong> menjadi harga modal aktual sebelum ditandai dibayar.</p>
          </div>
          <span className="date-badge">{pendingPayments} BELUM</span>
        </div>
        <div className="supplier-payment-list">
          {payments.map((payment) => (
            <SupplierPaymentRow key={payment.id} payment={payment} onSave={updateSupplierPayment} />
          ))}
          {!payments.length && <div className="table-empty">Belum ada PO. Tarik dan finalkan PO terlebih dahulu.</div>}
        </div>
      </section>
    </>
  );
}

function SupplierPaymentRow({ payment, onSave }: { payment: SupplierPayment; onSave: (payment: SupplierPayment) => Promise<void> }) {
  const [vendorAmount, setVendorAmount] = useState(String(payment.vendorAmount || ""));
  const [dueDate, setDueDate] = useState(payment.dueDate);
  const [saving, setSaving] = useState(false);
  const nextPayment = (status = payment.status): SupplierPayment => ({
    ...payment,
    vendorAmount: Math.max(0, Math.round(Number(vendorAmount || 0))),
    dueDate,
    status,
  });
  const save = async (status = payment.status) => {
    setSaving(true);
    await onSave(nextPayment(status));
    setSaving(false);
  };
  return (
    <article className={`supplier-payment-row ${payment.status === "paid" ? "paid" : ""}`}>
      <button className="payment-check" type="button" onClick={() => void save(payment.status === "paid" ? "pending" : "paid")} disabled={saving} aria-label={`Tandai pembayaran ${payment.supplierName}`}>
        {payment.status === "paid" ? "✓" : ""}
      </button>
      <div className="payment-supplier">
        <strong>{payment.supplierName}</strong>
        <small>{categoryLabels[payment.supplierCategory] || payment.supplierCategory}</small>
        {payment.paymentMode === "internal_transfer" && <span>TRANSFER INTERNAL</span>}
      </div>
      <div className="payment-reference"><small>Nilai Acuan PO (termasuk margin)</small><strong>{formatMoney(payment.referenceAmount)}</strong></div>
      <label>Nilai Bayar Vendor (harga modal)<input type="number" min="0" value={vendorAmount} onChange={(event) => setVendorAmount(event.target.value)} /></label>
      <label>Jadwal Bayar<input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} /><small>{payment.dueNote}</small></label>
      <div className="payment-margin"><small>Margin / selisih</small><strong>{formatMoney(payment.referenceAmount - Number(vendorAmount || 0))}</strong></div>
      <button className="button ghost" type="button" onClick={() => void save()} disabled={saving}>{saving ? "Menyimpan…" : "Simpan"}</button>
    </article>
  );
}

function StatusLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="status-line">
      <span>{label}</span>
      <strong>{statusLabels[value] || value}</strong>
    </div>
  );
}

function PurchaseView({
  unit,
  workflow,
  items,
  suppliers,
  orderRules,
  total,
  busy,
  setBusy,
  setError,
  updateWorkflow,
  notify,
  replacePurchases,
  patchPurchase,
  addPurchase,
  removePurchase,
  patchSupplier,
  patchOrderRule,
  syncSupplierPayments,
}: {
  unit: Unit;
  workflow: Workflow;
  items: Purchase[];
  suppliers: Supplier[];
  orderRules: OrderRule[];
  total: number;
  busy: boolean;
  setBusy: (value: boolean) => void;
  setError: (value: string) => void;
  updateWorkflow: (field: string, value: string | number) => Promise<void>;
  notify: (message: string) => void;
  replacePurchases: (workflowId: number, items: Purchase[]) => void;
  patchPurchase: (item: Purchase) => void;
  addPurchase: (item: Purchase) => void;
  removePurchase: (item: Purchase) => void;
  patchSupplier: (supplier: Supplier) => void;
  patchOrderRule: (rule: OrderRule) => void;
  syncSupplierPayments: (workflowId: number) => Promise<void>;
}) {
  const [form, setForm] = useState({
    itemName: "",
    quantity: "",
    unit: "kg",
    unitPrice: "",
    supplierCategory: "buah_sayur",
    operationalCategory: "lain_lain",
    supplierName: "",
  });
  const [drafts, setDrafts] = useState<Record<number, { quantity: string; unit: string; unitPrice: string; supplierId: string; operationalCategory: string; note: string }>>({});
  const [phones, setPhones] = useState<Record<number, string>>({});
  const [savingIds, setSavingIds] = useState<number[]>([]);
  const [adding, setAdding] = useState(false);
  const [scheduleBusy, setScheduleBusy] = useState(false);
  const [accountantExporting, setAccountantExporting] = useState(false);
  const [scheduleResults, setScheduleResults] = useState<Record<string, ScheduleRule>>({});
  const [ruleDrafts, setRuleDrafts] = useState<Record<string, { leadDays: string; coverageDays: string }>>({});
  const baseDraft = (item: Purchase) => {
    const selected = suppliers.find((supplier) => supplier.role === "supplier" && supplier.name === item.supplierName)
      || suppliers.find((supplier) => supplier.role === "supplier" && supplier.category === item.supplierCategory);
    return {
      quantity: String(item.quantity), unit: item.unit, unitPrice: String(item.unitPrice),
      supplierId: selected ? String(selected.id) : "", operationalCategory: item.operationalCategory || operationalCategoryFromNote(item.note), note: item.note || "",
    };
  };
  const editDraft = (item: Purchase, change: Partial<ReturnType<typeof baseDraft>>) => {
    setDrafts((current) => ({ ...current, [item.id]: { ...(current[item.id] || baseDraft(item)), ...change } }));
  };

  const addItem = async (event: FormEvent) => {
    event.preventDefault();
    const temporary: Purchase = {
      id: -Date.now(),
      workflowId: workflow.id,
      itemName: form.itemName.trim(),
      quantity: Number(form.quantity),
      unit: form.unit,
      unitPrice: Number(form.unitPrice || 0),
      supplierCategory: form.supplierCategory,
      supplierName: form.supplierName.trim() || null,
      operationalCategory: form.operationalCategory,
      note: null,
      orderDate: null,
      sourceJson: null,
      serviceDates: [],
      portionsSmall: 0,
      portionsLarge: 0,
    };
    addPurchase(temporary);
    setAdding(true);
    setError("");
    try {
      const result = await requestJson<{ item: Purchase }>("/api/purchases", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workflowId: workflow.id,
          ...form,
          quantity: Number(form.quantity),
          unitPrice: Number(form.unitPrice || 0),
        }),
      });
      removePurchase(temporary);
      addPurchase(result.item);
      void syncSupplierPayments(workflow.id);
      setForm((current) => ({ ...current, itemName: "", quantity: "", unitPrice: "" }));
      notify("Item belanja ditambahkan.");
    } catch (addError) {
      removePurchase(temporary);
      setError(addError instanceof Error ? addError.message : "Gagal menambah item.");
    } finally {
      setAdding(false);
    }
  };

  const deleteItem = async (item: Purchase) => {
    removePurchase(item);
    setSavingIds((current) => [...current, item.id]);
    try {
      await requestJson(`/api/purchases?id=${item.id}&workflowId=${item.workflowId}`, { method: "DELETE" });
      void syncSupplierPayments(workflow.id);
      notify(`${item.itemName} dihapus.`);
    } catch (deleteError) {
      addPurchase(item);
      setError(deleteError instanceof Error ? deleteError.message : "Gagal menghapus item.");
    } finally {
      setSavingIds((current) => current.filter((id) => id !== item.id));
    }
  };

  const pullFromKitchen = async () => {
    const approved = window.confirm(`Tarik ulang estimasi ${unit.name} tanggal ${workflow.serviceDate}?\n\nDraft PO di Pusat Kontrol akan diganti. Data di aplikasi kalkulator tidak berubah.`);
    if (!approved) return;
    setBusy(true); setError("");
    try {
      const result = await requestJson<{ items: Purchase[]; count: number }>("/api/pull-estimate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ unitId: unit.id, serviceDate: workflow.serviceDate }),
      });
      replacePurchases(workflow.id, result.items);
      void syncSupplierPayments(workflow.id);
      setDrafts({});
      notify(`${result.count} item ditarik. Silakan sesuaikan jumlah dan supplier di Pusat Kontrol.`);
    } catch (pullError) {
      setError(pullError instanceof Error ? pullError.message : "Gagal menarik estimasi dapur.");
    } finally { setBusy(false); }
  };

  const saveItem = async (item: Purchase, draftOverride?: ReturnType<typeof baseDraft>, returnOnFailure = false) => {
    const draft = draftOverride || drafts[item.id] || baseDraft(item);
    const calculatedQuantity = evaluateQuantityExpression(draft.quantity);
    if (calculatedQuantity === null) {
      setError("Rumus Qty tidak valid. Tekan Enter setelah mengetik, misalnya 987/2.");
      return;
    }
    const selected = suppliers.find((supplier) => supplier.id === Number(draft.supplierId));
    const updated: Purchase = {
      ...item,
      quantity: calculatedQuantity,
      unit: draft.unit,
      unitPrice: Number(draft.unitPrice || 0),
      supplierCategory: selected?.category || item.supplierCategory,
      operationalCategory: draft.operationalCategory || item.operationalCategory || operationalCategoryFromNote(item.note),
      supplierName: selected?.name || item.supplierName || "",
      note: draft.note,
    };
    patchPurchase(updated);
    const supplierChanged = updated.supplierCategory !== item.supplierCategory || updated.supplierName !== item.supplierName;
    setDrafts((current) => {
      const next = { ...current };
      delete next[item.id];
      return next;
    });
    setSavingIds((current) => [...current, item.id]);
    setError("");
    try {
      const result = await requestJson<{ syncedPlans: number }>("/api/purchases", {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: item.id,
          workflowId: item.workflowId,
          quantity: updated.quantity,
          unit: updated.unit,
          unitPrice: updated.unitPrice,
          supplierCategory: updated.supplierCategory,
          supplierName: updated.supplierName,
          note: operationalNote(updated.operationalCategory || "lain_lain", updated.note),
          operationalCategory: updated.operationalCategory,
          unitId: unit.id,
          sourceItemName: item.itemName,
          sourceUnit: item.unit,
          serviceDates: item.serviceDates,
          syncSupplier: supplierChanged,
        }),
      });
      if (supplierChanged) {
        notify(result.syncedPlans > 0
          ? `${item.itemName} disimpan; supplier juga diperbarui di kalkulator dapur.`
          : `${item.itemName} disimpan. Supplier sumber belum dapat ditemukan di kalkulator.`);
      } else {
        notify(`${item.itemName} disimpan di Pusat Kontrol; Qty kalkulator dapur tetap.`);
      }
      void syncSupplierPayments(workflow.id);
    } catch (saveError) {
      patchPurchase(item);
      setDrafts((current) => {
        if (!returnOnFailure) return { ...current, [item.id]: draft };
        const next = { ...current };
        delete next[item.id];
        return next;
      });
      setError(saveError instanceof Error ? saveError.message : "Gagal menyimpan perubahan item.");
    } finally { setSavingIds((current) => current.filter((id) => id !== item.id)); }
  };

  const saveContact = async (supplier: Supplier) => {
    const nextSupplier = { ...supplier, phone: phones[supplier.id] ?? supplier.phone ?? "" };
    patchSupplier(nextSupplier);
    setSavingIds((current) => [...current, -supplier.id]);
    setError("");
    try {
      await requestJson("/api/suppliers", {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: supplier.id, name: supplier.name, category: supplier.category, phone: nextSupplier.phone }),
      });
      notify(`Nomor WhatsApp ${supplier.name} disimpan.`);
    } catch (contactError) {
      patchSupplier(supplier);
      setError(contactError instanceof Error ? contactError.message : "Gagal menyimpan nomor WhatsApp.");
    } finally { setSavingIds((current) => current.filter((id) => id !== -supplier.id)); }
  };

  const pullOrderSchedule = async () => {
    const approved = window.confirm(`Susun pesanan ${unit.name} untuk tanggal kerja ${workflow.serviceDate}?\n\nSayur, bahan kering/protein, dan ayam akan ditarik sesuai aturan H dan mengganti draft PO tanggal kerja ini. Data kalkulator tidak berubah.`);
    if (!approved) return;
    setScheduleBusy(true); setError("");
    try {
      const effectiveRules = orderRules.map((rule) => ({
        category: rule.category,
        leadDays: Math.max(0, Math.round(Number(ruleDrafts[rule.category]?.leadDays ?? rule.leadDays))),
        coverageDays: Math.max(1, Math.round(Number(ruleDrafts[rule.category]?.coverageDays ?? rule.coverageDays))),
      }));
      const result = await requestJson<{ items: Purchase[]; schedule: ScheduleRule[]; replaced: boolean; warning?: string }>("/api/order-schedule", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ unitId: unit.id, orderDate: workflow.serviceDate, rules: effectiveRules }),
      });
      setScheduleResults(Object.fromEntries(result.schedule.map((rule) => [rule.category, rule])));
      if (!result.replaced) {
        notify(result.warning || "Belum ada item yang dapat ditarik.");
        return;
      }
      replacePurchases(workflow.id, result.items);
      void syncSupplierPayments(workflow.id);
      setDrafts({});
      const covered = result.schedule.filter((rule) => rule.itemCount > 0).length;
      const chicken = result.schedule.find((rule) => rule.category === "ayam");
      if (chicken && chicken.itemCount === 0) {
        setError(`Ayam belum masuk untuk ${chicken.serviceDates.map(formatDate).join(" dan ")}: ${chicken.message}.`);
      } else {
        notify(`${result.items.length} item dari ${covered} kelompok jadwal sudah ditarik${chicken ? `; ayam ${chicken.itemCount} item untuk ${chicken.serviceDates.map(formatDate).join(" dan ")}` : ""}.`);
      }
    } catch (scheduleError) {
      setError(scheduleError instanceof Error ? scheduleError.message : "Gagal menyusun jadwal pesanan.");
    } finally { setScheduleBusy(false); }
  };

  const saveOrderRule = async (rule: OrderRule) => {
    const draft = ruleDrafts[rule.category];
    const nextRule = {
      category: rule.category,
      leadDays: Math.max(0, Math.round(Number(draft?.leadDays ?? rule.leadDays))),
      coverageDays: Math.max(1, Math.round(Number(draft?.coverageDays ?? rule.coverageDays))),
    };
    patchOrderRule(nextRule);
    setSavingIds((current) => [...current, -1000 - orderRules.findIndex((item) => item.category === rule.category)]);
    try {
      await requestJson("/api/order-rules", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextRule),
      });
      notify(`Aturan ${categoryLabels[rule.category]} disimpan.`);
    } catch (ruleError) {
      patchOrderRule(rule);
      setError(ruleError instanceof Error ? ruleError.message : "Gagal menyimpan aturan pemesanan.");
    } finally {
      setSavingIds((current) => current.filter((id) => id !== -1000 - orderRules.findIndex((item) => item.category === rule.category)));
    }
  };

  const grouped = useMemo(() => {
    const result: Record<string, Purchase[]> = {};
    items.forEach((item) => {
      (result[item.supplierName || item.supplierCategory] ||= []).push(item);
    });
    return result;
  }, [items]);

  const supplierTableGroups = useMemo(() => {
    const groups = new Map<string, { key: string; name: string; category: string; items: Purchase[] }>();
    items.forEach((item) => {
      const draft = drafts[item.id];
      const selected = suppliers.find((supplier) => supplier.role === "supplier" && supplier.id === Number(draft?.supplierId));
      const name = selected?.name || item.supplierName || categoryLabels[item.supplierCategory] || item.supplierCategory;
      const category = selected?.category || item.supplierCategory;
      const key = selected ? `supplier-${selected.id}` : `supplier-${name}`;
      const group = groups.get(key) || { key, name, category, items: [] };
      group.items.push(item);
      groups.set(key, group);
    });
    return [...groups.values()]
      .map((group) => ({ ...group, items: group.items.sort((a, b) => a.itemName.localeCompare(b.itemName, "id")) }))
      .sort((a, b) => a.name.localeCompare(b.name, "id"));
  }, [drafts, items, suppliers]);

  const exportPoExcel = () => {
    const rows: Array<Array<string | number>> = [
      ["Item", "Jumlah", "Kategori Operasional", "Satuan", "Harga Satuan (Estimasi)", "Total Harga (Estimasi)", "Catatan", "Kategori / Supplier"],
      ...[...items].sort((a, b) => (a.supplierName || categoryLabels[a.supplierCategory]).localeCompare(b.supplierName || categoryLabels[b.supplierCategory], "id") || a.itemName.localeCompare(b.itemName, "id")).map((item) => [
        item.itemName,
        item.quantity,
        operationalCategoryLabels[item.operationalCategory || operationalCategoryFromNote(item.note)] || "Lain-lain",
        item.unit,
        item.unitPrice,
        item.quantity * item.unitPrice,
        item.note || "",
        item.supplierName || categoryLabels[item.supplierCategory] || item.supplierCategory,
      ]),
      [],
      ["GRAND TOTAL", "", "", "", "", total, "", ""],
    ];
    downloadXlsx(`PO_pusat_${unit.id}_${workflow.serviceDate}.xlsx`, "PO Pusat", rows, {
      widths: [34, 38, 13, 12, 22, 22, 48, 28],
      decimalColumns: [1],
      currencyColumns: [4, 5],
      totalRow: rows.length,
    });
    notify("File PO pusat berhasil dibuat.");
  };

  const exportCalculatorInvoice = async () => {
    setAccountantExporting(true);
    setError("");
    try {
      const calculator = await requestJson<CalculatorExport>(`/api/accountant-export?unitId=${unit.id}&serviceDate=${workflow.serviceDate}`);
      const rows: Array<Array<string | number>> = [
      ["Item", "Jumlah", "Kategori Operasional", "Satuan", "Harga Satuan (Estimasi)", "Total Harga (Estimasi)", "Catatan", "Kategori / Supplier"],
        ...calculator.items.map((item) => [
          item.itemName,
          item.quantity,
          operationalCategoryLabels[item.operationalCategory || "lain_lain"] || "Lain-lain",
          item.unit,
          item.unitPrice,
          item.totalPrice,
          item.note,
          item.supplierTitle,
        ]),
        [],
        ["GRAND TOTAL", "", "", "", "", calculator.grandTotal, "", ""],
        ["PAGU BGN", "", "", "", "", calculator.paguBgn, "", ""],
        ["SELISIH PAGU - ESTIMASI", "", "", "", "", calculator.difference, "", ""],
      ];
      downloadXlsx(`daftar_belanja_${calculator.serviceDate}.xlsx`, "Belanja", rows, {
        widths: [34, 38, 13, 12, 24, 24, 48, 30],
        decimalColumns: [1],
        currencyColumns: [4, 5],
        summaryRows: [rows.length - 2, rows.length - 1, rows.length],
      });
      notify(`Excel akuntan diambil langsung dari kalkulator ${unit.name}.`);
      return calculator;
    } catch (exportError) {
      setError(exportError instanceof Error ? exportError.message : "Gagal membuat Excel kalkulator.");
      return null;
    } finally {
      setAccountantExporting(false);
    }
  };

  const waNumber = (value: string) => {
    const digits = String(value || "").replace(/\D/g, "");
    return digits.startsWith("0") ? `62${digits.slice(1)}` : digits;
  };

  const openSupplierWhatsApp = (supplierName: string, supplierItems: Purchase[], phone: string) => {
    const lines = supplierItems.map((item, index) => `${index + 1}. ${item.itemName} — ${formatQuantity(item.quantity)} ${item.unit}${item.serviceDates.length ? ` (untuk masak ${item.serviceDates.map(formatDate).join(" & ")})` : item.note ? ` (${item.note})` : ""}`);
    const message = `*PESANAN ${unit.name.toUpperCase()}*\nSupplier: ${supplierName}\nTanggal pesan: ${formatDate(workflow.serviceDate)}\n\n${lines.join("\n")}\n\nMohon konfirmasi ketersediaan dan jadwal pengiriman. Terima kasih.`;
    window.open(`https://wa.me/${waNumber(phone)}?text=${encodeURIComponent(message)}`, "_blank", "noopener,noreferrer");
  };

  const accountant = suppliers.find((supplier) => supplier.role === "accountant");
  const orderedRules = [...orderRules].sort((a, b) => {
    const order = ["bahan_kering", "buah_sayur", "ayam", "tahu_tempe", "telur", "ikan", "beras", "lainnya"];
    return order.indexOf(a.category) - order.indexOf(b.category);
  });
  const draftTotal = items.reduce((sum, item) => {
    const draft = drafts[item.id];
    return sum + Number(draft?.quantity ?? item.quantity) * Number(draft?.unitPrice ?? item.unitPrice);
  }, 0);
  const editRuleDraft = (rule: OrderRule, field: "leadDays" | "coverageDays", value: string) => {
    setRuleDrafts((current) => ({
      ...current,
      [rule.category]: {
        leadDays: current[rule.category]?.leadDays ?? String(rule.leadDays),
        coverageDays: current[rule.category]?.coverageDays ?? String(rule.coverageDays),
        [field]: value,
      },
    }));
  };
  const exportAndOpenAccountant = async () => {
    const phone = accountant ? phones[accountant.id] ?? accountant.phone ?? "" : "";
    const calculator = await exportCalculatorInvoice();
    if (!calculator || !accountant || !waNumber(phone)) return;
    const message = `Nilai invoice/tagihan ${unit.name} untuk distribusi ${workflow.serviceDate} sebesar ${formatMoney(calculator.grandTotal)} sudah diambil langsung dari kalkulator. File Excel baru saja diunduh; mohon dibuatkan invoice untuk proses maker.`;
    window.open(`https://wa.me/${waNumber(phone)}?text=${encodeURIComponent(message)}`, "_blank", "noopener,noreferrer");
  };

  return (
    <>
    <section className="purchase-layout">
      <article className="panel order-schedule-panel">
        <div className="panel-heading order-schedule-heading">
          <div>
            <p className="eyebrow">JADWAL PESAN OTOMATIS</p>
            <h2>Pesanan untuk {formatDate(workflow.serviceDate)}</h2>
            <p className="schedule-explanation">Bahan ditarik dari tanggal masak sesuai jeda masing-masing supplier. Ayam dapat dijumlahkan untuk beberapa hari masak dalam satu pesanan.</p>
          </div>
          <button className="button primary schedule-pull-button" type="button" onClick={() => void pullOrderSchedule()} disabled={scheduleBusy || busy}>
            {scheduleBusy ? "Menyusun pesanan…" : "Tarik Pesanan Sesuai Jadwal"}
          </button>
        </div>
        <div className="order-rule-grid">
          {orderedRules.map((rule) => {
            const draft = ruleDrafts[rule.category];
            const leadDays = Math.max(0, Number(draft?.leadDays ?? rule.leadDays));
            const coverageDays = Math.max(1, Number(draft?.coverageDays ?? rule.coverageDays));
            const firstDate = addDateDays(workflow.serviceDate, leadDays);
            const lastDate = addDateDays(workflow.serviceDate, leadDays + coverageDays - 1);
            const saveKey = -1000 - orderRules.findIndex((item) => item.category === rule.category);
            const scheduleResult = scheduleResults[rule.category];
            return (
              <div className={`order-rule-card ${rule.category === "ayam" ? "featured" : ""}`} key={rule.category}>
                <div><strong>{categoryLabels[rule.category]}</strong><small>Masak {formatDate(firstDate)}{lastDate !== firstDate ? ` – ${formatDate(lastDate)}` : ""}</small>{scheduleResult && <span className={`schedule-rule-status ${scheduleResult.status}`}>{scheduleResult.message}</span>}</div>
                <div className="rule-inputs">
                  <label>Pesan H−<input type="number" min="0" max="14" value={draft?.leadDays ?? rule.leadDays} onChange={(event) => editRuleDraft(rule, "leadDays", event.target.value)} /></label>
                  <label>Gabung<input type="number" min="1" max="7" value={draft?.coverageDays ?? rule.coverageDays} onChange={(event) => editRuleDraft(rule, "coverageDays", event.target.value)} /><span>hari</span></label>
                  <button type="button" className="button ghost compact-button" onClick={() => void saveOrderRule(rule)} disabled={savingIds.includes(saveKey)}>{savingIds.includes(saveKey) ? "…" : "Simpan"}</button>
                </div>
              </div>
            );
          })}
        </div>
        <div className="schedule-example"><strong>Contoh Senin:</strong> bahan kering/protein untuk Selasa · sayur untuk Rabu · ayam untuk Kamis dan Jumat.</div>
      </article>

      <article className="panel purchase-table-panel">
        <div className="panel-heading purchase-heading">
          <div>
            <p className="eyebrow">DRAF PO PUSAT KONTROL</p>
            <h2>Daftar belanja {unit.name}</h2>
            <p className="purchase-subtitle">Qty dapat dihitung langsung: ketik misalnya <strong>987/2</strong>, lalu tekan Enter. Perubahan Qty tidak mengubah kalkulator dapur; perubahan supplier akan disinkronkan.</p>
          </div>
          <div className="button-row">
            <button className="button ghost" type="button" onClick={() => void pullFromKitchen()} disabled={busy}>Tarik 1 Tanggal Saja (Manual)</button>
            <button className="button ghost" type="button" onClick={exportPoExcel} disabled={!items.length}>Unduh Excel PO Pusat</button>
            <button
              className="button primary"
              type="button"
              onClick={() => void updateWorkflow("status", workflow.status === "final" ? "draft" : "final")}
              disabled={busy || !items.length}
            >
              {workflow.status === "final" ? "Buka kembali PO" : "Finalkan PO"}
            </button>
          </div>
        </div>
        <div className="schedule-action-note"><strong>Pesanan terjadwal:</strong> gunakan tombol biru “Tarik Pesanan Sesuai Jadwal” di atas. Tombol manual hanya mengambil satu tanggal yang sedang dipilih.</div>
        <div className="supplier-table-stack">
          {!items.length && <div className="empty-state compact">Belum ada item. Gunakan “Tarik Pesanan Sesuai Jadwal”, atau tarik manual untuk satu tanggal.</div>}
          {supplierTableGroups.map((group) => {
            const groupTotal = group.items.reduce((sum, item) => sum + Number(drafts[item.id]?.quantity ?? item.quantity) * Number(drafts[item.id]?.unitPrice ?? item.unitPrice), 0);
            return <section className="supplier-table-section" key={group.key}>
              <header className="supplier-table-header"><div><span>KELOMPOK SUPPLIER</span><h3>{group.name}</h3><small>{categoryLabels[group.category] || group.category}</small></div><div><strong>{group.items.length} item</strong><small>Subtotal {formatMoney(groupTotal)}</small></div></header>
              <div className="table-wrap"><table>
                <thead><tr><th>Item / Kategori Operasional</th><th>Tanggal Masak & Porsi</th><th>Jumlah</th><th>Satuan</th><th>Harga/Satuan</th><th>Supplier</th><th>Total</th><th>Aksi</th></tr></thead>
                <tbody>{group.items.map((item) => (
                  <tr key={item.id}>
                    <td><strong>{item.itemName}</strong><small>{categoryLabels[item.supplierCategory]}</small><select value={drafts[item.id]?.operationalCategory ?? item.operationalCategory ?? operationalCategoryFromNote(item.note)} onChange={(event) => editDraft(item, { operationalCategory: event.target.value })}><option value="">Pilih kategori operasional</option>{operationalCategories.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></td>
                    <td><div className="portion-cell"><strong>{item.serviceDates.length ? item.serviceDates.map(formatDate).join(" · ") : formatDate(workflow.serviceDate)}</strong><small>Kecil {item.portionsSmall.toLocaleString("id-ID")} · Besar {item.portionsLarge.toLocaleString("id-ID")} · Total {(item.portionsSmall + item.portionsLarge).toLocaleString("id-ID")}</small></div></td>
                    <td><div className="quantity-control"><input className="table-number-input" type="text" inputMode="decimal" value={drafts[item.id]?.quantity ?? item.quantity} onChange={(event) => editDraft(item, { quantity: event.target.value })} onKeyDown={(event) => {
                      if (event.key !== "Enter") return;
                      event.preventDefault();
                      const result = evaluateQuantityExpression(event.currentTarget.value);
                      if (result === null) {
                        setError("Rumus Qty tidak valid. Contoh yang benar: 987/2 atau (500+250)/3.");
                        return;
                      }
                      setError("");
                      editDraft(item, { quantity: String(result) });
                    }} aria-label={`Qty ${item.itemName}; dapat menghitung rumus dengan Enter`} /></div></td>
                    <td><input className="table-unit-input" value={drafts[item.id]?.unit ?? item.unit} onChange={(event) => editDraft(item, { unit: event.target.value })} /></td>
                    <td><input className="table-price-input" type="number" min="0" value={drafts[item.id]?.unitPrice ?? item.unitPrice} onChange={(event) => editDraft(item, { unitPrice: event.target.value })} /></td>
                    <td><select className="table-supplier-select" value={drafts[item.id]?.supplierId ?? baseDraft(item).supplierId} disabled={savingIds.includes(item.id)} onChange={(event) => {
                      const nextDraft = { ...(drafts[item.id] || baseDraft(item)), supplierId: event.target.value };
                      editDraft(item, { supplierId: event.target.value });
                      void saveItem(item, nextDraft, true);
                    }}>{suppliers.filter((supplier) => supplier.role === "supplier").map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}</select></td>
                    <td><strong>{formatMoney(Number(drafts[item.id]?.quantity ?? item.quantity) * Number(drafts[item.id]?.unitPrice ?? item.unitPrice))}</strong></td>
                    <td><div className="row-actions"><button type="button" className="button primary compact-button" onClick={() => void saveItem(item)} disabled={savingIds.includes(item.id)}>{savingIds.includes(item.id) ? "Menyimpan…" : "Simpan"}</button><button type="button" className="icon-button" onClick={() => void deleteItem(item)} disabled={savingIds.includes(item.id)} aria-label={`Hapus ${item.itemName}`}>×</button></div></td>
                  </tr>
                ))}</tbody>
              </table></div>
            </section>;
          })}
          {!!items.length && <div className="supplier-grand-total"><span>GRAND TOTAL SEMUA SUPPLIER</span><strong>{formatMoney(draftTotal)}</strong></div>}
        </div>
      </article>

      <aside className="panel form-panel">
        <div className="panel-heading compact"><div><p className="eyebrow">TAMBAH ITEM</p><h2>Input estimasi</h2></div></div>
        <form onSubmit={addItem} className="stack-form">
          <label>Nama barang<input value={form.itemName} onChange={(event) => setForm({ ...form, itemName: event.target.value })} placeholder="Contoh: Wortel" required /></label>
          <div className="form-grid two">
            <label>Jumlah<input type="number" min="0.01" step="0.01" value={form.quantity} onChange={(event) => setForm({ ...form, quantity: event.target.value })} required /></label>
            <label>Satuan<select value={form.unit} onChange={(event) => setForm({ ...form, unit: event.target.value })}><option>kg</option><option>liter</option><option>pcs</option><option>papan</option><option>ikat</option><option>dus</option><option>pack</option></select></label>
          </div>
          <label>Harga satuan<input type="number" min="0" value={form.unitPrice} onChange={(event) => setForm({ ...form, unitPrice: event.target.value })} placeholder="Rp" /></label>
          <label>Kategori operasional<select value={form.operationalCategory} onChange={(event) => setForm({ ...form, operationalCategory: event.target.value })}>{operationalCategories.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          <label>Nama supplier<input value={form.supplierName} onChange={(event) => setForm({ ...form, supplierName: event.target.value })} placeholder="Opsional" /></label>
          <button className="button primary wide" type="submit" disabled={adding}>{adding ? "Menyimpan…" : "Tambahkan item"}</button>
        </form>
      </aside>

      <article className="panel supplier-wa-panel">
        <div className="panel-heading"><div><p className="eyebrow">WHATSAPP TERPISAH</p><h2>Kirim ke masing-masing supplier</h2></div></div>
        <div className="supplier-share-grid">
          {Object.entries(grouped).map(([supplierName, supplierItems]) => {
            const contact = suppliers.find((supplier) => supplier.role === "supplier" && supplier.name === supplierName)
              || suppliers.find((supplier) => supplier.role === "supplier" && supplier.category === supplierItems[0]?.supplierCategory);
            const phone = contact ? phones[contact.id] ?? contact.phone ?? "" : "";
            return <div className="supplier-share-card" key={supplierName}><div><strong>{contact?.name || supplierName}</strong><small>{supplierItems.length} item · {categoryLabels[supplierItems[0]?.supplierCategory]}</small></div>{contact && <div className="supplier-contact-row"><input value={phone} onChange={(event) => setPhones((current) => ({ ...current, [contact.id]: event.target.value }))} placeholder="Nomor WA, contoh 0812…" /><button type="button" className="button ghost" onClick={() => void saveContact(contact)} disabled={savingIds.includes(-contact.id)}>{savingIds.includes(-contact.id) ? "…" : "Simpan No."}</button></div>}<button type="button" className="button secondary wide" disabled={!contact || !waNumber(phone)} onClick={() => openSupplierWhatsApp(contact?.name || supplierName, supplierItems, phone)}>Buka WhatsApp Supplier Ini</button></div>;
          })}
          {!items.length && <div className="empty-state compact">Tarik estimasi terlebih dahulu.</div>}
        </div>
      </article>

      <article className="panel accountant-share-panel">
        <div className="panel-heading"><div><p className="eyebrow">EXCEL UNTUK AKUNTAN</p><h2>Unduh file lalu buka WhatsApp</h2></div></div>
        <div className="accountant-share-body">
          <p>File ini diambil langsung dari estimasi harian kalkulator—bukan dari perubahan Qty PO pusat. Kolomnya sama persis dengan ekspor kalkulator, dengan pemisah ribuan, header berwarna, dan garis pembatas yang lebih rapi.</p>
          <div className="invoice-source-note"><strong>Nilai Invoice/Tagihan</strong><span>Harga estimasi kalkulator yang sudah termasuk margin · distribusi {formatDate(workflow.serviceDate)}</span></div>
          {accountant && <div className="supplier-contact-row"><input value={phones[accountant.id] ?? accountant.phone ?? ""} onChange={(event) => setPhones((current) => ({ ...current, [accountant.id]: event.target.value }))} placeholder="Nomor WhatsApp akuntan" /><button type="button" className="button ghost" onClick={() => void saveContact(accountant)} disabled={savingIds.includes(-accountant.id)}>{savingIds.includes(-accountant.id) ? "…" : "Simpan No."}</button></div>}
          <button type="button" className="button primary wide" onClick={() => void exportAndOpenAccountant()} disabled={accountantExporting}>{accountantExporting ? "Mengambil dari kalkulator…" : accountant && waNumber(phones[accountant.id] ?? accountant.phone ?? "") ? "Unduh Excel & Buka WA Akuntan" : "Unduh Excel Akuntan"}</button>
        </div>
      </article>
    </section>
    </>
  );
}

function PaymentView({ unit, workflow, busy, updateWorkflow }: { unit: Unit; workflow: Workflow; busy: boolean; updateWorkflow: (field: string, value: string | number) => Promise<void> }) {
  const [invoiceAmount, setInvoiceAmount] = useState(String(workflow.invoiceAmount || ""));
  const [reference, setReference] = useState(workflow.paymentReference || "");
  const difference = Number(invoiceAmount || 0) - workflow.calculatorInvoiceTotal;
  return (
    <section className="payment-grid">
      <article className="panel bank-card">
        <p className="eyebrow">MAKER INVOICE/TAGIHAN {unit.name.toUpperCase()}</p>
        <h2>{unit.bankChannel}</h2>
        <div className="bank-total"><span>Nilai Invoice Kalkulator (termasuk margin)</span><strong>{formatMoney(workflow.calculatorInvoiceTotal)}</strong></div>
        <label>Status pembayaran<select value={workflow.paymentStatus} onChange={(event) => void updateWorkflow("paymentStatus", event.target.value)} disabled={busy}><option value="belum_dibuat">Belum dibuat</option><option value="maker">Maker selesai</option><option value="menunggu_checker">Menunggu checker</option><option value="dibayar">Dibayar</option><option value="gagal">Gagal</option></select></label>
        <label>Nomor referensi<input value={reference} onChange={(event) => setReference(event.target.value)} onBlur={() => void updateWorkflow("paymentReference", reference)} placeholder="Nomor transaksi / batch" /></label>
        <div className="security-note"><strong>Data bank yang tidak disimpan:</strong><span>Password, PIN, token, dan OTP.</span></div>
      </article>
      <article className="panel invoice-card">
        <p className="eyebrow">REKONSILIASI NILAI INVOICE/TAGIHAN</p>
        <h2>Cocokkan sebelum maker</h2>
        <label>Status invoice<select value={workflow.invoiceStatus} onChange={(event) => void updateWorkflow("invoiceStatus", event.target.value)} disabled={busy}><option value="belum_diminta">Belum diminta</option><option value="diminta">Sudah diminta</option><option value="diterima">Diterima</option><option value="selisih">Ada selisih</option></select></label>
        <label>Nominal invoice dari akuntan<input type="number" min="0" value={invoiceAmount} onChange={(event) => setInvoiceAmount(event.target.value)} onBlur={() => void updateWorkflow("invoiceAmount", Number(invoiceAmount || 0))} placeholder="Rp" /></label>
        <div className={`difference-card ${difference === 0 ? "ok" : "warn"}`}><span>Selisih terhadap Nilai Invoice Kalkulator</span><strong>{formatMoney(difference)}</strong><small>{difference === 0 ? "Nominal cocok" : "Periksa invoice sebelum melakukan maker"}</small></div>
      </article>
    </section>
  );
}

function DailyPaymentsView({ unit, date, payments, reload, notify }: { unit: Unit; date: string; payments: DailyPayment[]; reload: () => Promise<void>; notify: (message: string) => void }) {
  const [form, setForm] = useState({ recipientType: "guru_kader", recipientName: "", role: "Guru", rate: "", proofNumber: "", note: "" });
  const [saving, setSaving] = useState(false);
  const total = payments.reduce((sum, item) => sum + item.amount, 0);
  const submit = async () => {
    setSaving(true);
    try {
      await requestJson("/api/daily-payments", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ unitId: unit.id, serviceDate: date, ...form, rate: Number(form.rate) }) });
      setForm({ recipientType: "guru_kader", recipientName: "", role: "Guru", rate: "", proofNumber: "", note: "" });
      await reload(); notify("Pembayaran harian dan register bukti tersimpan.");
    } catch (error) { notify(error instanceof Error ? error.message : "Gagal menyimpan pembayaran harian."); }
    finally { setSaving(false); }
  };
  const update = async (payment: DailyPayment, patch: Partial<DailyPayment>) => {
    const { id: _id, ...rest } = payment;
    await requestJson("/api/daily-payments", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: payment.id, ...rest, ...patch }) });
    await reload(); notify("Status pembayaran harian diperbarui.");
  };
  const exportRegister = () => downloadXlsx(`register-pembayaran-harian-${unit.id}-${date}.xlsx`, "Register Harian", [
    ["Tanggal", "Penerima", "Jenis", "Peran", "Tarif Harian", "Jumlah", "Nomor Bukti", "Status Kuitansi", "Status Bayar", "Referensi Bank"],
    ...payments.map((item) => [date, item.recipientName, item.recipientType === "guru_kader" ? "Insentif guru/kader" : "Upah relawan", item.role, item.rate, item.amount, item.proofNumber, item.receiptStatus, item.paymentStatus, item.paymentReference || ""]),
    [], ["TOTAL", "", "", "", "", total, "", "", "", ""],
  ], { currencyColumns: [4, 5], totalRow: payments.length + 3, widths: [14, 24, 22, 18, 16, 16, 18, 18, 16, 22] });
  const printReceipt = (payment: DailyPayment) => {
    const amount = formatMoney(payment.amount);
    const typeLabel = payment.recipientType === "guru_kader" ? "Insentif guru/kader" : "Upah relawan";
    const popup = window.open("", "_blank", "noopener,noreferrer,width=860,height=700");
    if (!popup) { notify("Izinkan pop-up browser untuk mencetak kuitansi."); return; }
    popup.document.write(`<!doctype html><html><head><title>Kuitansi ${payment.proofNumber}</title><style>body{font-family:Arial,sans-serif;padding:32px;color:#111}header{text-align:center;border-bottom:2px solid #111;padding-bottom:16px;margin-bottom:22px}h1{font-size:20px;margin:0 0 6px}h2{font-size:18px;text-align:center;margin:20px 0}.meta{display:grid;grid-template-columns:180px 1fr;gap:8px;margin:18px 0}.total{font-size:22px;font-weight:700;text-align:right;margin:28px 0}.sign{display:flex;justify-content:space-between;margin-top:64px;text-align:center}.sign div{width:40%}@media print{body{padding:10px}}</style></head><body><header><h1>SPPG ${unit.name}</h1><div>Kwitansi Pembayaran Harian</div></header><h2>${typeLabel}</h2><div class="meta"><strong>Nomor bukti</strong><span>${payment.proofNumber}</span><strong>Tanggal layanan</strong><span>${date}</span><strong>Penerima</strong><span>${payment.recipientName}</span><strong>Peran</strong><span>${payment.role}</span><strong>Catatan</strong><span>${payment.note || "-"}</span></div><div class="total">Jumlah dibayar: ${amount}</div><p>Telah diterima dengan baik sesuai pekerjaan dan tarif harian pada tanggal layanan tersebut.</p><div class="sign"><div>Penerima,<br><br><br><u>${payment.recipientName}</u></div><div>Penanggung jawab,<br><br><br><u>${unit.name}</u></div></div><script>window.onload=()=>window.print();</script></body></html>`);
    popup.document.close();
  };
  return <section className="daily-payments-layout">
    <article className="panel">
      <div className="panel-heading"><div><p className="eyebrow">PEMBAYARAN HARIAN</p><h2>{unit.name}</h2></div><button type="button" className="button secondary" onClick={exportRegister} disabled={!payments.length}>Export Register</button></div>
      <p className="payment-helper">Insentif guru/kader dan upah relawan dicatat, dibuktikan, dan dibayar untuk satu tanggal layanan. Kuitansi diterbitkan per orang pada hari yang sama.</p>
      <div className="form-grid two"><label>Jenis penerima<select value={form.recipientType} onChange={(event) => setForm({ ...form, recipientType: event.target.value })}><option value="guru_kader">Insentif guru/kader</option><option value="relawan">Upah relawan</option></select></label><label>Nama penerima<input value={form.recipientName} onChange={(event) => setForm({ ...form, recipientName: event.target.value })} placeholder="Nama lengkap" /></label></div>
      <div className="form-grid three"><label>Peran<input value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })} placeholder="Guru / kader / relawan" /></label><label>Tarif harian<input type="number" min="1" value={form.rate} onChange={(event) => setForm({ ...form, rate: event.target.value })} placeholder="Rp" /></label><label>Nomor bukti<input value={form.proofNumber} onChange={(event) => setForm({ ...form, proofNumber: event.target.value })} placeholder="BKT-20261005-001" /></label></div>
      <label>Catatan<input value={form.note} onChange={(event) => setForm({ ...form, note: event.target.value })} placeholder="Keterangan pekerjaan / penerimaan" /></label>
      <button type="button" className="button primary wide" onClick={() => void submit()} disabled={saving || !form.recipientName || !form.rate || !form.proofNumber}>{saving ? "Menyimpan…" : "Simpan Pembayaran Harian"}</button>
    </article>
    <article className="panel"><div className="panel-heading compact"><div><p className="eyebrow">REGISTER BUKTI & KUITANSI</p><h2>{payments.length} penerima · {formatMoney(total)}</h2></div></div><div className="table-wrap"><table><thead><tr><th>Penerima</th><th>Nomor bukti</th><th>Nilai</th><th>Kuitansi</th><th>Pembayaran</th><th /></tr></thead><tbody>{payments.map((item) => <tr key={item.id}><td><strong>{item.recipientName}</strong><small>{item.role} · {item.recipientType === "guru_kader" ? "Guru/kader" : "Relawan"}</small></td><td>{item.proofNumber}</td><td>{formatMoney(item.amount)}</td><td><select value={item.receiptStatus} onChange={(event) => void update(item, { receiptStatus: event.target.value })}><option value="draft">Draf</option><option value="ready">Siap cetak</option><option value="issued">Terbit</option></select></td><td><select value={item.paymentStatus} onChange={(event) => void update(item, { paymentStatus: event.target.value })}><option value="pending">Belum dibayar</option><option value="paid">Dibayar</option><option value="failed">Gagal</option></select></td><td><button type="button" className="button ghost" onClick={() => printReceipt(item)}>Cetak</button></td></tr>)}</tbody></table>{!payments.length && <div className="empty-state compact">Belum ada pembayaran pada tanggal ini.</div>}</div></article>
  </section>;
}

function AiView({ unit, workflow, items }: { unit: Unit; workflow: Workflow; items: Purchase[] }) {
  const [mode, setMode] = useState("audit");
  const [prompt, setPrompt] = useState("Audit estimasi belanja ini dan tunjukkan bagian yang harus saya periksa sebelum dikirim ke akuntan dan supplier.");
  const [answer, setAnswer] = useState("");
  const [provider, setProvider] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const run = async () => {
    setLoading(true); setError(""); setAnswer("");
    try {
      const result = await requestJson<{ text: string; provider: string; model: string }>("/api/ai", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, prompt, unitName: unit.name, context: { workflow, purchaseItems: items } }),
      });
      setAnswer(result.text); setProvider(`${result.provider} · ${result.model}`);
    } catch (aiError) {
      setError(aiError instanceof Error ? aiError.message : "AI gagal dijalankan.");
    } finally { setLoading(false); }
  };
  return (
    <section className="ai-layout">
      <article className="panel ai-compose">
        <div className="ai-orb">AI</div>
        <p className="eyebrow">ASISTEN DAPUR TERLINDUNGI</p>
        <h2>Fitur AI tetap ada, kunci tidak berada di browser.</h2>
        <div className="ai-modes">
          {[['audit','Audit belanja'],['sop','Buat SOP'],['nutrition','Audit nutrisi'],['message','Pesan WA'],['chat','Tanya bebas']].map(([key, label]) => <button type="button" key={key} className={mode === key ? "active" : ""} onClick={() => setMode(key)}>{label}</button>)}
        </div>
        <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={7} />
        <button type="button" className="button primary wide" onClick={() => void run()} disabled={loading}>{loading ? "AI sedang menganalisis…" : "Jalankan analisis"}</button>
        {error && <div className="alert error compact-alert">{error}</div>}
      </article>
      <article className="panel ai-answer">
        <div className="panel-heading compact"><div><p className="eyebrow">HASIL ANALISIS</p><h2>{provider || "Belum dijalankan"}</h2></div></div>
        {answer ? <div className="answer-text">{answer}</div> : <div className="answer-empty"><strong>Konteks otomatis</strong><p>AI menerima unit, status workflow, dan {items.length} item estimasi yang sedang aktif.</p></div>}
      </article>
    </section>
  );
}

type MigrationKind = "recipes" | "prices" | "gramasi" | "bumbu" | "plans";
type MigrationEntry = { index: number; file: File; kind: MigrationKind | null; count: number; target: string; error: string };
type MigrationReport = { fileName: string; kind: MigrationKind; target: string; processed: number; skipped: number };
const migrationLabels: Record<MigrationKind, string> = { recipes: "Resep master", prices: "Master harga", gramasi: "Aturan gramasi", bumbu: "Daftar bumbu", plans: "Rencana harian" };
const importChunkBytes = 240_000;

function migrationArray(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (!value || typeof value !== "object") return [];
  const record = value as Record<string, unknown>;
  for (const key of ["recipes", "plans", "items", "data", "prices", "gramasi", "bumbu"]) if (Array.isArray(record[key])) return record[key] as unknown[];
  return [];
}

function detectMigrationKind(value: unknown): { kind: MigrationKind | null; count: number } {
  const items = migrationArray(value);
  if (!items.length) return { kind: null, count: 0 };
  if (items.every((item) => typeof item === "string")) return { kind: "bumbu", count: items.length };
  const sample = items.find((item) => item && typeof item === "object") as Record<string, unknown> | undefined;
  if (!sample) return { kind: null, count: items.length };
  if ("planName" in sample || "tanggal" in sample || "planDate" in sample || "shoppingListJSON" in sample || "porsiKecil" in sample || "porsiBesar" in sample) return { kind: "plans", count: items.length };
  if (Array.isArray(sample.ingredients)) return { kind: "recipes", count: items.length };
  if ("kecil" in sample || "besar" in sample || "smallGrams" in sample || "largeGrams" in sample) return { kind: "gramasi", count: items.length };
  if ("price" in sample || "harga" in sample || "waste" in sample || "grams_per_unit" in sample) return { kind: "prices", count: items.length };
  return { kind: null, count: items.length };
}

function splitMigrationItems(items: unknown[]) {
  const encoder = new TextEncoder();
  const chunks: unknown[][] = [];
  let current: unknown[] = [];
  let currentBytes = 2;
  for (const item of items) {
    const itemBytes = encoder.encode(JSON.stringify(item)).byteLength + (current.length ? 1 : 0);
    if (current.length && currentBytes + itemBytes > importChunkBytes) {
      chunks.push(current);
      current = [];
      currentBytes = 2;
    }
    current.push(item);
    currentBytes += itemBytes;
  }
  if (current.length) chunks.push(current);
  return chunks;
}

function MigrationView({ imports, reload }: { imports: LegacyImport[]; reload: () => Promise<void> }) {
  const [entries, setEntries] = useState<MigrationEntry[]>([]);
  const [inputKey, setInputKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [progress, setProgress] = useState("");
  const [importMode, setImportMode] = useState<"merge" | "replace">("merge");
  const [deleteKind, setDeleteKind] = useState<MigrationKind>("plans");
  const [deleteTarget, setDeleteTarget] = useState("maja");
  const chooseFiles = async (files: FileList | null) => {
    const selected = Array.from(files || []).slice(0, 10);
    const analyzed = await Promise.all(selected.map(async (file, index) => {
      try {
        const detected = detectMigrationKind(JSON.parse(await file.text()));
        const lowerName = file.name.toLowerCase();
        const target = detected.kind === "plans" ? lowerName.includes("maja") ? "maja" : lowerName.includes("cemplang") ? "cemplang" : "" : "shared";
        return { index, file, ...detected, target, error: detected.kind ? "" : "Isi JSON tidak dikenali" };
      } catch { return { index, file, kind: null, count: 0, target: "", error: "JSON rusak atau tidak dapat dibaca" } as MigrationEntry; }
    }));
    setEntries(analyzed); setMessage(""); setProgress("");
  };
  const upload = async () => {
    if (!entries.length || entries.some((entry) => !entry.kind || entry.error || (entry.kind === "plans" && !entry.target))) return;
    setBusy(true); setMessage("");
    try {
      if (importMode === "replace") {
        const labels = entries.map((entry) => `${entry.kind ? migrationLabels[entry.kind] : "Data"}${entry.kind === "plans" ? ` ${entry.target}` : ""}`).join(", ");
        if (!window.confirm(`Yakin mengganti data lama?\n\n${labels}\n\nData tujuan akan dihapus dahulu, lalu diisi file baru. Data di tujuan lain tidak berubah.`)) {
          setBusy(false);
          return;
        }
        const destinations = new Map<string, { kind: MigrationKind; target: string }>();
        entries.forEach((entry) => {
          if (!entry.kind) return;
          const target = entry.kind === "plans" ? entry.target : "shared";
          destinations.set(`${entry.kind}:${target}`, { kind: entry.kind, target });
        });
        for (const destination of destinations.values()) {
          setProgress(`Membersihkan data lama ${migrationLabels[destination.kind]}…`);
          await requestJson("/api/import", {
            method: "DELETE", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...destination, confirm: "HAPUS" }),
          });
        }
      }
      const batches: { entry: MigrationEntry; items: unknown[]; part: number; totalParts: number }[] = [];
      for (const entry of entries) {
        const items = migrationArray(JSON.parse(await entry.file.text()));
        const chunks = splitMigrationItems(items);
        chunks.forEach((chunk, index) => batches.push({ entry, items: chunk, part: index + 1, totalParts: chunks.length }));
      }
      const totals = new Map<number, MigrationReport>();
      let transmittedParts = 0;
      const sendOversizedBatch = async (batch: { entry: MigrationEntry; items: unknown[] }) => {
        const uploadId = crypto.randomUUID();
        const serialized = JSON.stringify(batch.items);
        const chunkSize = 80000;
        let chunkIndex = 0;
        for (let offset = 0; offset < serialized.length; offset += chunkSize) {
          setProgress(`Mengirim data besar bagian ${chunkIndex + 1} · ${batch.entry.file.name}`);
          await requestJson("/api/import", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "upload_import_chunk", uploadId, chunkIndex, chunkText: serialized.slice(offset, offset + chunkSize), target: batch.entry.target, fileName: batch.entry.file.name }),
          });
          chunkIndex += 1;
        }
        const result = await requestJson<{ reports: MigrationReport[] }>("/api/import", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "commit_import_chunks", uploadId, target: batch.entry.target, fileName: batch.entry.file.name }),
        });
        return result.reports[0] || { fileName: batch.entry.file.name, kind: batch.entry.kind!, target: batch.entry.target, processed: 0, skipped: 0 };
      };
      const sendBatch = async (batch: { entry: MigrationEntry; items: unknown[]; part: number; totalParts: number }, suffix = ""): Promise<MigrationReport> => {
        transmittedParts += 1;
        setProgress(`Mengimpor bagian ${transmittedParts} · ${batch.entry.file.name}`);
        const form = new FormData();
        const baseName = batch.entry.file.name.replace(/\.json$/i, "");
        const partName = `${baseName}.bagian-${String(batch.part).padStart(2, "0")}${suffix}.json`;
        form.append("files", new Blob([JSON.stringify(batch.items)], { type: "application/json" }), partName);
        form.append("assignments", JSON.stringify([{ index: 0, target: batch.entry.target }]));
        try {
          const result = await requestJson<{ reports: MigrationReport[] }>("/api/import", { method: "POST", body: form });
          return result.reports[0] || { fileName: partName, kind: batch.entry.kind!, target: batch.entry.target, processed: 0, skipped: 0 };
        } catch (error) {
          if (error instanceof RequestError && error.status === 413 && batch.items.length > 1) {
            const midpoint = Math.ceil(batch.items.length / 2);
            const left = await sendBatch({ ...batch, items: batch.items.slice(0, midpoint) }, `${suffix}a`);
            const right = await sendBatch({ ...batch, items: batch.items.slice(midpoint) }, `${suffix}b`);
            return { ...left, processed: left.processed + right.processed, skipped: left.skipped + right.skipped };
          }
          if (error instanceof RequestError && error.status === 413) {
            return sendOversizedBatch(batch);
          }
          throw error;
        }
      };
      for (let index = 0; index < batches.length; index += 1) {
        const batch = batches[index];
        const report = await sendBatch(batch);
        const current = totals.get(batch.entry.index) || { fileName: batch.entry.file.name, kind: batch.entry.kind!, target: batch.entry.target, processed: 0, skipped: 0 };
        current.processed += report?.processed || 0;
        current.skipped += report?.skipped || 0;
        totals.set(batch.entry.index, current);
      }
      const reports = Array.from(totals.values());
      setMessage(`Impor selesai: ${reports.map((report) => `${migrationLabels[report.kind]} ${report.processed}${report.skipped ? `, dilewati ${report.skipped}` : ""}${report.kind === "plans" ? ` → ${report.target}` : ""}`).join(" · ")}`);
      setEntries([]); setInputKey((value) => value + 1); await reload();
    } catch (uploadError) {
      setMessage(uploadError instanceof Error ? uploadError.message : "Impor gagal.");
    } finally { setBusy(false); setProgress(""); }
  };
  const deleteData = async () => {
    const targetLabel = deleteKind === "plans" ? `rencana ${deleteTarget === "maja" ? "Maja" : "Cemplang"}` : migrationLabels[deleteKind];
    if (!window.confirm(`Yakin menghapus semua ${targetLabel}?\n\nTindakan ini tidak menghapus jenis data atau dapur lain. Sebaiknya unduh backup terlebih dahulu.`)) return;
    setBusy(true); setMessage("");
    try {
      const result = await requestJson<{ deleted: number }>("/api/import", {
        method: "DELETE", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: deleteKind, target: deleteKind === "plans" ? deleteTarget : "shared", confirm: "HAPUS" }),
      });
      setMessage(`${targetLabel} berhasil dikosongkan (${result.deleted} dokumen).`);
      await reload();
    } catch (deleteError) {
      setMessage(deleteError instanceof Error ? deleteError.message : "Gagal menghapus data.");
    } finally { setBusy(false); }
  };
  const ready = entries.length > 0 && entries.every((entry) => entry.kind && !entry.error && (entry.kind !== "plans" || entry.target));
  return (
    <section className="migration-workspace">
      <article className="panel upload-card migration-uploader">
        <p className="eyebrow">IMPOR MULTI-FILE TERKENDALI</p>
        <h2>Unggah semua JSON sekaligus</h2>
        <p className="migration-copy">Resep, harga, gramasi, dan bumbu otomatis masuk ke master bersama. Untuk setiap file rencana, Anda wajib memilih tujuan Maja atau Cemplang sebelum tombol impor aktif.</p>
        <div className="migration-actions"><a className="button secondary" href="/api/backup">Unduh Backup Lengkap ke PC (.zip)</a><span>ZIP berisi 6 JSON terpisah dan siap disimpan sebagai cadangan.</span></div>
        <div className="import-mode-box"><strong>Cara memasukkan data</strong><label><input type="radio" name="import-mode" checked={importMode === "merge"} onChange={() => setImportMode("merge")} /><span>Gabungkan — data lama dipertahankan dan data yang sama diperbarui</span></label><label><input type="radio" name="import-mode" checked={importMode === "replace"} onChange={() => setImportMode("replace")} /><span>Ganti data lama — tujuan dipastikan kosong sebelum file baru masuk</span></label></div>
        <div className="upload-zone">
          <input key={inputKey} type="file" accept=".json,application/json" multiple onChange={(event) => void chooseFiles(event.target.files)} />
          <strong>{entries.length ? `${entries.length} file sudah dianalisis` : "Pilih seluruh file JSON"}</strong>
          <small>Maksimal 10 file · 25 MB per file · file besar dibagi otomatis</small>
        </div>
        {entries.length > 0 && <div className="migration-map"><div className="migration-map-head"><span>File</span><span>Jenis terdeteksi</span><span>Jumlah</span><span>Tujuan database</span></div>{entries.map((entry) => <div className={entry.error ? "invalid" : ""} key={`${entry.index}-${entry.file.name}`}><span><strong>{entry.file.name}</strong><small>{entry.error || "Siap"}</small></span><span>{entry.kind ? migrationLabels[entry.kind] : "Tidak dikenali"}</span><span>{entry.count}</span><span>{entry.kind === "plans" ? <select value={entry.target} onChange={(event) => setEntries(entries.map((item) => item.index === entry.index ? { ...item, target: event.target.value } : item))}><option value="">Pilih dapur…</option><option value="maja">Rencana Maja</option><option value="cemplang">Rencana Cemplang</option></select> : entry.kind ? "Master bersama" : "—"}</span></div>)}</div>}
        <button className="button primary wide migration-import-button" type="button" disabled={!ready || busy} onClick={() => void upload()}>{busy ? "Memvalidasi dan mengimpor…" : importMode === "replace" ? "Konfirmasi, Hapus Lama & Impor" : "Konfirmasi & Impor Semua"}</button>
        {progress && <div className="alert info">{progress}</div>}
        {message && <div className="alert info">{message}</div>}
        <div className="security-note light"><strong>Perlindungan salah database</strong><span>Server membaca ulang isi setiap JSON. File tidak dikenal atau rencana tanpa tujuan akan ditolak sebelum data disimpan.</span></div>
        <div className="delete-data-box"><div><strong>Hapus satu kelompok data</strong><span>Untuk pengujian atau migrasi bertahap. Selalu ada konfirmasi sebelum dihapus.</span></div><select value={deleteKind} onChange={(event) => setDeleteKind(event.target.value as MigrationKind)}>{Object.entries(migrationLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>{deleteKind === "plans" && <select value={deleteTarget} onChange={(event) => setDeleteTarget(event.target.value)}><option value="maja">Rencana Maja</option><option value="cemplang">Rencana Cemplang</option></select>}<button type="button" className="button danger" onClick={() => void deleteData()} disabled={busy}>Hapus Data Terpilih</button></div>
      </article>
      <article className="panel migration-history">
        <div className="panel-heading compact"><div><p className="eyebrow">RIWAYAT IMPOR</p><h2>File yang sudah diproses</h2></div></div>
        <div className="import-list">
          {imports.map((item) => <div key={item.id}><span><strong>{item.fileName}</strong><small>{item.unitId === "shared" ? "Master bersama" : `Rencana ${item.unitId}`} · {(item.sizeBytes / 1024).toFixed(1)} KB</small></span><em>{item.status.replaceAll("_", " ")}</em></div>)}
          {!imports.length && <div><span><strong>Belum ada impor</strong><small>Riwayat akan muncul setelah proses pertama.</small></span></div>}
        </div>
      </article>
    </section>
  );
}

function LoadingState() {
  return <div className="loading-state"><span /><span /><span /></div>;
}

type AccessMember = {
  id: string;
  username: string;
  displayName: string;
  role: "owner" | "maja" | "cemplang";
  active: number;
};

const emptyAccessForm = { id: "", username: "", displayName: "", role: "cemplang", password: "" };

function AccessView() {
  const [members, setMembers] = useState<AccessMember[]>([]);
  const [form, setForm] = useState(emptyAccessForm);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const load = async () => {
    try { const result = await requestJson<{ members: AccessMember[] }>("/api/access"); setMembers(result.members); }
    catch (loadError) { setMessage(loadError instanceof Error ? loadError.message : "Gagal memuat akses."); }
  };
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, []);
  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setMessage("");
    try { await requestJson("/api/access", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "save", ...form }) }); setForm(emptyAccessForm); await load(); setMessage("Akun dan hak akses berhasil disimpan."); }
    catch (saveError) { setMessage(saveError instanceof Error ? saveError.message : "Gagal menyimpan akses."); }
    finally { setBusy(false); }
  };
  const remove = async (id: string) => {
    setBusy(true); setMessage("");
    try { await requestJson("/api/access", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "delete", id }) }); await load(); }
    catch (deleteError) { setMessage(deleteError instanceof Error ? deleteError.message : "Gagal menghapus akses."); }
    finally { setBusy(false); }
  };
  const edit = (member: AccessMember) => {
    setForm({ id: member.id, username: member.username, displayName: member.displayName, role: member.role, password: "" });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  return (
    <section className="access-grid">
      <article className="panel access-form-card">
        <p className="eyebrow">ADMIN USERNAME & PASSWORD</p>
        <h2>{form.id ? "Ubah akun pengguna" : "Tambahkan chef atau ahli gizi"}</h2>
        <p>Akun Maja hanya membuka Maja, akun Cemplang hanya membuka Cemplang, sedangkan Owner dapat membuka pusat kontrol dan kedua dapur.</p>
        <form onSubmit={save} className="stack-form">
          <label>Username<input value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value.toLowerCase() })} placeholder="contoh: chef-maja" required /></label>
          <label>Nama pengguna<input value={form.displayName} onChange={(event) => setForm({ ...form, displayName: event.target.value })} placeholder="Nama chef / ahli gizi" required /></label>
          <label>Akses<select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })}><option value="cemplang">Cemplang saja</option><option value="maja">Maja saja</option><option value="owner">Owner — pusat dan dua dapur</option></select></label>
          <label>{form.id ? "Password baru (kosongkan jika tidak diganti)" : "Password awal"}<input type="password" autoComplete="new-password" minLength={10} value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} required={!form.id} /></label>
          <button className="button primary wide" disabled={busy}>{busy ? "Menyimpan…" : form.id ? "Simpan Perubahan" : "Buat Akun"}</button>
          {form.id && <button type="button" className="button ghost wide" onClick={() => setForm(emptyAccessForm)}>Batal mengubah</button>}
        </form>
        {message && <div className="alert info">{message}</div>}
        <div className="security-note light"><strong>Sebelum dipakai tim</strong><span>Ganti password akun uji dan tambahkan email ChatGPT anggota ke izin hosting privat.</span></div>
      </article>
      <article className="panel member-card">
        <div className="panel-heading compact"><div><p className="eyebrow">AKUN AKTIF</p><h2>{members.length} pengguna</h2></div></div>
        <div className="member-list">
          {members.map((member) => (
            <div key={member.id}>
              <span className={`member-role ${member.role}`}>{member.role === "owner" ? "O" : member.role === "maja" ? "M" : "C"}</span>
              <div><strong>{member.displayName}</strong><small>@{member.username}</small></div>
              <em>{member.role === "owner" ? "Pusat + semua dapur" : `${member.role} saja`}</em>
              <span className="member-actions"><button type="button" disabled={busy} onClick={() => edit(member)}>Ubah</button>{member.role !== "owner" && <button type="button" disabled={busy} onClick={() => void remove(member.id)}>Hapus</button>}</span>
            </div>
          ))}
        </div>
      </article>
    </section>
  );
}

type AiSetting = {
  provider: "gemini" | "openai";
  configured: boolean;
  source: "hosting" | "admin" | null;
  keyHint: string;
  model: string;
  enabled: boolean;
  updatedAt: string | null;
};

function AiSettingsView() {
  const [settings, setSettings] = useState<AiSetting[]>([]);
  const [keys, setKeys] = useState<Record<string, string>>({ gemini: "", openai: "" });
  const [models, setModels] = useState<Record<string, string>>({ gemini: "gemini-2.5-flash", openai: "gpt-4o-mini" });
  const [enabled, setEnabled] = useState<Record<string, boolean>>({ gemini: true, openai: true });
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const load = async () => {
    try {
      const result = await requestJson<{ providers: AiSetting[] }>("/api/ai-settings");
      setSettings(result.providers);
      setModels(Object.fromEntries(result.providers.map((item) => [item.provider, item.model])));
      setEnabled(Object.fromEntries(result.providers.map((item) => [item.provider, item.enabled])));
    } catch (loadError) { setMessage(loadError instanceof Error ? loadError.message : "Gagal memuat pengaturan AI."); }
  };
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, []);
  const save = async (event: FormEvent, provider: "gemini" | "openai") => {
    event.preventDefault(); setBusy(provider); setMessage("");
    try {
      await requestJson("/api/ai-settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider, apiKey: keys[provider], model: models[provider], enabled: enabled[provider] }) });
      setKeys({ ...keys, [provider]: "" }); await load(); setMessage(`${provider === "gemini" ? "Gemini" : "OpenAI"} berhasil disimpan di server.`);
    } catch (saveError) { setMessage(saveError instanceof Error ? saveError.message : "Gagal menyimpan API key."); }
    finally { setBusy(""); }
  };
  return (
    <section className="ai-settings-grid">
      <article className="panel ai-settings-intro"><p className="eyebrow">KUNCI AI SERVER</p><h2>Pengaturan Gemini & OpenAI</h2><p>Masukkan API key di sini seperti pada aplikasi lama. Nilainya dikirim langsung ke server, tidak ditampilkan kembali di browser, dan dipakai bersama oleh aplikasi Maja serta Cemplang.</p><div className="security-note light"><strong>Urutan penggunaan</strong><span>Gemini dipakai sebagai utama. OpenAI dapat menjadi cadangan ketika Gemini gagal, sesuai alur aplikasi sumber.</span></div></article>
      <div className="provider-stack">
        {(["gemini", "openai"] as const).map((provider) => {
          const current = settings.find((item) => item.provider === provider);
          return <form key={provider} className="panel provider-card" onSubmit={(event) => void save(event, provider)}><div className="provider-heading"><span className={`provider-logo ${provider}`}>{provider === "gemini" ? "G" : "O"}</span><div><p>{provider === "gemini" ? "GOOGLE AI" : "OPENAI"}</p><h3>{provider === "gemini" ? "Gemini API" : "OpenAI API"}</h3></div><em className={current?.configured ? "configured" : ""}>{current?.configured ? `Aktif · ${current.keyHint}` : "Belum diatur"}</em></div><label>API key<input type="password" autoComplete="off" value={keys[provider]} onChange={(event) => setKeys({ ...keys, [provider]: event.target.value })} placeholder={current?.configured ? "Kosongkan jika key tidak diganti" : provider === "gemini" ? "AIza…" : "sk-…"} /></label><label>Model<input value={models[provider] || ""} onChange={(event) => setModels({ ...models, [provider]: event.target.value })} /></label><label className="toggle-line"><input type="checkbox" checked={enabled[provider] ?? true} onChange={(event) => setEnabled({ ...enabled, [provider]: event.target.checked })} />Aktifkan provider ini</label><button className="button primary wide" disabled={Boolean(busy)}>{busy === provider ? "Menyimpan…" : `Simpan ${provider === "gemini" ? "Gemini" : "OpenAI"}`}</button></form>;
        })}
      </div>
      {message && <div className="alert info ai-settings-message">{message}</div>}
    </section>
  );
}
