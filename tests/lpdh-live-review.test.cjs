const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const React = require('react');
const {create, act} = require('react-test-renderer');
const esbuild = require('esbuild');
const root = path.resolve(__dirname, '..');
const output = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'lpdh-live-review-')), 'test.cjs');
const text = node => node.children.map(x => typeof x === 'string' ? x : text(x)).join('');

(async () => {
  await esbuild.build({entryPoints:[path.join(root,'src/lpdh/LpdhWorkspace.jsx')],outfile:output,bundle:true,platform:'node',format:'cjs',loader:{'.css':'empty'},plugins:[{name:'isolated-fixture',setup(build){
    build.onResolve({filter:/^react$/},()=>({path:require.resolve('react'),external:true}));
    build.onResolve({filter:/lpdhApi\.js$/},()=>({path:'api',namespace:'fixture'}));
    build.onResolve({filter:/DocumentWorkspace\.jsx$/},()=>({path:'documents',namespace:'fixture'}));
    build.onLoad({filter:/.*/,namespace:'fixture'},args=>({contents:args.path==='api'?'export const lpdhApi=global.__lpdhFixture; export const arrayBufferToBase64=()=>""; export const downloadBase64=()=>{};':'export default function Documents(){return null}',loader:'js'}));
  }}]});
  let masters = {posyandu:[{name:'Pos Uji',pregnantLarge:5,breastfeedingLarge:7,balitaSmall:20}]};
  const daily = {pm:{rows:[{code:'KS-07',targetPm:5,distributed:4,received:3,bnba:true}],production:{produced:99,organoleptic:3,retainedSample:2}}};
  let savedDaily=0, previewed, reloads=0;
  global.__lpdhFixture = {
    getMasters:async()=>({data:masters}),getDaily:async()=>({data:daily}),getEffectiveDays:async()=>({dates:['2026-10-05']}),calendar:async()=>({items:[]}),reference:async()=>({rows:[]}),history:async()=>({items:[]}),
    preview:async()=>({pmRows:[],production:{produced:0}}),
    previewDraft:async(site,date,data)=>{previewed=structuredClone(data);return {previewSource:'CURRENT_FORM',pmRows:[],production:{produced:data.pm.production.produced}};},
    officialTemplateStatus:async()=>({installed:false}),saveMasters:async(site,data)=>{masters=data;reloads++;},saveDaily:async()=>{savedDaily++;}
  };
  global.window={location:{search:'?site=MAJA&date=2026-10-05&tab=daily'},clearTimeout(){},setTimeout(){},confirm:()=>false};
  const {default:Workspace}=require(output);
  let view;
  await act(async()=>{view=create(React.createElement(Workspace,{role:'OWNER'}));});
  const button = name => view.root.findAllByType('button').find(x=>text(x).trim()===name);
  assert.equal(view.root.findAllByType('select').find(x=>x.props['aria-label']==='BNBA KS-07').props.value,'Ya','boolean historical BNBA visible');
  const received = view.root.findAllByType('tr').find(x=>text(x).includes('KS-07')).findAllByType('input')[1];
  await act(async()=>received.props.onChange({target:{value:'2'}}));
  await act(async()=>button('Review LPDH / Sheet Excel').props.onClick());
  assert.equal(previewed.pm.rows.find(x=>x.code==='KS-07').received,2,'Review reads current unsaved form');
  assert.equal(savedDaily,0,'Preview navigation never saves');
  assert.ok(text(view.root).includes('termasuk perubahan belum disimpan'));
  await act(async()=>button('Data Harian dari Dokumen').props.onClick());
  await act(async()=>button('Hitung ulang total produksi').props.onClick());
  assert.equal(view.root.findAllByType('label').find(x=>text(x)==='Total diproduksi').findByType('input').props.value,'99','cancel retains production');
  global.window.confirm=()=>true;
  await act(async()=>button('Hitung ulang total produksi').props.onClick());
  assert.equal(view.root.findAllByType('label').find(x=>text(x)==='Total diproduksi').findByType('input').props.value,'9');
  await act(async()=>button('Master Data').props.onClick());
  const posRow=view.root.findAllByType('tr').find(x=>x.findAllByType('input').some(i=>i.props.value==='Pos Uji'));
  await act(async()=>posRow.findAllByType('input')[3].props.onChange({target:{value:'8'}}));
  await act(async()=>button('Simpan Semua Master').props.onClick());
  assert.equal(reloads,1);
  assert.equal(previewed.pm.rows.find(x=>x.code==='KS-07').targetPm,8,'saved master refreshes draft targets and review');
  assert.equal(previewed.pm.rows.find(x=>x.code==='KS-07').received,2,'actual edit survives master save');
  assert.equal(savedDaily,0);
  global.__lpdhFixture.previousRoutine=async()=>({sourceDate:'2026-10-02',targetDailyStatus:'DRAFT',hasDaily:true,lpdhNumber:'009/LPDH/TEST/X/2026',dailyDefaults:{pm:{rows:[{code:'KS-07',received:0,distributed:0,bnba:'Tidak'}],production:{produced:5,organoleptic:3,retainedSample:2}}}});
  await act(async()=>button('Data Harian dari Dokumen').props.onClick());
  await act(async()=>button('Tarik isian hari sebelumnya').props.onClick());
  assert.equal(previewed.pm.rows.find(x=>x.code==='KS-07').received,0,'copied explicit zero remains editable');
  assert.equal(previewed.pm.rows.find(x=>x.code==='KS-07').targetPm,8,'targets remain from current master');
  assert.equal(previewed.pm.production.produced,5,'previous production is a draft input, not a recalculation');
  assert.equal(previewed.lpdhNumber,'009/LPDH/TEST/X/2026','new-day number not old number');
  assert.equal(savedDaily,0,'standalone daily pull does not save automatically');
  await act(async()=>view.unmount());
  console.log('PASS live LPDH review: unsaved input, master reload, real-count preservation, boolean BNBA, production confirmation, no auto-save');
})().catch(error=>{console.error(error);process.exitCode=1;});
