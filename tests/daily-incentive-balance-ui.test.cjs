const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),esbuild=require('esbuild');
const {chromium}=require('playwright');
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'incentive-balance-')),'ui.js');
 await esbuild.build({define:{'import.meta.env':'{}'},stdin:{resolveDir:root,loader:'jsx',contents:`
 import React,{useState}from'react';import{createRoot}from'react-dom/client';import{DailyPanel,normalizeDaily}from'./src/lpdh/LpdhForms.jsx';
 function App(){const[d,setD]=useState(normalizeDaily({incentive:{paidAmount:6344000},balance:{openingRaw:18625678,openingOperational:6857282,openingIncentive:732340,bankBalance:370148700},topups:[{date:'2026-10-07',rawAmount:260365618,operationalAmount:89379242,incentiveAmount:38860540}]},'2026-10-07'));
 return <DailyPanel site="CEMPLANG" serviceDate="2026-10-07" masters={{}} daily={d} setDaily={setD} dailySaved={false} preview={{incentiveCalculated:6344000,balance:{expenditure:{raw:28818200,operational:9509800}},topup:{requiredRaw:28818200,requiredOperational:9509800,requiredIncentive:6344000,proposalTotal:44672000}}} api={{}}/>}createRoot(document.getElementById('root')).render(<App/>);`},outfile:out,bundle:true,format:'iife'});
 const browser=await chromium.launch({headless:true});try{
  const page=await browser.newPage();await page.setContent('<div id="root"></div>');await page.addScriptTag({path:out});
  await page.getByRole('tab',{name:'E / F · Saldo & TopUp',exact:true}).click();
  const row=page.getByRole('row').filter({hasText:'Insentif Ketersediaan dan Mutu Layanan'});
  await row.waitFor();assert.match(await row.innerText(),/6\.344\.000/);
  assert.match(await page.getByRole('row').filter({hasText:'JUMLAH'}).first().innerText(),/370\.148\.700/);
  await page.getByLabel('Saldo VA rekening koran',{exact:true}).fill('370148701');
  assert.match(await row.innerText(),/6\.344\.000/);
  assert.equal(await page.locator('.lpdh-sticky-save button').getAttribute('class'),'lpdh-save-pending');
  assert.match(await page.locator('.lpdh-summary-cards').last().innerText(),/6\.344\.000/);
  console.log('PASS pending E/F preserves entered payment and calculated incentive after balance edits');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});

