const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),esbuild=require('esbuild');
const {chromium}=require('playwright');
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'approval-error-')),'ui.js');
 await esbuild.build({define:{'import.meta.env':'{}'},stdin:{resolveDir:root,loader:'jsx',contents:`
 import React from'react';import{createRoot}from'react-dom/client';import ApprovalActions from'./src/lpdh/ApprovalActions.jsx';import{lpdhApi}from'./src/lpdh/lpdhApi.js';
 lpdhApi.approvalPreview=async()=>{throw new Error('Template belum dapat dicetak.');};
 window.testTab={closed:false,document:{body:{style:{}}},close(){this.closed=true}};window.open=()=>window.testTab;
 createRoot(document.getElementById('root')).render(<ApprovalActions site="CEMPLANG" serviceDate="2026-10-07" daily={{}}/>);`},outfile:out,bundle:true,format:'iife'});
 const browser=await chromium.launch({headless:true});try{
  const page=await browser.newPage();await page.setContent('<div id="root"></div>');await page.addScriptTag({path:out});
  await page.getByRole('button',{name:'Buka Pratinjau Cetak',exact:true}).click();
  await page.getByRole('status').waitFor();assert.match(await page.getByRole('status').innerText(),/CEMPLANG tanggal 2026-10-07 gagal: Template belum dapat dicetak/);
  const tab=await page.evaluate(()=>({closed:window.testTab.closed,text:window.testTab.document.body.textContent}));
  assert.equal(tab.closed,false);assert.match(tab.text,/Data tidak difinalkan/);
  assert.equal(await page.getByRole('button',{name:'Finalkan Pengesahan & Simpan ke Drive'}).isDisabled(),true);
  console.log('PASS failed approval preview stays visible and cannot finalize');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});

