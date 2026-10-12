const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),esbuild=require('esbuild');
const{chromium}=require('playwright');
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'bgn-check-')),'ui.js');
 await esbuild.build({define:{'import.meta.env':'{}'},stdin:{resolveDir:root,loader:'jsx',contents:`
 import React from'react';import{createRoot}from'react-dom/client';import BgnDrivePanel from'./src/lpdh/BgnDrivePanel.jsx';import{lpdhApi}from'./src/lpdh/lpdhApi.js';
 const status={configured:true,connected:true,folderReady:true,expectedEmail:'synthetic@example.test',expectedFolderId:'assigned-folder'};
 lpdhApi.bgnStatus=async()=>status;lpdhApi.bgnCheck=async()=>new Promise(resolve=>window.finishCheck=()=>resolve({...status,checkedAt:'2026-10-12T05:00:00Z',detail:'Pemeriksaan berhasil: akun Google aktif dan folder BGN dapat menerima upload.'}));
 window.saveCalls=[];
 lpdhApi.bgnPicker=async()=>({apiKey:'synthetic',appId:'123',accessToken:'synthetic'});
 lpdhApi.bgnFolder=async(site,id)=>{window.saveCalls.push({site,id});if(window.rejectFolder)throw new Error('Folder tidak sesuai dapur.');return new Promise(resolve=>window.finishFolder=()=>resolve({saved:true}));};
 window.gapi={load:(_name,options)=>options.callback()};
 class View{setIncludeFolders(){return this;}setSelectFolderEnabled(){return this;}}
 class Builder{setDeveloperKey(){return this;}setAppId(){return this;}setOAuthToken(){return this;}setOrigin(){return this;}addView(){return this;}setCallback(fn){window.selectFolder=fn;return this;}build(){return {setVisible(){},dispose(){throw new Error('Synthetic popup cleanup failure');}};}}
 window.google={picker:{DocsView:View,PickerBuilder:Builder,ViewId:{FOLDERS:'folders'},Action:{PICKED:'picked',CANCEL:'cancel'}}};
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
  await page.getByRole('button',{name:'Pilih Folder BGN',exact:true}).click();
  await page.waitForFunction(()=>typeof window.selectFolder==='function');
  await page.evaluate(()=>{window.selectFolder({action:'picked',docs:[{id:'synthetic-folder'}]});});
  await page.getByText('Pilihan folder diterima. Menyimpan dan memeriksa izin upload…',{exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Sedang memproses…'}).isDisabled(),true);
  await page.evaluate(()=>window.finishFolder());
  await page.getByText('Folder BGN berhasil disimpan dan izin upload terverifikasi.',{exact:true}).waitFor();
  assert.deepEqual(await page.evaluate(()=>window.saveCalls),[{site:'MAJA',id:'synthetic-folder'}]);
  await page.evaluate(()=>{window.selectFolder({action:'picked',docs:[]});});
  await page.getByText(/Folder BGN belum tersimpan: Google belum mengirim ID folder/).waitFor();
  assert.equal(await page.evaluate(()=>window.saveCalls.length),1);
  await page.evaluate(()=>{window.rejectFolder=true;window.selectFolder({action:'picked',docs:[{id:'wrong-folder'}]});});
  await page.getByText('Folder BGN belum tersimpan: Folder tidak sesuai dapur.',{exact:true}).waitFor();
  await page.evaluate(()=>{window.selectFolder({action:'cancel'});});
  await page.getByText(/Pemilihan folder dibatalkan/).waitFor();
  await page.evaluate(()=>{window.rejectFolder=false;});
  await page.getByRole('button',{name:'Verifikasi Folder BGN Dapur',exact:true}).click();
  await page.getByText(/Memverifikasi folder BGN dapur langsung/).waitFor();
  assert.deepEqual((await page.evaluate(()=>window.saveCalls)).at(-1),{site:'MAJA',id:'assigned-folder'});
  await page.evaluate(()=>window.finishFolder());
  await page.getByText(/Folder BGN berhasil diverifikasi dan disimpan/).waitFor();
  await page.evaluate(()=>{window.rejectFolder=true;});
  await page.getByRole('button',{name:'Verifikasi Folder BGN Dapur',exact:true}).click();
  await page.getByText(/Folder BGN belum dapat diverifikasi/).waitFor();
  console.log('PASS check shows progress and timestamped result even when status is unchanged');
  console.log('PASS Select saves despite popup cleanup failure and always reports success, empty selection, rejection or cancellation');
  console.log('PASS assigned folder verification uses the existing secured endpoint and reports permission rejection');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});

