"use client";

import { useEffect, useMemo, useState } from "react";

type Props = { unit: { id: string; name: string }; workflow: { id: number }; date: string };
type MasterItem = { recordKey: string; itemName: string; category: string; unit: string; unitPrice: number };
type Line = { itemName: string; category: string; quantity: number; unit: string; unitPrice: number; lineTotal: number };
type Document = { id: number; site: string; documentType: string; documentNumber: string; serviceDate: string; status: string; header: Record<string, unknown>; total: number; items: Line[] };

const money = (value: number) => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(value || 0);
const dateLabel = (value: string) => new Intl.DateTimeFormat("id-ID", { timeZone: "UTC", day: "numeric", month: "long", year: "numeric" }).format(new Date(value + "T00:00:00Z"));

export default function InvoiceDocumentsClient({ unit, workflow, date }: Props) {
  const site = unit.id.toUpperCase() as "MAJA" | "CEMPLANG";
  const [masters, setMasters] = useState<MasterItem[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [type, setType] = useState<"OPERASIONAL" | "BAHAN_BAKU">("OPERASIONAL");
  const [selected, setSelected] = useState("");
  const [qty, setQty] = useState("1");
  const [lines, setLines] = useState<Line[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    const [masterResponse, documentResponse] = await Promise.all([
      fetch("/api/accountant-documents/master?site=" + site, { credentials: "include" }),
      fetch("/api/accountant-documents?site=" + site + "&service_date=" + date, { credentials: "include" }),
    ]);
    const master = await masterResponse.json() as { items?: MasterItem[]; detail?: string };
    const docs = await documentResponse.json() as { documents?: Document[]; detail?: string };
    if (!masterResponse.ok) throw new Error(master.detail || "Master item gagal dimuat.");
    if (!documentResponse.ok) throw new Error(docs.detail || "Dokumen gagal dimuat.");
    setMasters(master.items || []);
    setDocuments(docs.documents || []);
  };

  useEffect(() => { void load().catch((e) => setError(e instanceof Error ? e.message : "Gagal memuat dokumen.")); }, [site, date]);

  const selectedItem = masters.find((item) => item.recordKey === selected);
  const total = useMemo(() => lines.reduce((sum, line) => sum + line.lineTotal, 0), [lines]);

  const addLine = () => {
    if (!selectedItem) return;
    const quantity = Number(qty);
    if (!Number.isFinite(quantity) || quantity <= 0) return;
    setLines((current) => [...current, { itemName: selectedItem.itemName, category: selectedItem.category || "LAIN_LAIN", quantity, unit: selectedItem.unit || "unit", unitPrice: selectedItem.unitPrice || 0, lineTotal: Math.round(quantity * (selectedItem.unitPrice || 0)) }]);
    setSelected("");
    setQty("1");
  };

  const generate = async () => {
    if (!lines.length) return;
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/accountant-documents", { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ site, document_type: type, service_date: date, items: lines, header_payload: { issuerName: unit.name, issuerAddress: unit.id === "maja" ? "Maja Baru" : "Cemplang 02", workflowId: workflow.id } }) });
      const result = await response.json() as { document?: Document; detail?: string };
      if (!response.ok) throw new Error(result.detail || "Invoice gagal dibuat.");
      setLines([]);
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Invoice gagal dibuat."); }
    finally { setBusy(false); }
  };

  const finalize = async (document: Document) => {
    setBusy(true);
    try {
      const response = await fetch("/api/accountant-documents/" + document.id + "/finalize", { method: "PATCH", credentials: "include" });
      if (!response.ok) throw new Error("Dokumen gagal difinalkan.");
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Dokumen gagal difinalkan."); }
    finally { setBusy(false); }
  };

  const print = (document: Document) => {
    const popup = window.open("", "_blank", "noopener,noreferrer,width=900,height=700");
    if (!popup) return;
    const rows = document.items.map((line, index) => "<tr><td>" + (index + 1) + "</td><td>" + line.itemName + "</td><td>" + line.category + "</td><td>" + line.quantity + " " + line.unit + "</td><td>" + money(line.unitPrice) + "</td><td>" + money(line.lineTotal) + "</td></tr>").join("");
    const title = document.documentType === "OPERASIONAL" ? "INVOICE OPERASIONAL" : "INVOICE BAHAN BAKU";
    popup.document.write("<html><head><title>" + document.documentNumber + "</title><style>body{font-family:Arial;margin:42px;color:#17231d}header{border-bottom:2px solid #173d2a;padding-bottom:14px;display:flex;justify-content:space-between}h1{text-align:center;font-size:22px;margin:28px 0 12px}table{width:100%;border-collapse:collapse;margin-top:20px}th,td{border:1px solid #555;padding:8px;font-size:12px}th{background:#e7f1e8}.total{text-align:right;font-size:17px;font-weight:bold;margin-top:14px}.sign{display:flex;justify-content:space-between;text-align:center;margin-top:80px}.sign div{width:35%}</style></head><body><header><div><strong>" + unit.name + "</strong><br>" + String(document.header?.issuerAddress || "") + "</div><div>Nomor: <strong>" + document.documentNumber + "</strong><br>Tanggal: " + dateLabel(document.serviceDate) + "</div></header><h1>" + title + "</h1><table><thead><tr><th>No</th><th>Item</th><th>Kategori</th><th>Qty</th><th>Harga</th><th>Total</th></tr></thead><tbody>" + rows + "</tbody></table><div class='total'>TOTAL: " + money(document.total) + "</div><div class='sign'><div>Mengetahui,<br><br><br><br>__________________<br>Pihak SPPG</div><div>Dibuat oleh,<br><br><br><br>__________________<br>Akuntan</div></div><script>window.onload=()=>window.print()</script></body></html>");
    popup.document.close();
  };

  return <section className="content-stack"><article className="panel"><div className="panel-heading"><div><p className="eyebrow">DOKUMEN AKUNTAN</p><h2>Pilih master item lalu generate</h2><p>Nomor invoice dibuat otomatis. Invoice operasional dapat dibuat berkali-kali pada tanggal yang sama dengan nomor 001, 002, 003, dan seterusnya.</p></div></div><div className="form-grid"><label>Jenis<select value={type} onChange={(e) => setType(e.target.value as "OPERASIONAL" | "BAHAN_BAKU")}><option value="OPERASIONAL">Invoice Operasional</option><option value="BAHAN_BAKU">Invoice Bahan Baku</option></select></label><label>Item master<select value={selected} onChange={(e) => setSelected(e.target.value)}><option value="">Pilih item…</option>{masters.map((item) => <option key={item.recordKey} value={item.recordKey}>{item.itemName} · {money(item.unitPrice)}/{item.unit}</option>)}</select></label><label>Jumlah<input type="number" min="0.001" step="0.001" value={qty} onChange={(e) => setQty(e.target.value)} /></label><button className="button primary" type="button" onClick={addLine}>Tambah item</button></div>{lines.length > 0 && <div className="table-wrap"><table><thead><tr><th>Item</th><th>Kategori</th><th>Qty</th><th>Harga</th><th>Total</th><th /></tr></thead><tbody>{lines.map((line, index) => <tr key={index}><td>{line.itemName}</td><td>{line.category}</td><td>{line.quantity} {line.unit}</td><td>{money(line.unitPrice)}</td><td>{money(line.lineTotal)}</td><td><button className="button ghost" type="button" onClick={() => setLines(lines.filter((_, i) => i !== index))}>Hapus</button></td></tr>)}</tbody></table><button className="button primary" type="button" onClick={() => void generate()} disabled={busy}>Generate nomor & invoice · {money(total)}</button></div>}{error && <div className="alert error">{error}</div>}</article><article className="panel"><div className="panel-heading compact"><div><p className="eyebrow">REGISTER DOKUMEN</p><h2>{documents.length} dokumen pada {dateLabel(date)}</h2></div></div><div className="table-wrap"><table><thead><tr><th>Nomor</th><th>Jenis</th><th>Total</th><th>Status</th><th>Aksi</th></tr></thead><tbody>{documents.map((document) => <tr key={document.id}><td><strong>{document.documentNumber}</strong></td><td>{document.documentType.replaceAll("_", " ")}</td><td>{money(document.total)}</td><td>{document.status}</td><td><button className="button ghost" type="button" onClick={() => print(document)}>Cetak</button>{document.status !== "FINAL" && <button className="button ghost" type="button" onClick={() => void finalize(document)} disabled={busy}>Finalkan</button>}</td></tr>)}</tbody></table>{documents.length === 0 && <div className="empty-state compact">Belum ada invoice untuk tanggal ini.</div>}</div></article></section>;
}
