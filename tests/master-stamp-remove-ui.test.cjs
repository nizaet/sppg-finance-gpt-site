const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),esbuild=require('esbuild');
const{chromium}=require('playwright');
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'remove-stamp-')),'ui.js');
 await esbuild.build({define:{'import.meta.env':'{}'},stdin:{resolveDir:root,loader:'jsx',contents:`
 import React,{useState}from'react';import{createRoot}from'react-dom/client';import{MasterPanel}from'./src/lpdh/LpdhForms.jsx';
 const api={officialTemplateStatus:async()=>({installed:true})};
 function App(){const[m,setM]=useState({assets:{approvalSppgStamp:'data:image/png;base64,AA==',approvalSppgSignature:'data:image/png;base64,BB==',approvalFoundationStamp:'data:image/png;base64,CC=='}});window.master=m;return <MasterPanel site="CEMPLANG" masters={m} setMasters={setM} api={api}/>;}createRoot(document.getElementById('root')).render(<App/>);`},outfile:out,bundle:true,format:'iife'});
 const browser=await chromium.launch({headless:true});try{
  const page=await browser.newPage();await page.setContent('<div id="root"></div>');await page.addScriptTag({path:out});
  await page.getByRole('tab',{name:'Pengesah',exact:true}).click();
  await page.getByRole('button',{name:'Hapus Stempel SPPG',exact:true}).click();
  const assets=await page.evaluate(()=>window.master.assets);
  assert.equal(assets.approvalSppgStamp,'');assert.equal(assets.approvalSppgSignature,'data:image/png;base64,BB==');assert.equal(assets.approvalFoundationStamp,'data:image/png;base64,CC==');
  assert.equal(await page.getByRole('img',{name:'Stempel SPPG',exact:true}).count(),0);
  console.log('PASS removing one stamp preserves signature and other stamp');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});

