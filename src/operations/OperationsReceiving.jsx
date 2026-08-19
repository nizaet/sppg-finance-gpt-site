import React, { useEffect, useMemo, useState } from "react";
import { CheckCircle2, MessageSquareText, RefreshCw, Search } from "lucide-react";
import { operationsApi } from "./apiClient";

function pct(value){ return `${Math.round(Number(value || 0) * 100)}%`; }
function fmtQty(value){ return value === null || value === undefined ? "-" : Number(value).toLocaleString("id-ID", { maximumFractionDigits: 4 }); }
function compactDateTime(value){ return value ? String(value).replace("T", " ").replace(/\.\d+Z?$/, "") : "-"; }
function itemLabel(item){ return item?.po_item_name || item?.reported_item_name || "Item"; }
function poLookup(value){
  const raw = String(value || "").trim();
  if (!raw) return { poId: "", poCode: "", search: "" };
  if (/^\d+$/.test(raw)) return { poId: raw, poCode: "", search: "" };
  if (/^PO[-_]/i.test(raw)) return { poId: "", poCode: raw, search: "" };
  return { poId: "", poCode: "", search: raw };
}

export default function OperationsReceiving({ fixedSite = "" }){
  const [site,setSite]=useState(fixedSite || "MAJA");
  const [items,setItems]=useState([]);
  const [variance,setVariance]=useState([]);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const [text,setText]=useState("");
  const [vendor,setVendor]=useState("");
  const [reporter,setReporter]=useState("");
  const [preview,setPreview]=useState(null);
  const [saving,setSaving]=useState(false);
  const [message,setMessage]=useState("");
  const [historyFrom,setHistoryFrom]=useState("");
  const [historyTo,setHistoryTo]=useState("");
  const [historyVendor,setHistoryVendor]=useState("");
  const [historyPo,setHistoryPo]=useState("");
  const [historySearch,setHistorySearch]=useState("");

  useEffect(()=>{
    if(fixedSite && site !== fixedSite){ setSite(fixedSite); setPreview(null); }
  },[fixedSite,site]);

  const activeSite = fixedSite || site;

  const load=async()=>{
    setLoading(true); setError("");
    try{
      const po = poLookup(historyPo);
      const search = historySearch.trim() || po.search;
      const [d,v]=await Promise.all([
        operationsApi.getGoodsReceipts({
          site: activeSite,
          vendor: historyVendor.trim().toUpperCase(),
          poId: po.poId,
          poCode: po.poCode,
          fromDate: historyFrom,
          toDate: historyTo,
          search,
          limit: 150,
        }),
        operationsApi.getReceivingVariance({site: activeSite}),
      ]);
      setItems(d?.items||[]); setVariance(v?.items||[]);
    }catch(e){setError(e.message||"Gagal mengambil penerimaan");}
    finally{setLoading(false);}
  };
  useEffect(()=>{load();},[activeSite]);
  useEffect(()=>{
    const onReceiptSaved=(event)=>{
      const eventSite=String(event?.detail?.site||"").toUpperCase();
      if(eventSite && eventSite!==String(activeSite).toUpperCase()) return;
      load();
    };
    window.addEventListener("sppg:goods-receipt-saved",onReceiptSaved);
    return()=>window.removeEventListener("sppg:goods-receipt-saved",onReceiptSaved);
  },[activeSite,historyFrom,historyTo,historyVendor,historyPo,historySearch]);

  const payload=useMemo(()=>({
    site: activeSite,
    text,
    vendor_code: vendor.trim() || null,
    reporter: reporter.trim() || null,
  }),[activeSite,text,vendor,reporter]);

  const runPreview=async()=>{
    if(!text.trim()) return;
    setSaving(true); setError(""); setMessage(""); setPreview(null);
    try{ setPreview(await operationsApi.previewWhatsAppReceipt(payload)); }
    catch(e){ setError(e.message||"Gagal mencocokkan chat dengan PO"); }
    finally{ setSaving(false); }
  };

  const commit=async()=>{
    if(!preview?.canCommit || !preview?.purchaseOrderId) return;
    setSaving(true); setError(""); setMessage("");
    try{
      const data=await operationsApi.commitWhatsAppReceipt({...payload,purchase_order_id:preview.purchaseOrderId});
      setPreview(data);
      setMessage(data?.duplicate
        ? `Penerimaan sudah pernah tersimpan (ID ${data.receiptId}); movement stok tetap dicek idempotent (${data.stockDuplicates || 0} sudah ada).`
        : `Penerimaan tersimpan. Receipt ID ${data.receiptId}; status PO ${data.purchaseOrderStatus}; ${data.stockInserted || 0} item diterima masuk ke stok gudang.`);
      await load();
    }catch(e){setError(e.message||"Gagal menyimpan penerimaan");}
    finally{setSaving(false);}
  };

  return <section className="ops-module">
    <div className="ops-module-header">
      <div><span className="ops-kicker">RECEIVING / WHATSAPP</span><h3>Penerimaan Barang</h3><p>Input terkonfirmasi dari halaman ini maupun GPTS masuk ke riwayat PostgreSQL yang sama. Qty diterima yang disetujui otomatis menambah stok gudang; mengirim PO saja tidak menambah stok. Riwayat di bawah sekarang menampilkan detail item per receipt, PO, tanggal terima, dan tanggal distribusi.</p></div>
      <div className="ops-inline-controls"><select value={activeSite} disabled={Boolean(fixedSite)} onChange={e=>{setSite(e.target.value);setPreview(null);}}><option value="MAJA">Maja</option><option value="CEMPLANG">Cemplang</option></select><button onClick={load} disabled={loading}><RefreshCw size={15}/> Refresh</button></div>
    </div>

    <div className="ops-parse-result">
      <div><MessageSquareText size={17}/><strong>Tempel laporan dari grup WhatsApp</strong></div>
      <div className="ops-form-grid">
        <label>Vendor (opsional)<input value={vendor} onChange={e=>setVendor(e.target.value.toUpperCase())} placeholder="HOLIL / WIKIAN / KOPERASI..."/></label>
        <label>Pelapor (opsional)<input value={reporter} onChange={e=>setReporter(e.target.value)} placeholder="Nama staf / kepala dapur"/></label>
      </div>
      <textarea className="ops-chat-input" rows={6} value={text} onChange={e=>setText(e.target.value)} placeholder={'Contoh:\nBarang Holil sudah datang\nWortel 105 kg\nSawi putih 82 kg\nBawang merah 31 kg'} />
      <div className="ops-chat-actions"><button onClick={runPreview} disabled={saving||!text.trim()}><Search size={16}/> {saving?"Mencocokkan...":"Preview & Cocokkan ke PO"}</button></div>
    </div>

    {error&&<div className="ops-error">{error}</div>}
    {message&&<div className="ops-success">{message}</div>}

    {preview&&<div className="ops-parse-result">
      <div><strong>Hasil pencocokan</strong></div>
      <dl>
        <dt>Site</dt><dd>{preview.site}</dd>
        <dt>Vendor</dt><dd>{preview.vendorCode||"Belum terdeteksi"}</dd>
        <dt>PO kandidat</dt><dd>{preview.poCode||"Belum ditemukan"} {preview.purchaseOrderId?`(#${preview.purchaseOrderId})`:""}</dd>
        <dt>Confidence PO</dt><dd>{pct(preview.poMatchConfidence)}</dd>
        <dt>Aman disimpan</dt><dd>{preview.canCommit?"YA":"BELUM — perlu pilih/perbaiki PO atau item"}</dd>
      </dl>
      <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Dari WA</th><th>Diterima</th><th>Item PO</th><th>Qty PO</th><th>Selisih</th><th>Match</th></tr></thead><tbody>{(preview.matches||[]).map((x,i)=><tr key={`${x.reported_item_name}-${i}`}><td>{x.reported_item_name}</td><td>{fmtQty(x.received_qty)} {x.unit||""}</td><td>{x.po_item_name||"⚠ Belum cocok"}</td><td>{fmtQty(x.po_qty)}</td><td>{x.variance_qty===null||x.variance_qty===undefined?"-":`${Number(x.variance_qty)>0?"+":""}${fmtQty(x.variance_qty)}`}</td><td>{pct(x.match_confidence)}</td></tr>)}</tbody></table></div>
      {!preview.committed&&<div className="ops-chat-actions"><button onClick={commit} disabled={saving||!preview.canCommit}><CheckCircle2 size={16}/> Konfirmasi Penerimaan</button></div>}
      {!preview.canCommit&&<div className="ops-muted">Sistem sengaja tidak mengizinkan commit otomatis bila PO/item masih ambigu. PO qty tetap tidak berubah.</div>}
    </div>}

    <div className="ops-module-header"><div><span className="ops-kicker">HISTORY</span><h3>Riwayat Penerimaan Tercatat</h3><p>Cari berdasarkan tanggal terima, vendor, PO ID/kode PO, atau nama barang. Ini menampilkan receipt header dan semua item di dalamnya, termasuk input dari GPTS.</p></div></div>
    <div className="ops-form-grid">
      <label>Dari tanggal terima<input type="date" value={historyFrom} onChange={e=>setHistoryFrom(e.target.value)} /></label>
      <label>Sampai tanggal terima<input type="date" value={historyTo} onChange={e=>setHistoryTo(e.target.value)} /></label>
      <label>Vendor<input value={historyVendor} onChange={e=>setHistoryVendor(e.target.value.toUpperCase())} placeholder="HOLIL" /></label>
      <label>PO ID / Kode PO<input value={historyPo} onChange={e=>setHistoryPo(e.target.value)} placeholder="18 atau PO-CEMPLANG-20260819-HOLIL" /></label>
      <label>Cari barang / pelapor<input value={historySearch} onChange={e=>setHistorySearch(e.target.value)} placeholder="Bidin, Jeruk, Sereh..." /></label>
      <label>Aksi<div className="ops-row-actions"><button onClick={load} disabled={loading}><RefreshCw size={15}/> Cari / Refresh</button></div></label>
    </div>
    <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Terima</th><th>PO</th><th>Distribusi</th><th>Vendor/Site</th><th>Pelapor</th><th>Item Diterima</th><th>Total</th><th>Status</th></tr></thead><tbody>{items.map(x=><tr key={x.id}>
      <td><strong>Receipt #{x.id}</strong><div className="ops-muted">{compactDateTime(x.received_at)}</div></td>
      <td><strong>{x.po_code||"-"}</strong><div className="ops-muted">PO ID {x.purchase_order_id || "-"} · {x.po_status || "-"}</div></td>
      <td>{x.distribution_date || "-"}<div className="ops-muted">Masak: {x.cooking_at ? String(x.cooking_at).slice(0,10) : "-"}</div></td>
      <td>{x.vendor_code}<div className="ops-muted">{x.site}</div></td>
      <td>{x.reporter || "-"}<div className="ops-muted">{x.source_type || "-"}</div></td>
      <td><details open><summary><strong>{x.item_count}</strong> item · {(x.item_names || []).slice(0,4).join(", ")}{(x.item_names || []).length > 4 ? "..." : ""}</summary><div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Receipt Item</th><th>Item PO</th><th>Dari WA</th><th>Diterima</th><th>Diterima Bersih</th><th>Reject</th><th>Selisih</th><th>Match</th></tr></thead><tbody>{(x.items || []).map(line=><tr key={line.receipt_item_id}><td>#{line.receipt_item_id}</td><td>{line.po_item_name || "-"}</td><td>{line.reported_item_name || "-"}</td><td>{fmtQty(line.received_qty)} {line.unit || ""}</td><td>{fmtQty(line.accepted_qty)} {line.unit || ""}</td><td>{fmtQty(line.rejected_qty)} {line.unit || ""}</td><td>{Number(line.variance_qty||0)>0?"+":""}{fmtQty(line.variance_qty)}</td><td>{pct(line.match_confidence)}</td></tr>)}</tbody></table></div></details></td>
      <td>{fmtQty(x.received_qty_total)}<div className="ops-muted">Bersih {fmtQty(x.accepted_qty_total)} · Reject {fmtQty(x.rejected_qty_total)}</div></td>
      <td>{x.match_status || "-"}<div className="ops-muted">{pct(x.match_confidence)}</div></td>
    </tr>)}{!loading&&items.length===0&&<tr><td colSpan="8" className="ops-empty-cell">Belum ada penerimaan yang cocok dengan filter. Coba kosongkan tanggal/filter, atau cari PO distribusi H+1 bila barang diterima sehari sebelumnya.</td></tr>}</tbody></table></div>

    <div className="ops-module-header"><div><span className="ops-kicker">VARIANCE</span><h3>PO vs Barang Diterima</h3><p>Selisih negatif berarti kurang kirim; positif berarti lebih kirim.</p></div></div>
    <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Waktu</th><th>PO</th><th>Vendor</th><th>Item PO</th><th>WA</th><th>PO Qty</th><th>Diterima</th><th>Selisih</th><th>Match</th></tr></thead><tbody>{variance.map(x=><tr key={x.receipt_item_id}><td>{compactDateTime(x.received_at)}</td><td>{x.po_code||"-"}</td><td>{x.vendor_code||"-"}</td><td>{x.po_item_name||"-"}</td><td>{x.reported_item_name||"-"}</td><td>{fmtQty(x.po_qty_snapshot)}</td><td>{fmtQty(x.received_qty)} {x.unit||""}</td><td>{Number(x.variance_qty||0)>0?"+":""}{fmtQty(x.variance_qty)}</td><td>{pct(x.item_match_confidence)}</td></tr>)}{!loading&&variance.length===0&&<tr><td colSpan="9" className="ops-empty-cell">Belum ada variance penerimaan.</td></tr>}</tbody></table></div>
  </section>;
}