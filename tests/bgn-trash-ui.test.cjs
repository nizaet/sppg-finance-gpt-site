const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),esbuild=require('esbuild');
const{chromium}=require('playwright');
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'bgn-trash-choice-')),'ui.js');
 await esbuild.build({define:{'import.meta.env':'{}'},stdin:{resolveDir:root,loader:'jsx',contents:`
 import React from 'react';import{createRoot}from'react-dom/client';import BgnDrivePanel from './src/lpdh/BgnDrivePanel.jsx';import{lpdhApi}from './src/lpdh/lpdhApi.js';import{chooseBgnTrash}from './src/lpdh/bgnTrashChoice.js';
 window.answer='SIMPAN';window.prompt=(text,value)=>{window.choiceDefault=value;return window.answer;};window.alert=()=>window.invalidAlert=true;window.chooseBgnTrash=chooseBgnTrash;window.confirm=()=>true;
 lpdhApi.bgnStatus=async()=>({configured:true,connected:true,folderReady:true});let pending=true;
 lpdhApi.bgnTrashRequests=async()=>({items:pending?[{id:7,service_date:'2026-10-12',status:'FAILED',error_message:'Pembatalan tersimpan, file belum di Sampah.'}]:[]});
 lpdhApi.bgnTrashRetry=async(site,id)=>{window.retryArgs={site,id};pending=false;return{status:'TRASHED',message:'File BGN sudah dipindahkan ke Sampah.'};};
 createRoot(document.getElementById('root')).render(<BgnDrivePanel site='MAJA' serviceDate='2026-10-12'/>);`},outfile:out,bundle:true,format:'iife'});
 const browser=await chromium.launch({headless:true});try{
  const page=await browser.newPage();await page.setContent('<div id="root"></div>');await page.addScriptTag({path:out});
  assert.equal(await page.evaluate(()=>window.chooseBgnTrash()),false);assert.equal(await page.evaluate(()=>window.choiceDefault),'SIMPAN');
  assert.equal(await page.evaluate(()=>{window.answer=' sampah ';return window.chooseBgnTrash();}),true);
  assert.equal(await page.evaluate(()=>{window.answer=null;return window.chooseBgnTrash();}),null);
  assert.equal(await page.evaluate(()=>{window.answer='invalid';return window.chooseBgnTrash();}),null);assert.equal(await page.evaluate(()=>window.invalidAlert),true);
  await page.getByText('Pemindahan file BGN belum selesai',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Coba lagi pindahkan ke Sampah BGN',exact:true}).click();
  await page.getByRole('status').filter({hasText:'File BGN sudah dipindahkan ke Sampah.'}).waitFor();
  assert.deepEqual(await page.evaluate(()=>window.retryArgs),{site:'MAJA',id:7});
  await page.getByText('Pemindahan file BGN belum selesai',{exact:true}).waitFor({state:'detached'});
  console.log('PASS default KEEP, explicit TRASH, abort, invalid choice, scoped retry and completed request removal');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
