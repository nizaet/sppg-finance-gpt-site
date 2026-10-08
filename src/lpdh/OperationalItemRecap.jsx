import React,{useEffect,useState} from 'react';
import {CORE_API,readSessionToken} from '../auth/session.js';
const money=value=>`Rp ${Number(value||0).toLocaleString('id-ID')}`;
export default function OperationalItemRecap({site,period,refresh}){
 const [data,setData]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[exporting,setExporting]=useState(false);
 const query=new URLSearchParams({site,start_date:period.start,end_date:period.end}).toString();
 useEffect(()=>{let dead=false;setData(null);setError('');if(!period.start||!period.end||period.start>period.end)return;setBusy(true);
  fetch(`${CORE_API}/v1/accountant-documents/recap/operational-items?${query}`,{headers:{Authorization:`Bearer ${readSessionToken()}`}})
   .then(async r=>{const b=await r.json();if(!r.ok)throw Error(typeof b.detail==='string'?b.detail:'Gagal memuat item operasional.');return b;})
   .then(b=>{if(!dead)setData(b);}).catch(e=>{if(!dead)setError(e.message);}).finally(()=>{if(!dead)setBusy(false);});return()=>{dead=true};
 },[query,refresh]);
 const download=async()=>{setExporting(true);setError('');try{
  const r=await fetch(`${CORE_API}/v1/accountant-documents/recap/operational-items.xlsx?${query}`,{headers:{Authorization:`Bearer ${readSessionToken()}`}});
  if(!r.ok){const b=await r.json();throw Error(typeof b.detail==='string'?b.detail:'Unduhan Excel gagal.');}
  const blob=await r.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');
  link.href=url;link.download=`Rekap_Operasional_${site}_${period.start}_${period.end}.xlsx`;link.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
 }catch(e){setError(e.message);}finally{setExporting(false)}};
 return <div><div className="lpdh-form-section-head"><div><h3>Rekap Item Operasional</h3><p>Jumlah item dari invoice operasional FINAL pada {period.start} sampai {period.end}. Bukan catatan stok aktual; upah dan insentif tidak ikut. Satuan dan kategori berbeda tetap dipisahkan.</p></div><button type="button" className="primary" disabled={busy||exporting||!data?.items?.length} onClick={download}>{exporting?'Menyiapkan Excel…':'Unduh Excel Item Operasional'}</button></div>
 {error&&<p role="alert">{error}</p>}{busy?<p role="status">Memuat item operasional…</p>:<>
 <div className="lpdh-summary-cards"><div><span>Invoice FINAL</span><strong>{data?.invoiceCount||0}</strong></div><div><span>Item / satuan</span><strong>{data?.itemCount||0}</strong></div><div><span>Total biaya operasional</span><strong>{money(data?.totalAmount)}</strong></div></div>
 <div className="lpdh-table-wrap"><table className="lpdh-data-table"><thead><tr>{['Item','Kategori','Jumlah','Satuan','Total biaya','Invoice','Hari pelayanan'].map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{data?.items?.length?data.items.map((x,i)=><tr key={i}><td>{x.itemName}</td><td>{x.category||'—'}</td><td>{Number(x.quantity).toLocaleString('id-ID',{maximumFractionDigits:4})}</td><td>{x.unit}</td><td>{money(x.amount)}</td><td>{x.invoiceCount}</td><td>{x.dayCount}</td></tr>):<tr><td colSpan={7}>Belum ada item invoice operasional FINAL pada periode ini.</td></tr>}</tbody><tfoot><tr><td colSpan={4}>TOTAL BIAYA</td><td>{money(data?.totalAmount)}</td><td colSpan={2}/></tr></tfoot></table></div></>}
 </div>;
}

