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
await page.setContent(deliveryHtml({...pkg,settings:{stamp:asset,positionLayoutVersion:2,positions:{stamp:{x:10,y:20,w:130,h:120}}}},'KUI'));
const stamp=page.locator('.asset.stamp');await stamp.scrollIntoViewIfNeeded();const box=await stamp.boundingBox();await page.mouse.move(box.x+40,box.y+40);await page.mouse.down();await page.mouse.move(box.x+70,box.y+60);await page.mouse.up();assert.ok(Math.abs(await stamp.evaluate(e=>parseFloat(e.style.left))-40)<.1);
assert.equal(await stamp.evaluate(e=>e.style.width),'130px');
await page.emulateMedia({media:'print'});assert.equal(await stamp.evaluate(e=>getComputedStyle(e).borderTopWidth),'0px');
console.log('PASS four editable A4 print formats, escaped invoice items, site kop and movable/sized stamp');
await page.emulateMedia({media:'screen'});
const logo=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=c.height=256;const x=c.getContext('2d');x.fillStyle='#16486d';x.beginPath();x.arc(128,128,120,0,Math.PI*2);x.fill();x.fillStyle='white';x.font='bold 50px Arial';x.textAlign='center';x.fillText('BGN',128,145);return c.toDataURL();});
const po={...pkg,settings:{logo,foundation:'YAYASAN MITRA MUKTI DERMAWAN SPPG CEMPLANG 2, JAWILAN, SERANG BANTEN',kitchen:'SPPG SERANG JAWILAN CEMPLANG 2',positions:{logo:{x:200,y:90,w:80,h:80}}}};
await page.setContent(deliveryHtml(po,'PO'));
for(const media of ['screen','print']){await page.emulateMedia({media});const bounds=await page.evaluate(()=>{const a=document.querySelector('.po-logo .asset').getBoundingClientRect(),b=document.querySelector('.po-kop-text').getBoundingClientRect();return{width:a.width,height:a.height,right:a.right,textLeft:b.left};});assert.equal(bounds.width,128);assert.equal(bounds.height,128);assert.ok(bounds.right<bounds.textLeft,'logo and header text never overlap, including saved legacy positions');}
await page.emulateMedia({media:'screen'});await page.screenshot({path:'../delivery-PO-logo-qa.png',fullPage:true});
const artwork=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=240;c.height=160;const x=c.getContext('2d');x.strokeStyle='#684698';x.lineWidth=4;x.beginPath();x.arc(110,80,67,0,Math.PI*2);x.stroke();x.font='bold 20px Arial';x.fillStyle='#684698';x.fillText('STEMPEL',64,88);const stamp=c.toDataURL();x.clearRect(0,0,240,160);x.strokeStyle='#152436';x.lineWidth=3;x.beginPath();x.moveTo(20,110);x.bezierCurveTo(80,0,75,160,115,60);x.bezierCurveTo(100,130,180,15,210,45);x.stroke();return {stamp,signature:c.toDataURL()};});
const signed={...pkg,document:{...pkg.document,site:'CEMPLANG'},settings:{...artwork,showDetails:false,signatory:'Mungkie',supervisor:'Diah Maulidiah, S.Ak.',positions:{signature:{x:-200,y:200,w:600,h:600},stamp:{x:300,y:200,w:400,h:400}}}};
for(const kind of ['PO','SJ','CKL','KUI']){await page.setContent(deliveryHtml(signed,kind));for(const media of ['screen','print']){await page.emulateMedia({media});assert.ok(await page.evaluate(()=>Array.from(document.querySelectorAll('.sign-space .asset')).every(el=>{const r=el.getBoundingClientRect(),s=el.closest('.sign-space').getBoundingClientRect(),name=el.closest('.signer').querySelector('.name').getBoundingClientRect();return r.left>=s.left-1&&r.right<=s.right+1&&r.top>=s.top-1&&r.bottom<name.top;})),'assets remain inside their own column and above names');if(kind==='KUI'){const result=await page.evaluate(()=>{const s=document.querySelector('.signer:last-child'),d=s.querySelector('.sign-date').getBoundingClientRect(),l=s.querySelector('.signer-label').getBoundingClientRect();return {date: s.querySelector('.sign-date').textContent,center:Math.abs((d.left+d.right)/2-(l.left+l.right)/2),above:d.bottom<=l.top};});assert.equal(result.date,'Serang, 6 Oktober 2026');assert.ok(result.above&&result.center<1);}}await page.emulateMedia({media:'screen'});await page.screenshot({path:`../delivery-signers-${kind}-qa.png`,fullPage:true});}
await page.setContent(deliveryHtml({...signed,settings:{...signed.settings,supervisorSignature:asset,supervisorStamp:asset}},'KUI'));
assert.equal(await page.locator('.signer:first-child [data-asset="supervisorSignature"]').count(),1);
assert.equal(await page.locator('.signer:last-child [data-asset="signature"]').count(),1);
assert.equal(await page.locator('.signer:last-child [data-asset="supervisorSignature"]').count(),0);
}finally{await browser.close();}

