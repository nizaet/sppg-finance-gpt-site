const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),esbuild=require('esbuild');
const{chromium}=require('playwright');
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'bgn-check-')),'ui.js');
 await esbuild.build({define:{'import.meta.env':'{}'},stdin:{resolveDir:root,loader:'jsx',contents:`
 import React from'react';import{createRoot}from'react-dom/client';import BgnDrivePanel from'./src/lpdh/BgnDrivePanel.jsx';import{lpdhApi}from'./src/lpdh/lpdhApi.js';
 const status={configured:true,connected:true,folderReady:true,expectedEmail:'synthetic@example.test'};
 lpdhApi.bgnStatus=async()=>status;lpdhApi.bgnCheck=async()=>new Promise(resolve=>window.finishCheck=()=>resolve({...status,checkedAt:'2026-10-12T05:00:00Z',detail:'Pemeriksaan berhasil: akun Google aktif dan folder BGN dapat menerima upload.'}));
 createRoot(document.getElementById('root')).render(<BgnDrivePanel site="MAJA"/>);`},outfile:out,bundle:true,format:'iife'});
 const browser=await chromium.launch({headless:true});try{
  const page=await browser.newPage();await page.setContent('<div id="root"></div>');await page.addScriptTag({path:out});
  await page.getByRole('button',{name:'Periksa Koneksi',exact:true}).click();
  assert.match(await page.getByRole('status').innerText(),/Memeriksa akun Google/);
  assert.equal(await page.getByRole('button',{name:'Sedang memproses…'}).isDisabled(),true);
  await page.evaluate(()=>window.finishCheck());
  await page.getByRole('button',{name:'Periksa Koneksi',exact:true}).waitFor();
  assert.match(await page.getByRole('status').innerText(),/Pemeriksaan berhasil/);
  assert.match(await page.getByRole('status').innerText(),/\d{2}[.:]\d{2}[.:]\d{2}/);
  console.log('PASS check shows progress and timestamped result even when status is unchanged');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});

