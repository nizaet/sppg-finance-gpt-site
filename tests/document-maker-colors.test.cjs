const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),esbuild=require('esbuild');
const{chromium}=require('playwright');
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'maker-colors-')),'ui.js');
 await esbuild.build({stdin:{resolveDir:root,contents:`import{documentMakerStatus}from './src/documents/makerStatus.js';window.statusOf=documentMakerStatus;`,loader:'js'},outfile:out,bundle:true,format:'iife'});
 const browser=await chromium.launch({headless:true});try{
  const page=await browser.newPage();await page.setContent('<div class="lpdh-page"><div class="doc-workspace"><table class="doc-table"><tbody id="rows"></tbody></table></div></div>');await page.addScriptTag({path:out});await page.addStyleTag({path:path.join(root,'src/documents/documents.css')});
  const fixtures=[{status:'FINAL',makerId:1,makerStatus:'CREATED',makerApprovalStatus:'PENDING'}, {status:'FINAL',makerId:2,makerStatus:'CREATED',makerApprovalStatus:'APPROVED'},{status:'FINAL',makerId:3,makerStatus:'PAID'}, {status:'FINAL',makerInvoiceId:4},{status:'CANCELLED',makerId:5,makerPaid:true},{status:'FINAL',makerId:6,makerStatus:'CANCELLED',makerApprovalStatus:'APPROVED'}];
  const states=await page.evaluate(rows=>rows.map(window.statusOf),fixtures);
  assert.equal(states[0].className,'doc-maker-pending');assert.equal(states[0].label,'Sudah di Maker');
  assert.equal(states[1].className,'doc-maker-approved');assert.equal(states[1].label,'Sudah diapprove');
  assert.equal(states[2].className,'doc-maker-approved');assert.match(states[2].label,/PAID/);
  for(const index of [3,4,5])assert.equal(states[index].className,'');
  await page.evaluate(states=>{document.getElementById('rows').innerHTML=states.map((x,i)=>'<tr class="'+x.className+'"><td>'+i+'</td><td><span class="doc-maker-label '+x.className+'">'+x.label+'</span></td></tr>').join('');},states);
  for(const width of [1200,390]){
   await page.setViewportSize({width,height:800});assert.equal(await page.locator('tr').nth(0).evaluate(el=>getComputedStyle(el.cells[0]).backgroundColor),'rgb(255, 246, 216)');
   assert.equal(await page.locator('tr').nth(1).evaluate(el=>getComputedStyle(el.cells[0]).backgroundColor),'rgb(225, 244, 231)');
   assert.ok(await page.getByText('Sudah diapprove',{exact:true}).isVisible());
  }
  const source=fs.readFileSync(path.join(root,'src/documents/DocumentWorkspace.jsx'),'utf8');assert.ok(source.includes('className={documentMakerStatus(doc).className}'));
  console.log('PASS yellow Maker, green approved/PAID, neutral queued/cancelled, desktop/mobile styles and labels');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
