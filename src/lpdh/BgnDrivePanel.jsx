import React,{useEffect,useRef,useState} from 'react';
import {lpdhApi} from './lpdhApi.js';

let pickerLoader;
function loadPicker(){
 if(!pickerLoader)pickerLoader=new Promise((resolve,reject)=>{
  const ready=()=>window.gapi.load('picker',{callback:resolve,onerror:()=>reject(new Error('Google Picker gagal dimuat.')),timeout:15000,ontimeout:()=>reject(new Error('Google Picker tidak merespons.'))});
  if(window.gapi)return ready();
  const script=document.createElement('script');script.src='https://apis.google.com/js/api.js';script.onload=ready;script.onerror=()=>reject(new Error('Tidak dapat memuat Google Picker.'));document.head.appendChild(script);
 }).catch(error=>{pickerLoader=null;throw error;});
 return pickerLoader;
}
export default function BgnDrivePanel({site}){
 const[state,setState]=useState(null),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
 const context=useRef(site);context.current=site;
 const refresh=async()=>{const target=site;const r=await lpdhApi.bgnStatus(target);if(context.current===target)setState(r);};
 async function check(){
  const target=site;setBusy(true);setMessage('Memeriksa akun Google dan izin folder…');
  try{const r=await lpdhApi.bgnCheck(target);if(context.current!==target)return;setState(r);setMessage(r.detail+' · '+new Date(r.checkedAt).toLocaleTimeString('id-ID'));}
  catch(e){if(context.current===target)setMessage('Pemeriksaan gagal: '+e.message);}
  finally{if(context.current===target)setBusy(false);}
 }
 useEffect(()=>{let alive=true;setState(null);setMessage('');lpdhApi.bgnStatus(site).then(r=>{if(alive)setState(r);}).catch(e=>{if(alive)setMessage(e.message);});return()=>{alive=false;};},[site]);
 async function connect(){
  const target=site,w=window.open('','_blank');if(!w)return setMessage('Izinkan tab baru untuk login Google.');
  w.document.body.textContent='Membuka login Google…';setBusy(true);setMessage('');
  try{const r=await lpdhApi.bgnStart(target);if(context.current!==target){w.close();return;}w.location.href=r.authorizationUrl;setMessage('Selesaikan login Google di tab baru, lalu klik Periksa Koneksi.');}
  catch(e){w.close();if(context.current===target)setMessage(e.message);}finally{setBusy(false);}
 }
 async function choose(){
  const target=site;setBusy(true);setMessage('Membuka pemilih folder Google…');
  try{
   await loadPicker();const config=await lpdhApi.bgnPicker(target);if(context.current!==target)return;
   const view=new window.google.picker.DocsView(window.google.picker.ViewId.FOLDERS).setIncludeFolders(true).setSelectFolderEnabled(true);
   const picker=new window.google.picker.PickerBuilder().setDeveloperKey(config.apiKey).setAppId(config.appId).setOAuthToken(config.accessToken).setOrigin(window.location.origin).addView(view).setCallback(async result=>{
    if(context.current!==target)return;
    if(result?.action===window.google.picker.Action.CANCEL){setMessage('Pemilihan folder dibatalkan. Folder tersimpan sebelumnya tidak diubah.');return;}
    if(result?.action!==window.google.picker.Action.PICKED)return;
    setBusy(true);setMessage('Pilihan folder diterima. Menyimpan dan memeriksa izin upload…');
    try{
     const folderId=result?.docs?.[0]?.id;
     if(!folderId)throw new Error('Google belum mengirim ID folder. Pilih folder kembali.');
     // Popup cleanup must never abort the server-side save or hide its error.
     try{picker.setVisible(false);picker.dispose();}catch{}
     await lpdhApi.bgnFolder(target,folderId);
     if(context.current!==target)return;
     setState(old=>({...old,connected:true,folderReady:true}));
     setMessage('Folder BGN berhasil disimpan dan izin upload terverifikasi.');
     try{await refresh();}catch{if(context.current===target)setMessage('Folder BGN berhasil disimpan. Refresh status belum berhasil; klik Periksa Koneksi.');}
    }catch(e){if(context.current===target)setMessage('Folder BGN belum tersimpan: '+(e?.message||'Permintaan gagal. Pilih folder kembali.'));}
    finally{if(context.current===target)setBusy(false);}
   }).build();picker.setVisible(true);
   setMessage('Pilih folder BGN dapur, lalu klik Select. Jika belum muncul “Pilihan folder diterima”, hasil Google belum sampai ke aplikasi.');
  }catch(e){if(context.current===target)setMessage(e.message);}finally{setBusy(false);}
 }
 async function disconnect(){if(!window.confirm('Putuskan koneksi Drive BGN dapur ini? Bukti di kedua Drive tidak dihapus.'))return;setBusy(true);try{await lpdhApi.bgnDisconnect(site);await refresh();setMessage('Koneksi diputus. Hubungkan ulang sebelum upload BGN.');}catch(e){setMessage(e.message);}finally{setBusy(false);}}
 return <section className="lpdh-form-section"><h2>Koneksi Drive BGN · {site}</h2>
  <p>Drive BGN untuk link bukti LPDH. Drive internal tetap terpisah untuk arsip dan Maker. Folder mengikuti bulan dan tanggal HPE, bukan tanggal tombol upload diklik.</p>
  {state&&<><p>Akun akuntan: <strong>{state.expectedEmail}</strong></p><p>Status: {state.folderReady?'Akun terhubung · Folder siap':state.connected?'Akun terhubung · Pilih folder BGN':state.configured?'Belum terhubung':'Konfigurasi server belum lengkap'}</p>
   {state.expectedFolderId&&<a href={`https://drive.google.com/drive/folders/${state.expectedFolderId}`} target="_blank" rel="noopener noreferrer">Buka folder BGN dapur</a>}
   <div className="lpdh-inline-actions"><button type="button" disabled={busy||!state.configured} onClick={connect}>Hubungkan / Login Ulang Google</button><button type="button" disabled={busy} onClick={check}>{busy?'Sedang memproses…':'Periksa Koneksi'}</button><button type="button" disabled={busy||!state.connected} onClick={choose}>Pilih Folder BGN</button><button type="button" disabled={busy||!state.connected} onClick={disconnect}>Putuskan Koneksi</button></div></>}
  {!state&&!message&&<p>Memeriksa koneksi…</p>}{message&&<p role="status">{message}</p>}
  <p>Tahap koneksi: upload bukti ke BGN belum diaktifkan pada alur invoice. Arsip dan link internal yang sudah ada tidak diubah.</p>
 </section>;
}

