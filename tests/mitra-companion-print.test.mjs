import assert from 'node:assert/strict';
import {createRequire}from'node:module';
import fs from 'node:fs';
import{deliveryHtml}from'../src/delivery/deliveryPrint.mjs';
const require=createRequire(import.meta.url),{chromium}=require('playwright');
const pkg={document:{id:99,site:'CEMPLANG',status:'FINAL',documentType:'INSENTIF_MITRA',documentNumber:'001/IM/X/2026',serviceDate:'2026-10-14',total:6046000,header:{issuerName:'YAYASAN UJI MITRA',senderCompany:'YAYASAN UJI MITRA',senderSignatory:'PENGURUS UJI'},items:[{itemName:'Insentif Mitra HPE',quantity:1,unit:'hari',unitPrice:6046000,lineTotal:6046000}]},numbers:{KUI_MITRA:'001/KUI.Banper/IM/X/2026'},dates:{KUI_MITRA:'2026-10-15'},settings:{byKind:{KUI:{signatory:'VENDOR SALAH',signature:'data:image/png;base64,vendor'},KUI_MITRA:{supervisor:'PENGAWAS UJI'}}}};
for(const kind of ['PO','SJ','CKL','KUI'])assert.throws(()=>deliveryHtml(pkg,kind));
assert.throws(()=>deliveryHtml({...pkg,document:{...pkg.document,status:'CANCELLED'}},'KUI_MITRA'));
const browser=await chromium.launch({headless:true});try{
 const page=await browser.newPage();await page.setContent(deliveryHtml(pkg,'KUI_MITRA'));
 const text=await page.locator('.paper').innerText();
 for(const part of ['BADAN GIZI NASIONAL','YAYASAN UJI MITRA','Insentif Mitra HPE 2026-10-14','15 Oktober 2026','Rp 6.046.000','PENGURUS UJI'])assert.ok(text.includes(part),part);
 assert.ok(!text.includes('VENDOR SALAH'));assert.equal(await page.locator('.asset.signature,.asset.stamp').count(),0);
 fs.mkdirSync('tmp/pdfs',{recursive:true});await page.emulateMedia({media:'print'});await page.pdf({path:'tmp/pdfs/mitra-companion-test.pdf',format:'A4',printBackground:true});
 await page.screenshot({path:'tmp/pdfs/mitra-companion-test.png',fullPage:true});
 console.log('PASS Mitra invoice amount/payee, HPE+1, isolated assets, canceled guard; synthetic PDF generated');
}finally{await browser.close();}
