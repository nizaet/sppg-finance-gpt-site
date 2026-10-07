import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {deliveryHtml,terbilang} from '../src/delivery/deliveryPrint.mjs';
const require=createRequire(import.meta.url);const {chromium}=require('playwright');
assert.equal(terbilang(125000).trim(),'seratus dua puluh lima ribu');
const pkg={document:{site:'MAJA',documentType:'BAHAN_BAKU',documentNumber:'220/BB/MMD/X/2026',serviceDate:'2026-10-05',total:25000,header:{issuerName:'KOPERASI\nMAJA MUDA MADYA',issuerAddress:'Alamat uji',senderSignatory:'Pengirim Uji'},items:[{itemName:'Beras <uji>',quantity:2,unit:'kg',unitPrice:12500,lineTotal:25000}]},settings:{},numbers:{PO:'PO/2026/X/001',SJ:'SJ/202610/001',CKL:'CKL/202610/001',KUI:'001/KUI.Banper/BB/X/2026'},dates:{PO:'2026-10-03',SJ:'2026-10-04',CKL:'2026-10-04',KUI:'2026-10-06'}};
const browser=await chromium.launch({headless:true});
for(const kind of ['PO','SJ','CKL'])assert.ok(!deliveryHtml(pkg,kind).includes('Invoice acuan:'));
assert.ok(!deliveryHtml({...pkg,document:{...pkg.document,items:[{...pkg.document.items[0],metadata:{note:'RAHASIA CATATAN BAHAN'}}]}},'SJ').includes('RAHASIA CATATAN BAHAN'));
assert.ok(deliveryHtml({...pkg,settings:{byKind:{PO:{foundation:'KOP KHUSUS PO'},KUI:{foundation:'KOP KHUSUS KUITANSI'}}}},'PO').includes('KOP KHUSUS PO'));
assert.ok(!deliveryHtml({...pkg,settings:{byKind:{PO:{foundation:'KOP KHUSUS PO'},KUI:{foundation:'KOP KHUSUS KUITANSI'}}}},'KUI').includes('KOP KHUSUS PO'));
try{const page=await browser.newPage();for(const kind of ['PO','SJ','CKL','KUI']){
  await page.setContent(deliveryHtml(pkg,kind));
  assert.equal(await page.locator('.paper').getAttribute('contenteditable'),'true');
  assert.equal(await page.getByText('Beras <uji>',{exact:true}).count(),1);
  assert.equal(await page.locator('script').count(),1);
  await page.locator('.title').fill('Judul edit cetak');
  assert.equal(await page.locator('.title').textContent(),'Judul edit cetak');
  await page.emulateMedia({media:'print'});
  assert.equal(await page.locator('.toolbar').isVisible(),false);
  await page.emulateMedia({media:'screen'});
  await page.screenshot({path:`../delivery-${kind}-qa.png`,fullPage:true});
}await page.setContent(deliveryHtml({...pkg,document:{...pkg.document,site:'CEMPLANG'}},'CKL'));assert.equal(await page.getByText(/YAYASAN MITRA MUKTI DERMAWAN/).count(),1);
const asset='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQAAAABJRU5ErkJggg==';
await page.setContent(deliveryHtml({...pkg,settings:{stamp:asset,positions:{stamp:{x:10,y:20,w:130,h:120}}}},'KUI'));
const stamp=page.locator('.asset.stamp');await stamp.scrollIntoViewIfNeeded();const box=await stamp.boundingBox();await page.mouse.move(box.x+40,box.y+40);await page.mouse.down();await page.mouse.move(box.x+70,box.y+60);await page.mouse.up();assert.equal(await stamp.evaluate(e=>e.style.left),'40px');
assert.equal(await stamp.evaluate(e=>e.style.width),'130px');
await page.emulateMedia({media:'print'});assert.equal(await stamp.evaluate(e=>getComputedStyle(e).borderTopWidth),'0px');
console.log('PASS four editable A4 print formats, escaped invoice items, site kop and movable/sized stamp');
await page.emulateMedia({media:'screen'});
const logo=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=c.height=256;const x=c.getContext('2d');x.fillStyle='#16486d';x.beginPath();x.arc(128,128,120,0,Math.PI*2);x.fill();x.fillStyle='white';x.font='bold 50px Arial';x.textAlign='center';x.fillText('BGN',128,145);return c.toDataURL();});
const po={...pkg,settings:{logo,foundation:'YAYASAN MITRA MUKTI DERMAWAN SPPG CEMPLANG 2, JAWILAN, SERANG BANTEN',kitchen:'SPPG SERANG JAWILAN CEMPLANG 2',positions:{logo:{x:200,y:90,w:80,h:80}}}};
await page.setContent(deliveryHtml(po,'PO'));
for(const media of ['screen','print']){await page.emulateMedia({media});const bounds=await page.evaluate(()=>{const a=document.querySelector('.po-logo .asset').getBoundingClientRect(),b=document.querySelector('.po-kop-text').getBoundingClientRect();return{width:a.width,height:a.height,right:a.right,textLeft:b.left};});assert.equal(bounds.width,128);assert.equal(bounds.height,128);assert.ok(bounds.right<bounds.textLeft,'logo and header text never overlap, including saved legacy positions');}
await page.emulateMedia({media:'screen'});await page.screenshot({path:'../delivery-PO-logo-qa.png',fullPage:true});
}finally{await browser.close();}
