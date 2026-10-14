const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),esbuild=require('esbuild');
const{chromium}=require('playwright');
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'mitra-support-')),'ui.js');
 await esbuild.build({define:{'import.meta.env':'{}'},stdin:{resolveDir:root,loader:'jsx',contents:`import React from'react';import{createRoot}from'react-dom/client';import Delivery from'./src/delivery/DeliveryWorkspace.jsx';
 const document={id:99,status:'FINAL',site:'MAJA',documentType:'INSENTIF_MITRA',documentNumber:'001/IM/X/2026',serviceDate:'2026-10-14',total:6046000,header:{issuerName:'YAYASAN UJI',senderSignatory:'PENGURUS'},items:[{itemName:'Insentif Mitra',quantity:1,unit:'hari',unitPrice:6046000,lineTotal:6046000}]};
 const pkg={document,numbers:{KUI_MITRA:'001/KUI.Banper/IM/X/2026'},dates:{KUI_MITRA:'2026-10-15'},settings:{}};window.requestBodies=[];
 window.fetch=async(url,options={})=>{let body=url.includes('delivery-sync')?{packages:[pkg]}:url.includes('delivery-controls')?{profiles:{KUI:{signatory:'VENDOR SALAH'},KUI_MITRA:{supervisor:'PENGAWAS'}}}:{document};if(options.method==='PUT'){window.requestBodies.push({url,body:JSON.parse(options.body)});body={ok:true};}return{ok:true,json:async()=>body};};
 createRoot(window.document.getElementById('root')).render(<Delivery role='MAJA'/>);`},outfile:out,bundle:true,format:'iife',loader:{'.css':'empty'},plugins:[{name:'offline-session',setup(build){build.onResolve({filter:/auth\/session.js$/},()=>({path:'session',namespace:'test'}));build.onLoad({filter:/.*/,namespace:'test'},()=>({contents:'export const CORE_API="http://fixture.test";export const readSessionToken=()=>"synthetic";',loader:'js'}));}}]});
 const browser=await chromium.launch({headless:true});try{
  const page=await browser.newPage();await page.setContent('<div id="root"></div>');await page.addScriptTag({path:out});
  await page.getByRole('button',{name:/001\/IM\/X\/2026/}).click();
  await page.getByRole('dialog',{name:'Preview Dokumen Pendamping'}).waitFor();
  assert.equal(await page.getByRole('tab',{name:'Kuitansi Insentif Mitra',exact:true}).count(),1);
  assert.equal(await page.getByRole('tab',{name:'Surat Jalan',exact:true}).count(),0);
  await page.frameLocator('iframe').getByText('YAYASAN UJI',{exact:true}).waitFor();
  assert.equal(await page.frameLocator('iframe').getByText('VENDOR SALAH',{exact:true}).count(),0);
  await page.getByRole('button',{name:'Edit identitas & aset',exact:true}).click();
  await page.getByRole('button',{name:'Simpan master jenis surat',exact:true}).click();
  await page.waitForFunction(()=>window.requestBodies.length===1);
  const request=await page.evaluate(()=>window.requestBodies[0]);assert.match(request.url,/delivery-profiles\/KUI_MITRA/);assert.equal(request.body.settings.supervisor,'PENGAWAS');
  console.log('PASS Mitra-only companion tab and isolated master save; no vendor signature inherited');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
