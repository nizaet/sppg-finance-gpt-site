"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { downloadXlsx } from "./xlsx";
import { operationalCategories, operationalCategoryLabels } from "./operational-categories";

type Ingredient = { name: string; quantityGr: number; supplierCategory: string };
type Recipe = { id?: string; name: string; englishName?: string; category?: string; method?: string; ingredients: Ingredient[]; nutrition?: Record<string, number> };
type PlanMenu = { recipeId: string; name: string; categoryId: string };
type ShoppingItem = { itemName: string; quantity: number; unit: string; unitPrice: number; supplierCategory: string; operationalCategory?: string; supplierName?: string; note?: string };
type Plan = { id?: string; planName: string; serviceDate: string; portionsSmall: number; portionsLarge: number; menus: PlanMenu[]; shopping: ShoppingItem[]; status: string; bgnServiceDays: number };
type Price = { id: number; itemKey: string; itemName: string; price: number; purchaseUnit: string; category: string };
type PortionRule = { id: string; name: string; smallGrams: number; largeGrams: number };
type KitchenData = { unitId: string; unit: { name: string; bank: string }; recipes: Recipe[]; plans: Plan[]; prices: Price[]; rules: PortionRule[] };
type ModuleId = "dashboard" | "recipes" | "planning" | "estimate" | "documents" | "nutrition" | "master";

const modules: Array<[ModuleId, string, string]> = [
  ["dashboard", "Ringkasan", "01"], ["recipes", "Daftar Resep", "02"],
  ["planning", "Perencanaan & Kalender", "03"], ["estimate", "Estimasi Belanja", "04"],
  ["documents", "SOP & Surat Pembelian", "05"], ["nutrition", "Nutrisi & AI", "06"],
  ["master", "Master Harga & Gramasi", "07"],
];

const suppliers: Record<string, string> = {
  buah_sayur: "Buah & Sayur", ayam: "Supplier Ayam", ikan: "Supplier Ikan",
  tahu_tempe: "Tahu & Tempe", telur: "Supplier Telur", beras: "Supplier Beras",
  bahan_kering: "Bahan Kering / Koperasi", lainnya: "Lainnya",
};

const money = (value: number) => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(value || 0);
const today = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Jakarta", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
const normalize = (value: string) => value.trim().toLocaleLowerCase("id-ID").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
const freshRecipe = (): Recipe => ({ name: "", englishName: "", category: "Menu Utama", method: "", ingredients: [{ name: "", quantityGr: 0, supplierCategory: "lainnya" }], nutrition: {} });
const freshPlan = (): Plan => ({ planName: "", serviceDate: today(), portionsSmall: 0, portionsLarge: 0, menus: [], shopping: [], status: "draft", bgnServiceDays: 1 });

async function json<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  const body = (await response.json()) as T & { error?: string };
  if (!response.ok) throw new Error(body.error || "Permintaan gagal.");
  return body;
}

function calculateShopping(plan: Plan, data: KitchenData): ShoppingItem[] {
  const result = new Map<string, ShoppingItem>();
  plan.menus.forEach((menu) => {
    const recipe = data.recipes.find((item) => item.id === menu.recipeId);
    const rule = data.rules.find((item) => item.id === menu.categoryId);
    if (!recipe || !rule) return;
    const targetGrams = plan.portionsSmall * rule.smallGrams + plan.portionsLarge * rule.largeGrams;
    const baseGrams = recipe.ingredients.reduce((sum, item) => sum + Math.max(0, Number(item.quantityGr || 0)), 0);
    if (!targetGrams || !baseGrams) return;
    recipe.ingredients.forEach((ingredient) => {
      const key = normalize(ingredient.name);
      const quantity = targetGrams * (Number(ingredient.quantityGr || 0) / baseGrams) / 1000;
      if (!key || quantity <= 0) return;
      const price = data.prices.find((item) => item.itemKey === key);
      const existing = result.get(key);
      if (existing) {
        existing.quantity += quantity;
        existing.note = `${existing.note || ""}; ${menu.name}`.replace(/^; /, "");
      } else {
        result.set(key, { itemName: ingredient.name, quantity, unit: "kg", unitPrice: price?.price || 0, supplierCategory: ingredient.supplierCategory || "lainnya", operationalCategory: price?.category || "lain_lain", note: menu.name });
      }
    });
  });
  return Array.from(result.values()).map((item) => ({ ...item, quantity: Number(item.quantity.toFixed(3)) })).sort((a, b) => a.supplierCategory.localeCompare(b.supplierCategory) || a.itemName.localeCompare(b.itemName));
}

export default function KitchenClient({ unitId, onBack, onSwitchUnit }: { unitId: "maja" | "cemplang"; onBack: () => void; onSwitchUnit: (id: "maja" | "cemplang") => void }) {
  const [active, setActive] = useState<ModuleId>("dashboard");
  const [data, setData] = useState<KitchenData | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const load = async (quiet = false) => {
    if (!quiet) setLoading(true);
    try { setData(await json<KitchenData>(`/api/kitchen?unitId=${unitId}`)); setError(""); }
    catch (loadError) { setError(loadError instanceof Error ? loadError.message : "Aplikasi dapur gagal dimuat."); }
    finally { setLoading(false); }
  };
  useEffect(() => {
    // This effect synchronizes the selected kitchen with its server-side data.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [unitId]);
  const post = async (payload: Record<string, unknown>) => {
    setBusy(true); setError("");
    try {
      const result = await json<{ ok: true; id?: string }>("/api/kitchen", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ unitId, ...payload }) });
      await load(true); return result;
    } catch (postError) { setError(postError instanceof Error ? postError.message : "Gagal menyimpan data."); throw postError; }
    finally { setBusy(false); }
  };
  const notify = (message: string) => { setNotice(message); window.setTimeout(() => setNotice(""), 3200); };
  return (
    <div className="kitchen-shell">
      <aside className="kitchen-sidebar">
        <div className="kitchen-brand"><span>{unitId === "maja" ? "M" : "C"}</span><div><strong>{data?.unit.name || (unitId === "maja" ? "SPPG Maja Baru" : "SPPG Cemplang 02")}</strong><small>Perencanaan Menu & Gizi</small></div></div>
        <button type="button" className="back-control" onClick={onBack}>← Pusat Operasional</button>
        <nav className="kitchen-nav">{modules.map(([id, label, no]) => <button type="button" key={id} className={active === id ? "active" : ""} onClick={() => setActive(id)}><span>{no}</span>{label}</button>)}</nav>
        <div className="kitchen-safe"><span /><div><strong>Database privat</strong><small>Data tiap dapur terpisah</small></div></div>
      </aside>
      <main className="kitchen-main">
        <header className="kitchen-topbar"><div><p className="eyebrow">APLIKASI DAPUR LENGKAP</p><h1>{modules.find(([id]) => id === active)?.[1]}</h1></div><div className="kitchen-unit-switch"><button type="button" className={unitId === "maja" ? "active" : ""} onClick={() => onSwitchUnit("maja")}>Maja</button><button type="button" className={unitId === "cemplang" ? "active" : ""} onClick={() => onSwitchUnit("cemplang")}>Cemplang</button></div></header>
        {error && <div className="alert error">{error}</div>}{notice && <div className="toast">{notice}</div>}
        {loading || !data ? <div className="loading-state"><span /><span /><span /></div> : <>
          {active === "dashboard" && <Dashboard data={data} open={setActive} />}
          {active === "recipes" && <Recipes data={data} busy={busy} post={post} notify={notify} />}
          {active === "planning" && <Planning data={data} busy={busy} post={post} notify={notify} />}
          {active === "estimate" && <Estimate data={data} busy={busy} post={post} notify={notify} />}
          {active === "documents" && <Documents data={data} />}
          {active === "nutrition" && <Nutrition data={data} />}
          {active === "master" && <Master data={data} busy={busy} post={post} notify={notify} />}
        </>}
      </main>
    </div>
  );
}

function Dashboard({ data, open }: { data: KitchenData; open: (id: ModuleId) => void }) {
  const missingPrices = new Set(data.recipes.flatMap((recipe) => recipe.ingredients.map((item) => normalize(item.name))).filter((key) => key && !data.prices.some((price) => price.itemKey === key))).size;
  const latest = data.plans[0];
  return <><section className="kitchen-metrics"><article className="kmetric emerald"><p>Database resep</p><strong>{data.recipes.length}</strong><small>resep aktif</small></article><article className="kmetric"><p>Rencana tersimpan</p><strong>{data.plans.length}</strong><small>jadwal produksi</small></article><article className="kmetric amber"><p>Harga belum lengkap</p><strong>{missingPrices}</strong><small>bahan perlu harga</small></article><article className="kmetric dark"><p>Kanal pembayaran</p><strong>{data.unit.bank}</strong><small>status dibaca pusat</small></article></section><section className="kitchen-dashboard-grid"><article className="panel kitchen-welcome"><p className="eyebrow">ALUR UTAMA</p><h2>Resep → Rencana → Estimasi → PO/SOP</h2><p>Semua pekerjaan dapur tetap di aplikasi ini. Pusat Operasional hanya menarik hasil final dan statusnya.</p><div className="quick-grid">{[["recipes", "Kelola resep", "Bahan, gramasi, metode"], ["planning", "Buat rencana", "Menu, porsi, kalender"], ["estimate", "Hitung estimasi", "Harga, pagu, belanja"], ["documents", "Cetak dokumen", "SOP, PO, Excel, WA"]].map(([id, title, text], index) => <button type="button" key={id} onClick={() => open(id as ModuleId)}><span>0{index + 1}</span><strong>{title}</strong><small>{text}</small></button>)}</div></article><aside className="panel latest-plan"><p className="eyebrow">RENCANA TERBARU</p>{latest ? <><h2>{latest.planName}</h2><strong>{latest.serviceDate}</strong><p>{latest.menus.length} menu · {latest.portionsSmall + latest.portionsLarge} porsi</p><div className={`plan-status ${latest.status}`}>{latest.status === "final" ? "ESTIMASI FINAL" : "DRAF"}</div></> : <div className="empty-state compact">Belum ada rencana.</div>}</aside></section></>;
}

function Recipes({ data, busy, post, notify }: ModuleProps) {
  const [draft, setDraft] = useState<Recipe>(freshRecipe());
  const [search, setSearch] = useState("");
  const filtered = data.recipes.filter((recipe) => recipe.name.toLowerCase().includes(search.toLowerCase()));
  const select = (recipe?: Recipe) => setDraft(recipe ? JSON.parse(JSON.stringify(recipe)) as Recipe : freshRecipe());
  const patchIngredient = (index: number, patch: Partial<Ingredient>) => setDraft((current) => ({ ...current, ingredients: current.ingredients.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item) }));
  const save = async (event: FormEvent) => { event.preventDefault(); try { const clean = { ...draft, ingredients: draft.ingredients.filter((item) => item.name.trim() && item.quantityGr > 0) }; const result = await post({ action: "save_recipe", recipe: clean }); setDraft({ ...clean, id: result.id || draft.id }); notify("Resep berhasil disimpan."); } catch { /* handled by parent */ } };
  return <section className="recipe-layout"><aside className="panel recipe-list-panel"><div className="panel-heading compact"><div><p className="eyebrow">DAFTAR RESEP</p><h2>{data.recipes.length} resep</h2></div><button type="button" className="button secondary" onClick={() => select()}>+ Baru</button></div><input className="search-input" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Cari resep…" /><div className="recipe-list">{filtered.map((recipe) => <button type="button" key={recipe.id} className={draft.id === recipe.id ? "active" : ""} onClick={() => select(recipe)}><span>{recipe.name.slice(0, 1)}</span><div><strong>{recipe.name}</strong><small>{recipe.ingredients.length} bahan · {recipe.category || "Tanpa kategori"}</small></div></button>)}{!filtered.length && <div className="empty-state compact">Belum ada resep.</div>}</div></aside><article className="panel recipe-editor"><div className="panel-heading"><div><p className="eyebrow">{draft.id ? "EDIT RESEP" : "RESEP BARU"}</p><h2>{draft.name || "Masukkan detail resep"}</h2></div>{draft.id && <button type="button" className="button danger" onClick={() => void post({ action: "delete_recipe", id: draft.id }).then(() => { select(); notify("Resep dihapus."); })}>Hapus</button>}</div><form onSubmit={save} className="recipe-form"><div className="form-grid two"><label>Nama resep<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} required /></label><label>Nama Inggris<input value={draft.englishName || ""} onChange={(event) => setDraft({ ...draft, englishName: event.target.value })} /></label></div><label>Kategori menu<input value={draft.category || ""} onChange={(event) => setDraft({ ...draft, category: event.target.value })} /></label><div className="ingredient-heading"><div><p className="eyebrow">BAHAN-BAHAN</p><small>Komposisi gram resep</small></div><button type="button" className="button ghost" onClick={() => setDraft({ ...draft, ingredients: [...draft.ingredients, { name: "", quantityGr: 0, supplierCategory: "lainnya" }] })}>+ Bahan</button></div><div className="ingredient-list">{draft.ingredients.map((item, index) => <div className="ingredient-row" key={`${draft.id || "new"}-${index}`}><input aria-label={`Nama bahan ${index + 1}`} value={item.name} onChange={(event) => patchIngredient(index, { name: event.target.value })} placeholder="Nama bahan" /><input aria-label={`Gram bahan ${index + 1}`} type="number" min="0" step="0.01" value={item.quantityGr || ""} onChange={(event) => patchIngredient(index, { quantityGr: Number(event.target.value) })} placeholder="gram" /><select aria-label={`Supplier bahan ${index + 1}`} value={item.supplierCategory} onChange={(event) => patchIngredient(index, { supplierCategory: event.target.value })}>{Object.entries(suppliers).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><button type="button" onClick={() => setDraft({ ...draft, ingredients: draft.ingredients.filter((_, itemIndex) => itemIndex !== index) })}>×</button></div>)}</div><label>Cara membuat / metode<textarea rows={6} value={draft.method || ""} onChange={(event) => setDraft({ ...draft, method: event.target.value })} placeholder="Urutan persiapan dan pengolahan…" /></label><button className="button primary wide" disabled={busy}>{busy ? "Menyimpan…" : "Simpan Resep"}</button></form></article></section>;
}

function Planning({ data, busy, post, notify }: ModuleProps) {
  const [draft, setDraft] = useState<Plan>(data.plans[0] ? JSON.parse(JSON.stringify(data.plans[0])) as Plan : freshPlan());
  const [recipeId, setRecipeId] = useState(data.recipes[0]?.id || "");
  const [ruleId, setRuleId] = useState(data.rules[0]?.id || "");
  const [month, setMonth] = useState((draft.serviceDate || today()).slice(0, 7));
  const days = useMemo(() => { const [year, mon] = month.split("-").map(Number); const blanks = new Date(year, mon - 1, 1).getDay(); const count = new Date(year, mon, 0).getDate(); return [...Array(blanks).fill(null), ...Array.from({ length: count }, (_, index) => `${month}-${String(index + 1).padStart(2, "0")}`)]; }, [month]);
  const addMenu = () => { const recipe = data.recipes.find((item) => item.id === recipeId); if (recipe?.id && ruleId) setDraft({ ...draft, menus: [...draft.menus, { recipeId: recipe.id, name: recipe.name, categoryId: ruleId }] }); };
  const save = async () => { try { const result = await post({ action: "save_plan", plan: { ...draft, status: "draft" } }); setDraft({ ...draft, id: result.id || draft.id }); notify("Rencana harian disimpan."); } catch { /* handled */ } };
  return <section className="planning-grid"><article className="panel plan-editor"><div className="panel-heading"><div><p className="eyebrow">PERENCANAAN HARIAN</p><h2>{draft.id ? "Edit rencana" : "Rencana baru"}</h2></div><button type="button" className="button ghost" onClick={() => setDraft(freshPlan())}>+ Baru</button></div><div className="form-grid two"><label>Nama rencana<input value={draft.planName} onChange={(event) => setDraft({ ...draft, planName: event.target.value })} /></label><label>Tanggal layanan<input type="date" value={draft.serviceDate} onChange={(event) => setDraft({ ...draft, serviceDate: event.target.value })} /></label></div><div className="form-grid three"><label>Porsi kecil<input type="number" min="0" value={draft.portionsSmall || ""} onChange={(event) => setDraft({ ...draft, portionsSmall: Number(event.target.value) })} /></label><label>Porsi besar<input type="number" min="0" value={draft.portionsLarge || ""} onChange={(event) => setDraft({ ...draft, portionsLarge: Number(event.target.value) })} /></label><label>Faktor layanan<select value={draft.bgnServiceDays} onChange={(event) => setDraft({ ...draft, bgnServiceDays: Number(event.target.value) })}><option value={1}>1 hari</option><option value={2}>2 hari</option></select></label></div><div className="menu-adder"><select value={recipeId} onChange={(event) => setRecipeId(event.target.value)}><option value="">Pilih resep</option>{data.recipes.map((recipe) => <option key={recipe.id} value={recipe.id}>{recipe.name}</option>)}</select><select value={ruleId} onChange={(event) => setRuleId(event.target.value)}>{data.rules.map((rule) => <option key={rule.id} value={rule.id}>{rule.name}</option>)}</select><button type="button" className="button secondary" onClick={addMenu}>Tambah menu</button></div><div className="planned-menu-list">{draft.menus.map((menu, index) => <div key={`${menu.recipeId}-${index}`}><span>{index + 1}</span><div><strong>{menu.name}</strong><small>{data.rules.find((rule) => rule.id === menu.categoryId)?.name}</small></div><button type="button" onClick={() => setDraft({ ...draft, menus: draft.menus.filter((_, itemIndex) => itemIndex !== index) })}>×</button></div>)}{!draft.menus.length && <div className="empty-state compact">Tambahkan resep ke menu harian.</div>}</div><button type="button" className="button primary wide" disabled={busy || !draft.menus.length} onClick={() => void save()}>{busy ? "Menyimpan…" : "Simpan Rencana Harian"}</button></article><aside className="panel calendar-panel"><div className="panel-heading compact"><div><p className="eyebrow">KALENDER</p><h2>Rencana tersimpan</h2></div><input type="month" value={month} onChange={(event) => setMonth(event.target.value)} /></div><div className="calendar-week">{["Min", "Sen", "Sel", "Rab", "Kam", "Jum", "Sab"].map((item) => <span key={item}>{item}</span>)}</div><div className="calendar-grid">{days.map((date, index) => date ? <button type="button" key={date} className={data.plans.some((plan) => plan.serviceDate === date) ? "has-plan" : ""} onClick={() => { const plan = data.plans.find((item) => item.serviceDate === date); setDraft(plan ? JSON.parse(JSON.stringify(plan)) as Plan : { ...freshPlan(), serviceDate: date }); }}><span>{Number(date.slice(-2))}</span>{data.plans.filter((plan) => plan.serviceDate === date).slice(0, 1).map((plan) => <small key={plan.id}>{plan.planName}</small>)}</button> : <i key={`blank-${index}`} />)}</div><div className="saved-plan-list">{data.plans.slice(0, 6).map((plan) => <button type="button" key={plan.id} onClick={() => setDraft(JSON.parse(JSON.stringify(plan)) as Plan)}><span>{plan.serviceDate.slice(-2)}</span><div><strong>{plan.planName}</strong><small>{plan.menus.length} menu · {plan.portionsSmall + plan.portionsLarge} porsi</small></div></button>)}</div></aside></section>;
}

function Estimate({ data, busy, post, notify }: ModuleProps) {
  const [planId, setPlanId] = useState(data.plans[0]?.id || "");
  const plan = data.plans.find((item) => item.id === planId) || data.plans[0];
  const [preview, setPreview] = useState<ShoppingItem[]>(plan?.shopping || []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPreview(plan?.shopping || []);
  }, [plan?.id, plan?.shopping]);
  if (!plan) return <div className="empty-state large">Buat rencana harian terlebih dahulu.</div>;
  const total = preview.reduce((sum, item) => sum + item.quantity * item.unitPrice, 0);
  const budget = (plan.portionsSmall * 8000 + plan.portionsLarge * 10000) * plan.bgnServiceDays;
  const finalize = async () => { try { await post({ action: "save_plan", plan: { ...plan, shopping: preview, status: "final" } }); notify("Estimasi final masuk ke Pusat Operasional."); } catch { /* handled */ } };
  return <section className="estimate-stack"><div className="panel estimate-toolbar"><label>Rencana<select value={plan.id} onChange={(event) => setPlanId(event.target.value)}>{data.plans.map((item) => <option key={item.id} value={item.id}>{item.serviceDate} · {item.planName}</option>)}</select></label><button type="button" className="button secondary" onClick={() => { const rows = calculateShopping(plan, data); setPreview(rows); notify(rows.length ? "Kebutuhan dihitung dari resep dan gramasi." : "Gramasi belum dapat dihitung."); }}>Hitung Estimasi</button><button type="button" className="button primary" disabled={busy || !preview.length} onClick={() => void finalize()}>{busy ? "Menyimpan…" : "Terapkan & Finalkan"}</button></div><section className="estimate-metrics"><article><span>Pagu BGN</span><strong>{money(budget)}</strong><small>{plan.bgnServiceDays} hari layanan</small></article><article><span>Estimasi belanja</span><strong>{money(total)}</strong><small>{preview.length} bahan</small></article><article className={budget >= total ? "positive" : "negative"}><span>Selisih pagu</span><strong>{money(budget - total)}</strong><small>{budget >= total ? "dalam pagu" : "melebihi pagu"}</small></article></section><article className="panel estimate-table"><div className="panel-heading"><div><p className="eyebrow">KALKULASI & DAFTAR BELANJA</p><h2>{plan.planName}</h2></div><span className={`plan-status ${plan.status}`}>{plan.status === "final" ? "FINAL" : "DRAF"}</span></div><div className="table-wrap"><table><thead><tr><th>Bahan</th><th>Kebutuhan</th><th>Supplier</th><th>Harga/kg</th><th>Total</th></tr></thead><tbody>{preview.map((item) => <tr key={`${item.supplierCategory}-${item.itemName}`}><td><strong>{item.itemName}</strong><small>{item.note}</small></td><td>{item.quantity.toLocaleString("id-ID", { maximumFractionDigits: 3 })} {item.unit}</td><td>{suppliers[item.supplierCategory] || item.supplierCategory}</td><td>{money(item.unitPrice)}</td><td><strong>{money(item.quantity * item.unitPrice)}</strong></td></tr>)}{!preview.length && <tr><td colSpan={5} className="table-empty">Klik Hitung Estimasi. Lengkapi resep, porsi, gramasi, dan harga.</td></tr>}</tbody><tfoot><tr><td colSpan={4}>GRAND TOTAL</td><td>{money(total)}</td></tr></tfoot></table></div></article></section>;
}

function Documents({ data }: { data: KitchenData }) {
  const [planId, setPlanId] = useState(data.plans[0]?.id || ""); const [tab, setTab] = useState<"sop" | "po">("sop");
  const plan = data.plans.find((item) => item.id === planId) || data.plans[0];
  if (!plan) return <div className="empty-state large">Belum ada rencana untuk SOP atau surat pembelian.</div>;
  const grouped = plan.shopping.reduce<Record<string, ShoppingItem[]>>((acc, item) => { (acc[item.supplierCategory] ||= []).push(item); return acc; }, {});
  const exportExcel = () => downloadXlsx(`PO_${data.unitId}_${plan.serviceDate}.xlsx`, "Surat Pembelian", [["Dapur", "Tanggal", "Bahan", "Jumlah", "Satuan", "Harga", "Total", "Supplier"], ...plan.shopping.map((item) => [data.unit.name, plan.serviceDate, item.itemName, item.quantity, item.unit, item.unitPrice, item.quantity * item.unitPrice, suppliers[item.supplierCategory] || item.supplierCategory])]);
  const share = async () => { const text = `*SURAT PEMBELIAN ${data.unit.name.toUpperCase()}*\nTanggal: ${plan.serviceDate}\n\n${Object.entries(grouped).map(([category, items]) => `*${suppliers[category] || category}*\n${items.map((item, index) => `${index + 1}. ${item.itemName} — ${item.quantity} ${item.unit}`).join("\n")}`).join("\n\n")}\n\nMohon konfirmasi ketersediaan dan pengiriman.`; if (navigator.share) await navigator.share({ title: `PO ${data.unit.name}`, text }); else window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank", "noopener,noreferrer"); };
  return <section className="documents-stack"><div className="panel document-toolbar"><label>Rencana<select value={plan.id} onChange={(event) => setPlanId(event.target.value)}>{data.plans.map((item) => <option key={item.id} value={item.id}>{item.serviceDate} · {item.planName}</option>)}</select></label><div className="document-tabs"><button type="button" className={tab === "sop" ? "active" : ""} onClick={() => setTab("sop")}>SOP Harian</button><button type="button" className={tab === "po" ? "active" : ""} onClick={() => setTab("po")}>Surat Pembelian</button></div><button type="button" className="button ghost" onClick={exportExcel} disabled={!plan.shopping.length}>Export Excel</button><button type="button" className="button secondary" onClick={() => void share()} disabled={!plan.shopping.length}>Bagikan WA</button></div>{tab === "sop" ? <article className="panel printable sop-document"><header><p>STANDAR OPERASIONAL PRODUKSI</p><h2>{plan.planName}</h2><span>{data.unit.name} · {plan.serviceDate} · {plan.portionsSmall + plan.portionsLarge} porsi</span></header>{plan.menus.map((menu, index) => { const recipe = data.recipes.find((item) => item.id === menu.recipeId); return <section key={`${menu.recipeId}-${index}`}><h3>{index + 1}. {menu.name}</h3><div className="sop-columns"><div><strong>Bahan acuan</strong><ul>{recipe?.ingredients.map((item) => <li key={item.name}>{item.name}: {item.quantityGr} g komposisi</li>)}</ul></div><div><strong>Metode produksi</strong><p>{recipe?.method || "Ikuti standar persiapan, pemasakan, QC, dan holding aman."}</p></div></div></section>; })}<footer>Checklist: penerimaan · sortasi · timbang · persiapan terpisah · pemasakan · QC rasa/suhu · pemorsian · distribusi · sanitasi.</footer></article> : <article className="panel printable po-document"><header><p>SURAT PEMBELIAN BAHAN</p><h2>{data.unit.name}</h2><span>{plan.planName} · kebutuhan {plan.serviceDate}</span></header>{Object.entries(grouped).map(([category, items]) => <section key={category}><h3>{suppliers[category] || category}</h3><table><thead><tr><th>No</th><th>Barang</th><th>Jumlah</th><th>Catatan</th></tr></thead><tbody>{items.map((item, index) => <tr key={item.itemName}><td>{index + 1}</td><td>{item.itemName}</td><td>{item.quantity} {item.unit}</td><td>{item.note}</td></tr>)}</tbody></table></section>)}{!plan.shopping.length && <div className="empty-state">Finalkan estimasi terlebih dahulu.</div>}</article>}</section>;
}

function Nutrition({ data }: { data: KitchenData }) {
  const [planId, setPlanId] = useState(data.plans[0]?.id || ""); const [mode, setMode] = useState("nutrition"); const [prompt, setPrompt] = useState("Audit keseimbangan menu, variasi, kewajaran gramasi, dan risiko komposisi yang perlu diperiksa."); const [answer, setAnswer] = useState(""); const [provider, setProvider] = useState(""); const [loading, setLoading] = useState(false); const [error, setError] = useState("");
  const plan = data.plans.find((item) => item.id === planId) || data.plans[0];
  const run = async () => { setLoading(true); setError(""); setAnswer(""); try { const recipes = plan?.menus.map((menu) => data.recipes.find((recipe) => recipe.id === menu.recipeId)).filter(Boolean) || data.recipes.slice(0, 12); const result = await json<{ text: string; provider: string; model: string }>("/api/ai", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode, prompt, unitName: data.unit.name, context: { plan, recipes } }) }); setAnswer(result.text); setProvider(`${result.provider} · ${result.model}`); } catch (aiError) { setError(aiError instanceof Error ? aiError.message : "AI gagal."); } finally { setLoading(false); } };
  return <section className="nutrition-grid"><article className="panel nutrition-compose"><div className="ai-orb">AI</div><p className="eyebrow">LAPORAN NUTRISI & AUDIT</p><h2>AI membaca rencana dan resep dapur.</h2>{plan && <label>Rencana<select value={plan.id} onChange={(event) => setPlanId(event.target.value)}>{data.plans.map((item) => <option key={item.id} value={item.id}>{item.serviceDate} · {item.planName}</option>)}</select></label>}<div className="ai-modes">{[["nutrition", "Audit nutrisi"], ["audit", "Audit resep"], ["sop", "Perbaiki SOP"], ["chat", "Tanya bebas"]].map(([key, label]) => <button type="button" key={key} className={mode === key ? "active" : ""} onClick={() => setMode(key)}>{label}</button>)}</div><textarea rows={8} value={prompt} onChange={(event) => setPrompt(event.target.value)} /><button type="button" className="button primary wide" disabled={loading} onClick={() => void run()}>{loading ? "Menganalisis…" : "Jalankan Analisis AI"}</button>{error && <div className="alert error compact-alert">{error}</div>}</article><article className="panel ai-answer"><div className="panel-heading compact"><div><p className="eyebrow">HASIL ANALISIS</p><h2>{provider || "Belum dijalankan"}</h2></div></div>{answer ? <div className="answer-text">{answer}</div> : <div className="answer-empty"><strong>Konteks otomatis</strong><p>{plan ? `${plan.menus.length} menu dan resep terkait.` : `${data.recipes.length} resep dapur.`}</p></div>}</article></section>;
}

type ModuleProps = { data: KitchenData; busy: boolean; post: (payload: Record<string, unknown>) => Promise<{ ok: true; id?: string }>; notify: (message: string) => void };
function Master({ data, busy, post, notify }: ModuleProps) {
  const [price, setPrice] = useState({ itemName: "", price: "", purchaseUnit: "kg", category: "lain_lain" }); const [rule, setRule] = useState({ id: "", name: "", smallGrams: "", largeGrams: "" });
  const savePrice = async (event: FormEvent) => { event.preventDefault(); try { await post({ action: "save_price", price: { ...price, price: Number(price.price) } }); setPrice({ itemName: "", price: "", purchaseUnit: "kg", category: "lain_lain" }); notify("Master item dan kategori operasional disimpan."); } catch { /* handled */ } };
  const saveRule = async (event: FormEvent) => { event.preventDefault(); try { await post({ action: "save_rule", rule: { ...rule, smallGrams: Number(rule.smallGrams), largeGrams: Number(rule.largeGrams) } }); setRule({ id: "", name: "", smallGrams: "", largeGrams: "" }); notify("Aturan gramasi disimpan."); } catch { /* handled */ } };
  return <section className="master-grid"><article className="panel master-card"><div className="panel-heading compact"><div><p className="eyebrow">MASTER OPERASIONAL</p><h2>Item, kategori, dan harga</h2></div><span>{data.prices.length} item</span></div><form className="master-inline-form" onSubmit={savePrice}><input value={price.itemName} onChange={(event) => setPrice({ ...price, itemName: event.target.value })} placeholder="Nama item" required /><input type="number" min="0" value={price.price} onChange={(event) => setPrice({ ...price, price: event.target.value })} placeholder="Harga satuan" required /><select value={price.purchaseUnit} onChange={(event) => setPrice({ ...price, purchaseUnit: event.target.value })}><option>kg</option><option>liter</option><option>pcs</option><option>galon</option><option>pack</option><option>dus</option><option>isi ulang</option></select><select value={price.category} onChange={(event) => setPrice({ ...price, category: event.target.value })}>{operationalCategories.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><button className="button primary" disabled={busy}>Simpan</button></form><div className="master-list">{data.prices.map((item) => <div key={item.id}><span><strong>{item.itemName}</strong><small>{operationalCategoryLabels[item.category] || item.category} · per {item.purchaseUnit}</small></span><em>{money(item.price)}</em><button type="button" onClick={() => setPrice({ itemName: item.itemName, price: String(item.price), purchaseUnit: item.purchaseUnit, category: item.category })}>Edit</button><button type="button" onClick={() => void post({ action: "delete_price", id: item.id })}>×</button></div>)}</div></article><article className="panel master-card"><div className="panel-heading compact"><div><p className="eyebrow">ATURAN GRAMASI</p><h2>Porsi kecil & besar</h2></div><span>{data.rules.length} kategori</span></div><form className="master-inline-form rule" onSubmit={saveRule}><input value={rule.name} onChange={(event) => setRule({ ...rule, name: event.target.value })} placeholder="Nama kategori" required /><input type="number" min="0" value={rule.smallGrams} onChange={(event) => setRule({ ...rule, smallGrams: event.target.value })} placeholder="gram kecil" required /><input type="number" min="0" value={rule.largeGrams} onChange={(event) => setRule({ ...rule, largeGrams: event.target.value })} placeholder="gram besar" required /><button className="button primary" disabled={busy}>Simpan</button></form><div className="rule-list">{data.rules.map((item) => <button type="button" key={item.id} onClick={() => setRule({ id: item.id, name: item.name, smallGrams: String(item.smallGrams), largeGrams: String(item.largeGrams) })}><span>{item.name.slice(0, 1)}</span><div><strong>{item.name}</strong><small>{item.smallGrams} g kecil · {item.largeGrams} g besar</small></div></button>)}</div></article></section>;
}
