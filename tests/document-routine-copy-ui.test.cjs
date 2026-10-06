const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const os=require('node:os');
const React=require('react');
const {create,act}=require('react-test-renderer');
const esbuild=require('esbuild');
const root=path.resolve(__dirname,'..');
const output=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'routine-copy-')),'test.cjs');
const text=node=>node.children.map(x=>typeof x==='string'?x:text(x)).join('');
let confirmed=false,serial=231;
const records=[],saved=[],dailyCopies=[],downloads=[];
const header={issuerName:'Penerbit Uji',recipientName:'Dapur Uji',recipientAddress:'Alamat Uji',senderSignatory:'Pengirim Uji',documentProfileKey:'KOPERASI'};
const op=number=>({sourceNumber:number,sourceDate:'2026-10-05',documentType:'OPERASIONAL',header:{...header},items:[{itemName:'Gas uji',category:'Gas',quantity:2,unit:'tabung',unitPrice:100,metadata:{itemCode:'gas'}}]});
global.window={confirm:()=>confirmed,addEventListener(){},removeEventListener(){}};
global.__ROUTINE_API={
  master:async()=>({profiles:{KOPERASI:header,YAYASAN:header},categories:['Gas'],items:[],volunteers:[{code:'R1',name:'Relawan Aktif',role:'Pengolah',dailyRate:90000}]}),
  list:async()=>({documents:structuredClone(records)}),calendar:async()=>({items:[]}),
  suggestNumber:async(site,date,type)=>({documentNumber:`${type==='OPERASIONAL'?serial+1:1}/OP/MANUAL/IX/2026`}),
  previousRoutine:async()=>({site:'MAJA',serviceDate:'2026-10-06',sourceDate:'2026-10-05',hasDaily:true,dailyDefaults:{pm:{rows:[{code:'KS-09',received:20,distributed:20}]}},templates:[op('230/OP/MANUAL/IX/2026'),op('231/OP/MANUAL/IX/2026')]}),
  create:async payload=>{saved.push(payload);serial=Number(payload.document_number.split('/')[0]);const doc={id:saved.length,site:'MAJA',serviceDate:'2026-10-06',documentNumber:payload.document_number,documentType:payload.document_type,header:payload.header_payload,items:payload.items.map(x=>({itemName:x.item_name})),total:200,status:'DRAFT'};records.push(doc);return {document:doc};},
  excel:async()=>({filename:'test.xlsx',mimeType:'test/xlsx',contentBase64:'UEs='})
};
(async()=>{
  await esbuild.build({entryPoints:[path.join(root,'src/documents/DocumentWorkspace.jsx')],outfile:output,bundle:true,platform:'node',format:'cjs',loader:{'.css':'empty'},plugins:[{name:'fixture',setup(build){
    build.onResolve({filter:/^react$/},()=>({path:require.resolve('react'),external:true}));
    build.onResolve({filter:/documentApi\.js$/},()=>({path:'api',namespace:'fixture'}));
    build.onResolve({filter:/lpdhApi\.js$/},()=>({path:'lpdh',namespace:'fixture'}));
    build.onLoad({filter:/.*/,namespace:'fixture'},args=>({contents:args.path==='api'?'export const documentApi=global.__ROUTINE_API;':'export const lpdhApi={};export const downloadBase64=(...args)=>global.__routineDownload(...args);',loader:'js'}));
  }}]});
  global.__routineDownload=(...args)=>downloads.push(args);
  const {default:Workspace}=require(output);let view;
  const render=()=>React.createElement(Workspace,{site:'MAJA',serviceDate:'2026-10-06',onRoutineDaily:async value=>dailyCopies.push(value)});
  await act(async()=>{view=create(render());});
  const button=label=>view.root.findAllByType('button').find(node=>text(node).trim()===label);
  await act(async()=>button('Tarik isian rutin sebagai draft').props.onClick());
  assert.equal(dailyCopies.length,0,'cancel is non-mutating');
  assert.equal(saved.length,0);
  confirmed=true;
  await act(async()=>button('Tarik isian rutin sebagai draft').props.onClick());
  assert.equal(dailyCopies.length,1);
  assert.equal(saved.length,0,'document templates remain unsaved');
  assert.ok(text(view.root).includes('Antrean tarikan · 3 belum disimpan'),'two operational invoices plus current master volunteers');
  const number=()=>view.root.findAllByType('label').find(node=>text(node).includes('Nomor invoice')).findByType('input');
  assert.equal(number().props.value,'232/OP/MANUAL/IX/2026');
  await act(async()=>button('Simpan draft').props.onClick());
  assert.equal(saved[0].document_number,'232/OP/MANUAL/IX/2026');
  assert.equal(saved[0].service_date,'2026-10-06');
  assert.ok(text(view.root).includes('Antrean tarikan · 2 belum disimpan'));
  const second=view.root.findAllByType('button').find(node=>text(node).includes('231/OP/MANUAL/IX/2026'));
  await act(async()=>second.props.onClick());
  assert.equal(number().props.value,'233/OP/MANUAL/IX/2026');
  await act(async()=>button('Simpan draft').props.onClick());
  assert.equal(saved.length,2,'multiple invoices remain separate');
  const volunteer=view.root.findAllByType('button').find(node=>text(node).includes('Master relawan'));
  await act(async()=>volunteer.props.onClick());
  assert.equal(view.root.findByProps({'aria-label':'Nama baris 1'}).props.value,'Relawan Aktif');
  assert.equal(view.root.findByProps({'aria-label':'Harga atau nominal'}).props.value,90000);
  assert.equal(view.root.findByProps({'aria-label':'Jumlah'}).props.disabled,true);
  assert.equal(view.root.findAllByType('label').find(node=>text(node)==='Referensi pembayaran (jika tersedia)').findByType('input').props.value,'');
  records[0].status='FINAL';records[0].driveUri='https://example.test/pdf';records[0].driveExcelUri=null;
  await act(async()=>button('Refresh register').props.onClick());
  assert.ok(button('Simpan ke Drive'),'partial pair exposes retry even if PDF already archived');
  await act(async()=>button('Unduh Excel').props.onClick());
  assert.equal(downloads[0][0],'test.xlsx');
  await act(async()=>view.unmount());
  console.log('PASS routine UI: confirmed choices, draft queue, independent invoices, latest numbering, master daily wages, Excel and partial retry');
})().catch(error=>{console.error(error);process.exitCode=1;});
