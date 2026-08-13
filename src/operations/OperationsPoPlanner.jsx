import React, { useEffect, useMemo, useState } from "react";
import { CalendarDays, CheckCircle2, ClipboardCopy, MessageCircle, RefreshCw, ShoppingCart } from "lucide-react";
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

function normalize(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
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
  if (/\b(bahan kering|sembako|dry goods|packaging)\b/.test(category)) {
    return { vendor: "KOPERASI", method: "confirmed_internal_rule" };
  }
  if (/\b(sayur|buah|bumbu|vegetable|fruit)\b/.test(category)) {
    return { vendor: "HOLIL", method: "category_rule" };
  }

  return { vendor: "", method: "unassigned" };
}

function poMessage(po) {
  const lines = [
    `*PO SPPG ${po.site || ""}*`,
    `Vendor: ${po.vendor_code || "-"}`,
    `Tanggal distribusi: ${po.distribution_date || "-"}`,
    `PO: ${po.po_code || "-"}${po.revision_no ? ` / Rev ${po.revision_no}` : ""}`,
    "",
  ];
  (po.items || []).forEach((item, index) => {
    lines.push(`${index + 1}. ${item.item_name} — ${qty(item.po_qty)} ${item.unit || ""}`.trim());
  });
  lines.push("", "Mohon konfirmasi pesanan di atas. Terima kasih.");
  return lines.join("\n");
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  document.body.removeChild(area);
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

  useEffect(() => {
    if (fixedSite && site !== fixedSite) setSite(fixedSite);
  }, [fixedSite, site]);

  const activeSite = fixedSite || site;

  const applyPlanningSnapshot = (snapshot) => {
    setPlanningSnapshot(snapshot || null);
    setDraftItems((snapshot?.items || []).map((item) => {
      const assignment = safeVendorForPlanningItem(item, activeSite);
      return {
        planning_snapshot_item_id: item.id,
        item_code: item.item_code || null,
        item_name: item.item_name,
        category_code: item.category_code || "",
        planned_qty: item.planned_qty == null ? 0 : Number(item.planned_qty),
        po_qty: item.planned_qty == null ? 0 : Number(item.planned_qty),
        unit: item.unit || "",
        planning_price: item.planning_price == null ? null : Number(item.planning_price),
        vendor_code: assignment.vendor,
        assignment_method: assignment.method,
        notes: item.notes || "",
      };
    }));
  };

  const load = async () => {
    setLoading(true);
    setError("");
    setMessage("");
    try {
      const [scheduleData, poData, snapshotsData, vendorsData] = await Promise.all([
        operationsApi.previewPoSchedule({ distributionDate, cookingDate, site: activeSite }),
        operationsApi.getPurchaseOrders({ site: activeSite, limit: 50 }),
        operationsApi.getPlanningSnapshots({ site: activeSite, distributionDate, activeOnly: true }),
        operationsApi.getReferenceVendors(activeSite),
      ]);
      setSchedule(scheduleData?.items || []);
      setPurchaseOrders(poData?.items || []);

      const uniqueVendors = new Map(FALLBACK_VENDORS.map(([code, name]) => [code, { code, name }]));
      (vendorsData?.items || []).forEach((item) => {
        if (item?.code) uniqueVendors.set(String(item.code).toUpperCase(), { code: String(item.code).toUpperCase(), name: item.name || item.code });
      });
      setVendorOptions(Array.from(uniqueVendors.values()).sort((a, b) => a.name.localeCompare(b.name, "id")));

      const snapshots = snapshotsData?.items || [];
      if (!snapshots.length) {
        applyPlanningSnapshot(null);
      } else {
        const detail = await operationsApi.getPlanningSnapshot(snapshots[0].id);
        applyPlanningSnapshot(detail);
      }
    } catch (err) {
      setError(err.message || "Gagal mengambil planning/jadwal/PO vendor");
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
    const lines = draftItems.filter((item) => item.vendor_code === vendor && Number(item.po_qty || 0) > 0);
    if (!lines.length) return;

    const unresolved = lines.some((item) => !item.vendor_code);
    if (unresolved) {
      setError("Masih ada item tanpa vendor. Pilih vendor sebelum membuat draft PO.");
      return;
    }

    const code = `PO-${activeSite}-${distributionDate.replaceAll("-", "")}-${vendor}`;
    const confirmed = window.confirm(
      `Buat DRAFT PO ${vendor} untuk ${activeSite} tanggal distribusi ${distributionDate}?\n\n` +
      `${lines.length} item akan disimpan ke PostgreSQL. planned_qty tetap tidak diubah.`
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
          notes: item.notes || null,
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

  const loadPoText = async (poId) => {
    setActionId(poId);
    setError("");
    try {
      const detail = await operationsApi.getPurchaseOrder(poId);
      return poMessage(detail);
    } catch (err) {
      setError(err.message || "Gagal membuka detail PO");
      return "";
    } finally {
      setActionId(null);
    }
  };

  const copyPo = async (poId) => {
    const text = await loadPoText(poId);
    if (!text) return;
    await copyText(text);
    setMessage("Teks PO sudah disalin. Tinggal paste ke chat vendor.");
  };

  const openWhatsApp = async (poId) => {
    const text = await loadPoText(poId);
    if (!text) return;
    window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank", "noopener,noreferrer");
    setMessage("WhatsApp dibuka dengan teks PO siap diteruskan. Pilih chat vendor yang benar sebelum kirim.");
  };

  return (
    <div className="ops-domain-stack">
      <section className="ops-module">
        <div className="ops-module-header">
          <div>
            <span className="ops-kicker">KALKULATOR → PO</span>
            <h3>Draft PO Otomatis dari Planning</h3>
            <p>Planning dari Kalkulator tetap sumber awal. planned_qty tidak diubah; po_qty boleh Anda koreksi khusus untuk PO. Harga vendor tidak diarang dan tidak diisi otomatis dari planning_price.</p>
          </div>
          <button type="button" onClick={load} disabled={loading}><RefreshCw size={15} /> Refresh</button>
        </div>

        <div className="ops-form-grid">
          <label>Site<select value={activeSite} disabled={Boolean(fixedSite)} onChange={(e) => setSite(e.target.value)}><option value="MAJA">Maja</option><option value="CEMPLANG">Cemplang</option></select></label>
          <label>Distribusi<input type="date" value={distributionDate} onChange={(e) => setDistributionDate(e.target.value)} /></label>
          <label>Masak<input type="date" value={cookingDate} onChange={(e) => setCookingDate(e.target.value)} /></label>
        </div>

        {error && <div className="ops-error">{error}</div>}
        {message && <div className="ops-success">{message}</div>}

        {!loading && !planningSnapshot && (
          <div className="ops-notice">
            Belum ada planning snapshot Kalkulator untuk {activeSite} tanggal {distributionDate}. Pusat Resep, Master Harga, dan Kalkulator tidak diubah; PO tidak dibuat dari data tebakan.
          </div>
        )}

        {planningSnapshot && (
          <>
            <div className="ops-summary-strip">
              <span>Snapshot <strong>#{planningSnapshot.id}</strong></span>
              <span>Sumber <strong>{planningSnapshot.source_system || "-"}</strong></span>
              <span>Versi <strong>{planningSnapshot.source_version || "-"}</strong></span>
              <span>Item <strong>{draftItems.length}</strong></span>
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
                    <button type="button" onClick={() => createVendorPo(group.vendor)} disabled={creatingVendor === group.vendor || group.items.every((x) => Number(x.po_qty || 0) <= 0)}>
                      <ShoppingCart size={15} /> {creatingVendor === group.vendor ? "Menyimpan..." : "Buat Draft PO"}
                    </button>
                  )}
                </div>
                <div className="ops-table-wrap">
                  <table className="ops-table">
                    <thead><tr><th>Item</th><th>Kategori</th><th>Planned Qty</th><th>PO Qty</th><th>Unit</th><th>Planning Price</th><th>Vendor</th><th>Dasar</th></tr></thead>
                    <tbody>
                      {group.items.map((item) => (
                        <tr key={item.planning_snapshot_item_id}>
                          <td><strong>{item.item_name}</strong></td>
                          <td>{item.category_code || "-"}</td>
                          <td>{qty(item.planned_qty)}</td>
                          <td><input className="ops-qty-input" type="number" min="0" step="0.0001" value={item.po_qty} onChange={(e) => updateDraftItem(item.planning_snapshot_item_id, { po_qty: Number(e.target.value) })} /></td>
                          <td>{item.unit || "-"}</td>
                          <td>{item.planning_price == null ? "-" : money(item.planning_price)}</td>
                          <td>
                            <select value={item.vendor_code} onChange={(e) => updateDraftItem(item.planning_snapshot_item_id, { vendor_code: e.target.value, assignment_method: "manual" })}>
                              <option value="">Pilih vendor</option>
                              {vendorOptions.map((vendor) => <option key={vendor.code} value={vendor.code}>{vendor.name}</option>)}
                            </select>
                          </td>
                          <td>{item.assignment_method === "manual" ? "Manual" : item.assignment_method === "preferred_vendor" ? "Preferred vendor dari planning" : item.assignment_method === "unassigned" ? "Perlu dipilih" : "Rule operasional"}</td>
                        </tr>
                      ))}
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
          <div>
            <span className="ops-kicker">JADWAL PO</span>
            <h3>Preview Waktu Pesan Vendor</h3>
            <p>Tanggal masak menjadi anchor lead time. Jadwal hanya membantu timing; tidak membuat PO atau mengirim pesan otomatis.</p>
          </div>
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
          <div>
            <span className="ops-kicker">PO TERCATAT</span>
            <h3>Purchase Order Aktual</h3>
            <p>Qty PO tetap terpisah dari planning, receiving, invoice, dan actual usage. Copy/WhatsApp hanya menyiapkan teks; sistem tidak menganggap PO sudah terkirim sebelum ada status/evidence.</p>
          </div>
        </div>
        <div className="ops-table-wrap">
          <table className="ops-table">
            <thead><tr><th>Distribusi</th><th>PO</th><th>Vendor</th><th>Revisi</th><th>Item</th><th>Total PO</th><th>Status</th><th>Aksi Manual</th></tr></thead>
            <tbody>
              {purchaseOrders.map((po) => (
                <tr key={po.id}>
                  <td>{po.distribution_date || "-"}</td>
                  <td><strong>{po.po_code}</strong><div className="ops-muted">{po.sent_at ? `Sent: ${po.sent_at}` : "Belum ada bukti kirim"}</div></td>
                  <td>{po.vendor_code}</td>
                  <td>{po.revision_no}</td>
                  <td>{po.item_count}</td>
                  <td>{money(po.po_total)}</td>
                  <td>{po.status}</td>
                  <td>
                    <div className="ops-row-actions">
                      <button type="button" onClick={() => copyPo(po.id)} disabled={actionId === po.id}><ClipboardCopy size={14} /> Copy PO</button>
                      <button type="button" onClick={() => openWhatsApp(po.id)} disabled={actionId === po.id}><MessageCircle size={14} /> WhatsApp</button>
                    </div>
                  </td>
                </tr>
              ))}
              {!loading && purchaseOrders.length === 0 && <tr><td colSpan="8" className="ops-empty-cell">Belum ada PO tercatat untuk site ini.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
