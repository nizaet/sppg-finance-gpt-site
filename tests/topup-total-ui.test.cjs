const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),esbuild=require('esbuild');
const {chromium}=require('playwright');
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'topup-total-')),'ui.js');
 await esbuild.build({define:{'import.meta.env':'{}'},stdin:{resolveDir:root,loader:'jsx',contents:`import React,{useState}from'react';import{createRoot}from'react-dom/client';import Receipt from'./src/lpdh/TopupReceiptActions.jsx';const profile={sppgName:'Cemplang',foundation:'Yayasan',headName:'Kepala',foundationName:'Pengurus',payer:'BGN',purpose:'Banper'};let receipt,rows=[];const api={topupReceipts:async()=>({profile,documentNumber:'001/KWT/X/2026',receipts:receipt?[receipt]:[]}),topupReceiptDraft:async p=>{if(p.row_index!==0)throw Error('wrong row');window.lastPayload=p;const t=Number(p.total_amount),raw=Math.round(t*.67),inc=Math.round(t*.13);receipt={id:1,documentNumber:p.document_number,status:'DRAFT',snapshot:{profile:p.profile,funds:{date:p.funds.date,reference:p.funds.reference||'',rawAmount:raw,incentiveAmount:inc,operationalAmount:t-raw-inc}},hash:'hash'};rows=[{date:p.expected_funds.date,rawAmount:0,operationalAmount:0,incentiveAmount:0,_topupReceiptId:1}];return{receipt,data:{topups:rows}}},topupReceiptPdf:async()=>({contentBase64:btoa('%PDF-test'),hash:'hash'}),topupReceiptFinalize:async()=>{receipt={...receipt,status:'FINAL',pdfLink:'https://drive.google.com/test'};rows=[{...rows[0],...receipt.snapshot.funds,receiptNo:receipt.documentNumber,evidenceLink:receipt.pdfLink}];return{receipt,data:{topups:rows}}}};function App(){const[data,setData]=useState({topups:[]});return <Receipt isNew site='CEMPLANG' serviceDate='2026-10-07' row={{date:'2026-10-07',rawAmount:0,operationalAmount:0,incentiveAmount:0}} index={data.topups.length} api={api} disabled={false} onData={(d,id)=>{window.savedData=d;window.receiptId=id;setData(d)}}/>};createRoot(document.getElementById('root')).render(<App/>);`},outfile:out,bundle:true,format:'iife'});
 const browser=await chromium.launch({headless:true});try{
  const page=await browser.newPage();await page.setContent('<div id="root"></div>');await page.addScriptTag({path:out});
  await page.getByRole('button',{name:'Buat Kuitansi TopUp baru',exact:true}).click();
  await page.getByLabel('Total TopUp (Rp)',{exact:true}).fill('388605400');
  await page.getByRole('button',{name:'Simpan Draft Kuitansi',exact:true}).click();
  await page.waitForFunction(()=>window.savedData?.topups.length===1);
  assert.equal(await page.getByRole('dialog').isVisible(),true);
  assert.equal(await page.getByRole('button',{name:'Preview / Cetak PDF',exact:true}).isEnabled(),true);
  assert.equal(await page.evaluate(()=>window.savedData.topups[0].rawAmount),0);
  await page.getByRole('button',{name:'Simpan Draft Kuitansi',exact:true}).click();
  assert.equal(await page.evaluate(()=>window.lastPayload.row_index),0);
  await page.getByRole('button',{name:'Preview / Cetak PDF',exact:true}).click();await page.getByTitle('Preview Kuitansi TopUp').waitFor();
  page.on('dialog',d=>d.accept());await page.getByRole('button',{name:'Finalkan & Simpan ke Drive',exact:true}).click();
  await page.waitForFunction(()=>window.savedData?.topups[0].evidenceLink);
  const row=await page.evaluate(()=>window.savedData.topups[0]);
  assert.equal(row.rawAmount,260365618);assert.equal(row.incentiveAmount,50518702);assert.equal(row.operationalAmount,77721080);assert.equal(row.receiptNo,'001/KWT/X/2026');
  assert.equal(await page.evaluate(()=>window.savedData.topups.length),1);
  console.log('PASS single total, split 67/13/20, stable dialog after draft, repeated save, preview, final table synchronization');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});

