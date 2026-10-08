const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),esbuild=require('esbuild');
const {chromium}=require('playwright');
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'topup-upload-')),'ui.js');
 await esbuild.build({define:{'import.meta.env':'{}'},stdin:{resolveDir:root,loader:'jsx',contents:`import React,{useState}from'react';import{createRoot}from'react-dom/client';import{DailyPanel,normalizeDaily}from'./src/lpdh/LpdhForms.jsx';function App(){const[d,setD]=useState(normalizeDaily({topups:[{date:'2026-10-08',evidenceLink:'https://old.example/proof'}]},'2026-10-08'));return <DailyPanel site="MAJA" serviceDate="2026-10-08" masters={{}} daily={d} setDaily={v=>setD({...v,_reviewValidated:false})} dailySaved={false} api={{uploadTopupEvidence:async()=>{if(window.failUpload)throw Error('upload failed');return{evidenceLink:'https://drive.google.com/file/d/test/view'}}}} onSaved={m=>window.message=m}/>};createRoot(document.getElementById('root')).render(<App/>);`},outfile:out,bundle:true,format:'iife'});
 const browser=await chromium.launch({headless:true});try{
  const page=await browser.newPage();await page.setContent('<div id="root"></div>');await page.addScriptTag({path:out});
  await page.getByRole('tab',{name:'E / F · Saldo & TopUp',exact:true}).click();
  const upload=page.getByLabel('Upload bukti TopUp baris 1');
  await upload.setInputFiles({name:'bukti.jpeg',mimeType:'image/jpeg',buffer:Buffer.from('test fixture')});
  await page.waitForFunction(()=>Array.from(document.querySelectorAll('input')).some(x=>x.value==='https://drive.google.com/file/d/test/view'));
  assert.match(await page.evaluate(()=>window.message),/Simpan.*Validasi/);
  assert.equal(await page.getByRole('button',{name:'Simpan & Validasi',exact:true}).last().getAttribute('class'),'lpdh-save-pending');
  await page.evaluate(()=>window.failUpload=true);
  await upload.setInputFiles({name:'bukti.pdf',mimeType:'application/pdf',buffer:Buffer.from('test fixture')});
  await page.waitForFunction(()=>String(window.message).includes('upload failed'));
  assert.equal(await page.locator('input').evaluateAll(xs=>xs.filter(x=>x.value==='https://drive.google.com/file/d/test/view').length),1);
  console.log('PASS upload fills only selected link; pending validation; failure preserves link');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});

