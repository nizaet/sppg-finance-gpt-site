// Synthetic, offline browser acceptance. Never accesses a production account/API.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const esbuild = require('esbuild');
const root = path.resolve(__dirname, '..');
let browser;

(async () => {
  const {chromium} = require('playwright');
  const output = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'lpdh-mobile-')), 'fixture.js');
  await esbuild.build({stdin:{contents:`
    import React from 'react';import {createRoot} from 'react-dom/client';
    import Workspace from './src/lpdh/LpdhWorkspace.jsx';
    createRoot(document.getElementById('root')).render(<Workspace role="OWNER"/>);
  `,resolveDir:root,loader:'jsx'},outfile:output,bundle:true,format:'iife',platform:'browser',loader:{'.css':'empty'},plugins:[{name:'offline-fixture',setup(build){
    build.onResolve({filter:/lpdhApi\.js$/},()=>({path:'lpdh',namespace:'fixture'}));
    build.onResolve({filter:/documentApi\.js$/},()=>({path:'documents',namespace:'fixture'}));
    build.onLoad({filter:/.*/,namespace:'fixture'},args=>({contents:args.path==='lpdh'?'export const lpdhApi=window.testLpdhApi;export const downloadBase64=()=>{};export const arrayBufferToBase64=()=>"";':'export const documentApi=window.testDocumentApi;',loader:'js'}));
  }}]});
  const css=['src/lpdh/lpdh.css','src/documents/documents.css','src/auth/auth.css'].map(file=>fs.readFileSync(path.join(root,file),'utf8')).join('\n');
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage();
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',async route=>{
    if(route.request().url().startsWith('http://lpdh.test/')) return route.fulfill({contentType:'text/html',body:`<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0}${css}</style><nav class="sppg-session-bar sppg-session-bar--lpdh"><a>Kalkulator Maja</a><a>Kalkulator Cemplang</a><a>Pusat Operasional</a><a>LPDH Maja/Cemplang</a><a>Akuntan Maja</a><a>Akuntan Cemplang</a><button>Keluar</button></nav><div id="root"></div>`});
    throw new Error('Unexpected network request: '+route.request().url());
  });
  await page.goto('http://lpdh.test/?site=MAJA&date=2026-10-05&tab=masters');
  await page.evaluate(()=>{
    window.confirm=()=>true;window.testSaves=[];window.testDocuments=[];
    const volunteers=Array.from({length:20},(_,i)=>({code:'R'+i,name:'Relawan '+i,role:'Pengolah makanan',dailyRate:90000,status:'Aktif'}));
    let masters={identity:{sppgName:'Dapur Uji',sppgId:'SNG-UJI'},schools:[{code:'SD1',name:'Sekolah Dengan Nama Panjang Untuk Uji Layout',schoolType:'SD/MI',smallPortions:10,largePortions:20,staffLarge:3,phone:'0800000000',address:'Alamat uji'}, {code:'SD2',name:'Sekolah Kedua',schoolType:'PAUD',smallPortions:10}],posyandu:[{code:'P1',name:'Posyandu Uji',balitaSmall:4,pregnantLarge:2,breastfeedingLarge:1}],volunteers,operations:[{code:'gas',name:'Gas LPG',category:'GAS',unit:'tabung',defaultPrice:1000},{code:'sabun',name:'Sabun Pembersih',category:'Alat kebersihan',unit:'botol',defaultPrice:200}],vendor:{name:'Vendor Uji'}};
    let daily={lpdhNumber:'001/LPDH/UJI/X/2026',rawMaterials:[{name:'Beras',qty:2,unit:'kg',price:100,invoiceNo:'BB/UJI',sourceDocumentId:1}],operations:[{description:'Gas LPG',qty:2,price:1000,invoiceNo:'OP/UJI',sourceDocumentId:2}],volunteerPayments:volunteers.map(v=>({name:v.name,volunteerCode:v.code,role:v.role,date:'2026-10-05',dailyRate:v.dailyRate,workDays:1,sourceDocumentId:3,receiptNo:'KW/UJI'})),incentiveRecipients:[{name:'Guru Uji',type:'Guru',unitName:'SD Uji',amount:100,sourceDocumentId:4}],topups:[{date:'2026-10-05',reference:'SP2D/UJI',rawAmount:100,operationalAmount:200,incentiveAmount:300}]};
    window.testLpdhApi={getMasters:async()=>({data:masters}),getDaily:async()=>({data:daily}),getEffectiveDays:async()=>({dates:['2026-10-05']}),calendar:async()=>({items:[]}),reference:async()=>({rows:[]}),history:async()=>({items:[]}),preview:async()=>({effective:true,pmRows:[],production:{produced:0}}),previewDraft:async()=>({effective:true,pmRows:[],production:{produced:0}}),officialTemplateStatus:async()=>({installed:false}),saveMasters:async(site,data)=>{masters=data;window.testSaves.push(data);},saveDaily:async(site,date,data)=>{daily=data;window.testSaves.push(data);}};
    const header={issuerName:'Vendor Uji',recipientName:'Dapur Uji',recipientAddress:'Alamat panjang uji',documentProfileKey:'KOPERASI'};
    window.testDocumentApi={master:async()=>({profiles:{KOPERASI:header,YAYASAN:header},categories:['Gas','Alat kebersihan'],items:[{recordKey:'gas',itemName:'Gas LPG',kind:'OPERASIONAL',category:'Gas',unit:'tabung',unitPrice:1000},{recordKey:'sabun',itemName:'Sabun Pembersih',kind:'OPERASIONAL',category:'Alat kebersihan',unit:'botol',unitPrice:200}],volunteers,recipients:[{name:'Guru Uji',recipientType:'Guru',unitName:'SD Uji'}]}),list:async()=>({documents:window.testDocuments}),calendar:async()=>({items:[]}),suggestNumber:async()=>({documentNumber:'001/OP/UJI/X/2026'}),create:async payload=>{window.testSavedInvoice=payload;const doc={id:1,site:payload.site,serviceDate:payload.service_date,documentType:payload.document_type,documentNumber:payload.document_number,header:payload.header_payload,items:payload.items.map(x=>({itemName:x.item_name})),total:payload.items.reduce((sum,x)=>sum+x.quantity*x.unit_price,0),status:'DRAFT'};window.testDocuments.push(doc);return {document:doc};}};
  });
  await page.addScriptTag({content:fs.readFileSync(output,'utf8')});
  await page.getByRole('button',{name:'Master Data',exact:true}).click();
  await page.getByRole('tab',{name:'Sekolah',exact:true}).waitFor();
  const assertLayout = async (width, label) => {
    const layout=await page.evaluate(()=>({viewport:innerWidth,body:document.documentElement.scrollWidth,overflow:[...document.querySelectorAll('.lpdh-tabbed-form input,.lpdh-tabbed-form select,.lpdh-form-tabs button,.lpdh-page .doc-table td,.lpdh-page .doc-actions select')].filter(el=>{const r=el.getBoundingClientRect();return r.width>0&&(r.right>innerWidth+1||r.left< -1);}).map(el=>el.getAttribute('aria-label')||el.className)}));
    assert.ok(layout.body<=width+1,`${width}px ${label}: page overflow ${JSON.stringify(layout)}`);
    if(width<=1100) assert.deepEqual(layout.overflow,[],`${width}px ${label}: controls outside viewport`);
    if(width<=1100){const scrollers=await page.locator('.lpdh-page .lpdh-table-wrap,.lpdh-page .doc-table-wrap,.lpdh-form-tabs').evaluateAll(nodes=>nodes.filter(el=>el.scrollWidth>el.clientWidth+1).map(el=>el.className));assert.deepEqual(scrollers,[],`${width}px ${label}: horizontal form scrolling`);}
  };
  for(const width of [320,360,412,768,904,1100,1440]){
    await page.setViewportSize({width,height:900});
    await page.getByRole('button',{name:'Master Data',exact:true}).click();
    for(const tab of ['Sekolah','Posyandu','Total Porsi','Relawan','Operasional','Identitas','Vendor & Aset','Pengesah','Parameter','Data Lama']){
      await page.getByRole('tab',{name:tab,exact:true}).click();await assertLayout(width,'master '+tab);
    }
    await page.getByRole('button',{name:'Data Harian dari Dokumen',exact:true}).click();
    for(const tab of ['A · Penerima Manfaat','B · Bahan Baku','C · Operasional','C1 · Relawan','Guru / Kader','Bukti & Referensi','D · Insentif Yayasan','E / F · Saldo & TopUp','Upload']){
      await page.getByRole('tab',{name:tab,exact:true}).click();await assertLayout(width,'daily '+tab);
    }
    await page.getByRole('button',{name:'Buat Invoice & Kuitansi',exact:true}).click();
    await page.getByRole('combobox',{name:'Jenis dokumen'}).selectOption('OPERASIONAL');
    await page.getByLabel('Cari item dari master',{exact:true}).fill('saBun');
    await page.getByRole('button',{name:'Tambah Sabun Pembersih dari hasil pencarian'}).click();
    await page.getByLabel('Cari item dari master',{exact:true}).fill('gas');
    await page.getByRole('button',{name:'Tambah Gas LPG dari hasil pencarian'}).click();
    await assertLayout(width,'invoice inputs');
    await page.getByLabel('Cari item dalam invoice',{exact:true}).fill('gas');
    await page.getByLabel('Harga atau nominal',{exact:true}).fill('1200');
    await page.getByRole('button',{name:'Simpan draft',exact:true}).click();
    const payload=await page.evaluate(()=>window.testSavedInvoice);
    assert.equal(payload.items.length,2,'filtered save retains hidden invoice lines');
    assert.equal(payload.items[0].unit_price,200,'filtered edits do not mutate first hidden row');
    assert.equal(payload.items[1].unit_price,1200);
    await assertLayout(width,'invoice register');
    await page.getByRole('combobox',{name:'Jenis dokumen'}).selectOption('UPAH_RELAWAN');
    await page.getByRole('button',{name:'Siapkan penerima dari master'}).click();
    await page.getByLabel('Cari penerima dalam kuitansi',{exact:true}).fill('Relawan 19');
    assert.equal(await page.locator('.doc-form tbody tr').count(),1);
    await assertLayout(width,'receipt search');
  }
  await page.setViewportSize({width:360,height:900});
  await page.getByRole('button',{name:'Master Data',exact:true}).click();
  await page.getByRole('tab',{name:'Relawan',exact:true}).click();
  await page.getByLabel('Cari relawan',{exact:true}).fill('Relawan 19');
  await page.getByLabel('Tarif/Hari · baris 20',{exact:true}).fill('123000');
  await page.getByRole('tab',{name:'Sekolah',exact:true}).click();
  await page.getByRole('tab',{name:'Relawan',exact:true}).click();
  assert.equal(await page.getByLabel('Tarif/Hari · baris 20',{exact:true}).inputValue(),'123000','tab switch preserves draft');
  await page.setViewportSize({width:768,height:900});
  assert.equal(await page.getByLabel('Tarif/Hari · baris 20',{exact:true}).inputValue(),'123000','unfold preserves draft');
  await assertLayout(768,'unfolded draft');
  await page.setViewportSize({width:360,height:900});
  assert.equal(await page.getByLabel('Tarif/Hari · baris 20',{exact:true}).inputValue(),'123000','refold preserves draft');
  await page.getByRole('tab',{name:'Relawan',exact:true}).focus();
  await page.keyboard.press('End');
  assert.equal(await page.getByRole('tab',{name:'Parameter',exact:true}).getAttribute('aria-selected'),'true');
  assert.equal(await page.getByRole('tab',{name:'Parameter',exact:true}).evaluate(el=>el===document.activeElement),true);
  await page.getByRole('button',{name:'Data Harian dari Dokumen',exact:true}).click();
  await page.getByRole('tab',{name:'C1 · Relawan',exact:true}).click();
  await page.getByLabel('Cari relawan',{exact:true}).fill('Relawan 19');
  assert.equal(await page.getByLabel('Tarif/Hari · baris 20',{exact:true}).isDisabled(),true,'FINAL locked in actual browser');
  assert.equal(await page.getByLabel('Cari relawan',{exact:true}).isEnabled(),true,'search usable outside lock');
  await page.getByRole('button',{name:'Buat Invoice & Kuitansi',exact:true}).click();
  await page.getByRole('combobox',{name:'Jenis dokumen'}).selectOption('UPAH_RELAWAN');
  await page.getByRole('combobox',{name:'Cakupan paket'}).selectOption('ALL');
  await page.getByRole('button',{name:'Siapkan penerima dari master'}).click();
  const recap=page.getByRole('region',{name:'Rekap invoice gabungan'});
  assert.match(await recap.innerText(),/20 penerima/);
  assert.equal(await page.locator('.doc-form tbody tr').count(),0,'combined recipients collapsed initially');
  await recap.getByRole('button',{name:/Insentif Guru/}).click();
  await page.getByLabel('Harga atau nominal',{exact:true}).fill('30000');
  assert.match(await recap.innerText(),/30\.000/,'recap updates when amount edited');
  await page.setViewportSize({width:768,height:900});
  await recap.screenshot({path:path.resolve(root,'../../outputs/fold-rekap-invoice.png')});
  await recap.getByRole('button',{name:/Insentif Guru/}).click();
  assert.equal(await page.locator('.doc-form tbody tr').count(),0);
  await page.getByRole('button',{name:'Simpan draft',exact:true}).click();
  const combined=await page.evaluate(()=>window.testSavedInvoice);
  assert.equal(combined.items.length,21,'collapsed groups still saved in full');
  assert.equal(combined.items[20].unit_price,30000);
  assert.equal(combined.header_payload.combinedPayments,true);
  await recap.getByRole('button',{name:/Upah Relawan/}).click();
  for(const width of [360,412,700,768,904,1100,1440]){
    await page.setViewportSize({width,height:900});await assertLayout(width,'combined payment recap');
    const columns=await page.locator('.lpdh-page .doc-form .doc-table').evaluate(el=>getComputedStyle(el).display);
    assert.equal(columns,width>=700?'table':'block','fold-open has compact desktop table');
  }
  await page.setViewportSize({width:768,height:900});
  await page.screenshot({path:path.resolve(root,'../../outputs/fold-invoice-gabungan.png'),fullPage:true});
  await page.setViewportSize({width:360,height:900});
  await page.evaluate(()=>{window.testLpdhApi.preview=async()=>({incentiveCalculated:5572000});});
  await page.getByRole('button',{name:'Invoice Insentif Mitra / Yayasan',exact:true}).click();
  await page.getByLabel('Harga atau nominal',{exact:true}).waitFor();
  assert.equal(await page.getByLabel('Harga atau nominal',{exact:true}).inputValue(),'5572000');
  await assertLayout(360,'Mitra incentive invoice');
  await page.getByRole('button',{name:'Simpan draft',exact:true}).click();
  const mitra=await page.evaluate(()=>window.testSavedInvoice);
  assert.equal(mitra.document_type,'INSENTIF_MITRA');
  assert.equal(mitra.header_payload.documentProfileKey,'YAYASAN');
  assert.equal(mitra.items.length,1);assert.equal(mitra.items[0].unit_price,5572000);
  await page.evaluate(()=>{
    window.testDocuments.push({id:99,site:'MAJA',serviceDate:'2026-10-05',documentType:'OPERASIONAL',documentNumber:'TEST-MAKER-CYCLE',header:{},items:[],total:1000,status:'FINAL',driveUri:'https://drive.google.com/synthetic',makerId:200,makerInvoiceId:100});
    window.dispatchEvent(new Event('focus'));
  });
  await page.getByRole('button',{name:'Sudah di Data Maker #200',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Sudah di Data Maker #200',exact:true}).isDisabled(),true);
  await page.evaluate(()=>{window.testDocuments.find(x=>x.id===99).makerId=null;document.dispatchEvent(new Event('visibilitychange'));});
  await page.getByRole('button',{name:'Export ke Data Maker',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Export ke Data Maker',exact:true}).isEnabled(),true);
  assert.equal(await page.getByText('Belum masuk Data Maker',{exact:true}).count(),1);
  await page.evaluate(()=>{window.confirm=()=>true;window.testDocumentApi.exportMaker=async()=>{const doc=window.testDocuments.find(x=>x.id===99);doc.makerId=201;return {maker_id:201,accountant_invoice_id:100,duplicate:false};};});
  await page.getByRole('button',{name:'Export ke Data Maker',exact:true}).click();
  await page.getByRole('button',{name:'Sudah di Data Maker #201',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Sudah di Data Maker #201',exact:true}).isDisabled(),true);
  await page.evaluate(()=>{window.testLpdhApi.preview=async()=>({ready:false,errorCount:1,checks:[{no:'23',check:'Saldo VA',ok:false,status:'PERIKSA',detail:'Selisih saldo'}],pmRows:[],production:{produced:0}});});
  await page.getByRole('button',{name:'Unduh Excel & Riwayat',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'Isi Template & Unduh DRAFT',exact:true}).isEnabled(),true);
  await page.getByRole('button',{name:'23. Saldo VA · Buka isian',exact:true}).click();
  await page.getByLabel('Saldo VA rekening koran',{exact:true}).waitFor();
  assert.equal(await page.getByRole('tab',{name:'E / F · Saldo & TopUp',exact:true}).getAttribute('aria-selected'),'true');
  assert.ok(await page.locator('.lpdh-issue-focus').count()>0,'related balance field visibly highlighted');
  assert.deepEqual(errors,[],'no browser errors');
  await browser.close();
  console.log('PASS offline browser: all master/daily tabs and invoice/receipt cards at 320/360/412/768/904/1100/1440px; no mobile horizontal scrolling; keyboard focus, editable drafts, locked FINAL, typed search and complete filtered saves');
})().catch(async error=>{console.error(error);await browser?.close();process.exitCode=1;});
