import React,{useEffect,useRef,useState} from 'react';
import {arrayBufferToBase64} from './lpdhApi.js';

const labels={sppgName:'Nama SPPG',foundation:'Nama Yayasan / kop',headName:'Nama Kepala SPPG',foundationName:'Nama penerima / pengurus Yayasan',address:'Alamat pada kop',payer:'Sudah terima dari',purpose:'Untuk pembayaran'};
const images={letterhead:'Kop / logo',headSignature:'TTD Kepala SPPG',headStamp:'Stempel SPPG',foundationSignature:'TTD penerima Yayasan',foundationStamp:'Stempel Yayasan'};
const moneyLabels={rawAmount:'Nilai bahan baku (Rp)',operationalAmount:'Nilai operasional (Rp)',incentiveAmount:'Nilai insentif (Rp)'};
export default function TopupReceiptActions({site,serviceDate,row,index,api,disabled,onData}){
 const[open,setOpen]=useState(false),[profile,setProfile]=useState({}),[number,setNumber]=useState(''),[receipt,setReceipt]=useState(null),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[url,setUrl]=useState(''),[hash,setHash]=useState('');
 const alive=useRef(true),lock=useRef(false),pdfUrl=useRef('');
 const[funds,setFunds]=useState(row);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;if(pdfUrl.current)URL.revokeObjectURL(pdfUrl.current)}},[]);
 const dirty=!!receipt&&(receipt.documentNumber!==number||JSON.stringify(receipt.snapshot.profile)!==JSON.stringify(profile)||JSON.stringify(receipt.snapshot.funds||row)!==JSON.stringify(funds));
 const run=async(fn)=>{if(lock.current)return;lock.current=true;setBusy(true);setMessage('');try{await fn()}catch(e){if(alive.current)setMessage(e.message)}finally{lock.current=false;if(alive.current)setBusy(false)}};
 const load=()=>{setOpen(true);run(async()=>{const r=await api.topupReceipts(site,serviceDate);if(!alive.current)return;const found=r.receipts.find(x=>x.id===row._topupReceiptId);setReceipt(found||null);setFunds(found?.snapshot.funds||row);setProfile(found?.snapshot.profile||r.profile);setNumber(found?.status==='CANCELLED'?r.documentNumber:found?.documentNumber||r.documentNumber);setHash('');setUrl('')})};
 const edit=(key,value)=>{setProfile(p=>({...p,[key]:value}));setHash('');setUrl('')};
 const image=async(key,file)=>{if(!file)return;try{if(file.size>5*1024*1024)throw Error('Gambar maksimal 5 MB.');if(!['image/png','image/jpeg','image/webp'].includes(file.type))throw Error('Pilih PNG, JPG, atau WebP.');edit(key,`data:${file.type};base64,${arrayBufferToBase64(await file.arrayBuffer())}`)}catch(e){setMessage(e.message)}};
 const save=()=>run(async()=>{const r=await api.topupReceiptDraft({site,service_date:serviceDate,row_index:index,expected_funds:row,funds,document_number:number,profile});if(!alive.current)return;setReceipt(r.receipt);setFunds(r.receipt.snapshot.funds||funds);setProfile(r.receipt.snapshot.profile);setNumber(r.receipt.documentNumber);setHash('');setUrl('');onData(r.data);setMessage('Draft tersimpan. Buka preview sebelum Finalkan. Nilai masuk ke penerimaan TopUp setelah FINAL, bukan saat menyimpan draft.')});
 const preview=()=>run(async()=>{const r=await api.topupReceiptPdf(receipt.id);if(!alive.current)return;if(pdfUrl.current)URL.revokeObjectURL(pdfUrl.current);pdfUrl.current=URL.createObjectURL(new Blob([Uint8Array.from(atob(r.contentBase64),c=>c.charCodeAt(0))],{type:'application/pdf'}));setUrl(pdfUrl.current);setHash(r.hash)});
 const finalize=()=>{if(!window.confirm('Finalkan kuitansi TopUp ini? PDF disimpan ke Drive, nomor dan link masuk ke baris penerimaan. Ini bukan konfirmasi transfer bank.'))return;run(async()=>{const r=await api.topupReceiptFinalize(receipt.id,hash);if(!alive.current)return;setReceipt(r.receipt);onData(r.data);setUrl('');setHash('');setMessage('FINAL: PDF tersimpan di Drive. Nomor dan link otomatis terisi. Klik Simpan & Validasi untuk memperbarui pemeriksaan.')})};
 const cancel=()=>{const reason=window.prompt('Alasan membatalkan kuitansi? Arsip Drive tetap disimpan.');if(!reason?.trim())return;run(async()=>{const r=await api.topupReceiptCancel(receipt.id,receipt.hash,reason);if(!alive.current)return;setReceipt(r.receipt);onData(r.data);setHash('');setUrl('');setMessage('Dibatalkan. Dana penerimaan tidak dihapus; link otomatis dilepas. Simpan & Validasi atau buat draft baru.')})};
 const total=['rawAmount','operationalAmount','incentiveAmount'].reduce((s,k)=>s+Number(funds[k]||0),0);
 return <div><button type="button" disabled={disabled&&!row._topupReceiptId} onClick={load}>Buat / Buka Kuitansi TopUp {index+1}</button>
 {disabled&&!row._topupReceiptId&&<small> Klik Simpan &amp; Validasi dahulu.</small>}
 {open&&<div className="invoice-recap-overlay"><section className="invoice-recap-dialog topup-receipt-dialog" role="dialog" aria-modal="true" aria-label="Kuitansi penerimaan TopUp">
 <header><h3>Kuitansi TopUp · format Banper</h3><button type="button" disabled={busy} onClick={()=>setOpen(false)}>Tutup</button></header>
 <p>Tanggal penerimaan {funds.date} · Total Rp {total.toLocaleString('id-ID')} · {receipt?.status||'Belum ada draft'}</p>
 <fieldset><legend>Nilai penerimaan TopUp</legend><div className="lpdh-form-grid"><label>Tanggal penerimaan<input type="date" value={funds.date||''} disabled={busy||receipt?.status==='FINAL'} onChange={e=>{setFunds({...funds,date:e.target.value});setHash('');setUrl('')}}/></label><label>Referensi SP2D / transfer<input value={funds.reference||''} disabled={busy||receipt?.status==='FINAL'} onChange={e=>{setFunds({...funds,reference:e.target.value});setHash('');setUrl('')}}/></label>{Object.entries(moneyLabels).map(([key,label])=><label key={key}>{label}<input type="number" min="0" step="1" value={funds[key]||0} disabled={busy||receipt?.status==='FINAL'} onChange={e=>{setFunds({...funds,[key]:e.target.value});setHash('');setUrl('')}}/></label>)}</div><strong>Total Rp {total.toLocaleString('id-ID')}</strong><p>Nilai menggantikan baris TopUp ini saat FINAL, tidak membuat penerimaan tambahan.</p></fieldset>
 <p>Ini bukti dana masuk, bukan invoice pengeluaran. Kop dan kedua penandatangan dapat diisi; isian awal mengikuti master.</p>
 <label>Nomor kuitansi<input value={number} disabled={busy||receipt?.status==='FINAL'} onChange={e=>{setNumber(e.target.value);setHash('');setUrl('')}}/></label>
 <div className="lpdh-form-grid">{Object.entries(labels).map(([key,label])=><label key={key}>{label}<input value={profile[key]||''} disabled={busy||receipt?.status==='FINAL'} onChange={e=>edit(key,e.target.value)}/></label>)}</div>
 <div className="lpdh-form-grid">{Object.entries(images).map(([key,label])=><label key={key}>{label}<input type="file" accept="image/png,image/jpeg,image/webp" disabled={busy||receipt?.status==='FINAL'} onChange={e=>{image(key,e.target.files?.[0]);e.target.value=''}}/>{profile[key]&&<><img src={profile[key]} alt={label} style={{maxWidth:160,maxHeight:85,objectFit:'contain'}}/><button type="button" disabled={busy||receipt?.status==='FINAL'} onClick={()=>edit(key,'')}>Hapus gambar</button></>}</label>)}</div>
 <div className="lpdh-inline-actions">{receipt?.status!=='FINAL'&&<button type="button" disabled={busy} onClick={save}>Simpan Draft Kuitansi</button>}
 <button type="button" disabled={busy||!receipt||dirty||receipt.status==='CANCELLED'} onClick={preview}>Preview / Cetak PDF</button>
 {receipt?.status==='DRAFT'&&<button type="button" disabled={busy||dirty||!hash} onClick={finalize}>Finalkan &amp; Simpan ke Drive</button>}
 {receipt&&receipt.status!=='CANCELLED'&&<button type="button" disabled={busy} onClick={cancel}>Batalkan Kuitansi</button>}
 {receipt?.pdfLink&&<a href={receipt.pdfLink} target="_blank" rel="noopener noreferrer">PDF di Drive</a>}
 {url&&<a href={url} target="_blank" rel="noopener noreferrer">Buka PDF untuk cetak / unduh</a>}</div>
 {message&&<p role="status">{message}</p>}{url&&<iframe title="Preview Kuitansi TopUp" src={url}/>}
 </section></div>}</div>;
}

