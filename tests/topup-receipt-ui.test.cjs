const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),esbuild=require('esbuild');
const {chromium}=require('playwright');
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'topup-receipt-')),'ui.js');
 await esbuild.build({define:{'import.meta.env':'{}'},stdin:{resolveDir:root,loader:'jsx',contents:`import React from'react';import{createRoot}from'react-dom/client';import TopupReceiptActions from'./src/lpdh/TopupReceiptActions.jsx';const profile={sppgName:'Maja',foundation:'Yayasan',headName:'Kepala',foundationName:'Pengurus',payer:'BGN',purpose:'Banper'};let receipt;const api={topupReceipts:async()=>({profile,documentNumber:'001/KWT/X/2026',receipts:[]}),topupReceiptDraft:async p=>{receipt={id:1,documentNumber:p.document_number,status:'DRAFT',snapshot:{profile:p.profile},hash:'hash'};return{receipt,data:{draft:true}}},topupReceiptPdf:async()=>({contentBase64:btoa('%PDF-test'),hash:'hash'}),topupReceiptFinalize:async()=>({receipt:{...receipt,status:'FINAL',pdfLink:'https://drive.google.com/test'},data:{final:true}}),topupReceiptCancel:async()=>({receipt:{...receipt,status:'CANCELLED'},data:{cancelled:true}})};createRoot(document.getElementById('root')).render(<TopupReceiptActions site='MAJA' serviceDate='2026-10-08' row={{date:'2026-10-08',rawAmount:1000}} index={0} api={api} disabled={false} onData={data=>window.receiptData=data}/>);`},outfile:out,bundle:true,format:'iife'});
 const browser=await chromium.launch({headless:true});try{
  const page=await browser.newPage();await page.setContent('<div id="root"></div>');await page.addScriptTag({path:out});
  await page.getByRole('button',{name:'Buat / Buka Kuitansi TopUp 1',exact:true}).click();await page.getByLabel('Nama SPPG',{exact:true}).waitFor();
  await page.addStyleTag({path:path.join(root,'src/lpdh/lpdh.css')});
  assert.equal(await page.getByLabel('Nama SPPG',{exact:true}).inputValue(),'Maja');
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.getByRole('dialog').evaluate(e=>e.scrollWidth<=e.clientWidth),true);
  assert.ok(await page.getByLabel('Nama SPPG',{exact:true}).evaluate(e=>e.getBoundingClientRect().width)>250);
  await page.setViewportSize({width:1100,height:900});
  assert.equal(await page.getByRole('button',{name:'Preview / Cetak PDF',exact:true}).isEnabled(),false);
  await page.getByRole('button',{name:'Simpan Draft Kuitansi',exact:true}).click();await page.waitForFunction(()=>window.receiptData?.draft);
  await page.getByRole('button',{name:'Preview / Cetak PDF',exact:true}).click();await page.getByTitle('Preview Kuitansi TopUp').waitFor();
  await page.getByLabel('Nama SPPG',{exact:true}).fill('Maja Baru');assert.equal(await page.getByRole('button',{name:'Finalkan & Simpan ke Drive',exact:true}).isEnabled(),false);
  await page.getByRole('button',{name:'Simpan Draft Kuitansi',exact:true}).click();await page.getByRole('button',{name:'Preview / Cetak PDF',exact:true}).click();await page.getByTitle('Preview Kuitansi TopUp').waitFor();
  page.on('dialog',d=>d.type()==='prompt'?d.accept('Perbaikan'):d.accept());
  await page.getByRole('button',{name:'Finalkan & Simpan ke Drive',exact:true}).click();await page.waitForFunction(()=>window.receiptData?.final);
  assert.equal(await page.getByLabel('Nama SPPG',{exact:true}).isEnabled(),false);
  await page.getByRole('button',{name:'Batalkan Kuitansi',exact:true}).click();await page.waitForFunction(()=>window.receiptData?.cancelled);
  console.log('PASS defaults, draft, preview-before-final, dirty guard, final link, cancellation');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});

