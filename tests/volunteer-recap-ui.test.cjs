const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),esbuild=require('esbuild');
const {chromium}=require('playwright');
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'volunteer-recap-')),'ui.js');
 await esbuild.build({stdin:{resolveDir:root,loader:'jsx',contents:`import React from 'react';import{createRoot}from'react-dom/client';import Recap from './src/lpdh/VolunteerWageRecap.jsx';const rows=[{id:1,status:'FINAL',documentType:'UPAH_RELAWAN',serviceDate:'2026-10-05',documentNumber:'001/UPAH',driveUri:'https://drive.google.com/test',items:[{itemName:'Ani',lineTotal:100000},{itemName:'Guru 1',lineTotal:30000,metadata:{recipientType:'Guru'}}]}];createRoot(document.getElementById('root')).render(<Recap rows={rows} period={{start:'2026-10-05',end:'2026-10-09'}}/>);`},outfile:out,bundle:true,format:'iife'});
 const browser=await chromium.launch({headless:true});try{
 const page=await browser.newPage();await page.setContent('<div id="root"></div>');await page.addScriptTag({path:out});
 await page.getByRole('heading',{name:'Rekap Upah Relawan per Nama'}).waitFor();
 assert.equal(await page.getByRole('cell',{name:'Ani',exact:true}).count(),1);
 assert.equal(await page.getByRole('cell',{name:'Guru 1',exact:true}).count(),0);
 await page.getByText('Rincian invoice · 1',{exact:true}).click();
 assert.equal(await page.getByRole('link',{name:'PDF invoice'}).getAttribute('href'),'https://drive.google.com/test');
 assert.equal(await page.getByRole('cell',{name:'001/UPAH',exact:true}).isVisible(),true);
 console.log('PASS volunteer recap table, saved amounts, combined package exclusion, expandable invoice evidence');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});

