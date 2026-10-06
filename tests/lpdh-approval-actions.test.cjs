const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const React = require('react');
const {create, act} = require('react-test-renderer');
const esbuild = require('esbuild');
const text = n => n.children.map(x => typeof x === 'string' ? x : text(x)).join('');
(async()=>{
  const output=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'lpdh-approval-')),'test.cjs');
  await esbuild.build({entryPoints:[path.join(__dirname,'../src/lpdh/ApprovalActions.jsx')],outfile:output,bundle:true,platform:'node',format:'cjs',plugins:[{name:'mock',setup(build){
    build.onResolve({filter:/^react$/},()=>({path:require.resolve('react'),external:true}));
    build.onResolve({filter:/lpdhApi\.js$/},()=>({path:'api',namespace:'mock'}));
    build.onLoad({filter:/.*/,namespace:'mock'},()=>({contents:'export const lpdhApi=global.approvalApi;',loader:'js'}));
  }}]});
  let confirmed=false, calls=0, refreshed=0, error=false;
  const tab={document:{body:{}},location:{},close(){}};
  global.window={open:()=>tab,confirm:()=>confirmed};
  const oldTimeout=global.setTimeout;
  global.setTimeout=(fn,delay,...args)=>delay===300000?oldTimeout(fn,delay,...args).unref():oldTimeout(fn,delay,...args);
  global.approvalApi={
    approvalPreview:async()=>({hash:'printed-hash',contentBase64:'cGRm',validation:{ready:false}}),
    approvalFinalize:async(site,day,hash)=>{assert.equal(site,'MAJA');assert.equal(day,'2026-10-05');assert.equal(hash,'printed-hash');calls++;if(error)throw Error('Drive belum tersimpan');},
    saveDaily:()=>{throw Error('Preview must not save or finalize real daily data');}
  };
  const Component=require(output).default;
  let view;await act(async()=>{view=create(React.createElement(Component,{site:'MAJA',serviceDate:'2026-10-05',daily:{},onSaved:()=>refreshed++}));});
  const button=prefix=>view.root.findAllByType('button').find(n=>text(n).startsWith(prefix));
  assert.equal(button('Finalkan').props.disabled,true);
  await act(async()=>button('Buka Pratinjau').props.onClick());
  assert.ok(tab.location.href.startsWith('blob:'));assert.equal(button('Finalkan').props.disabled,false);
  await act(async()=>button('Finalkan').props.onClick());assert.equal(calls,0,'confirmation can reject');
  confirmed=true;error=true;
  await act(async()=>button('Finalkan').props.onClick());assert.equal(refreshed,0);assert.ok(text(view.root).includes('Drive belum tersimpan'));
  error=false;
  await act(async()=>button('Finalkan').props.onClick());assert.equal(refreshed,1);assert.ok(text(view.root).includes('link masuk ke D_Insentif'));
  await act(async()=>view.unmount());global.setTimeout=oldTimeout;
  console.log('PASS approval UI: read-only PDF preview, explicit confirmation, correct printed hash, failed Drive remains non-final, refresh after success');
})().catch(error=>{console.error(error);process.exitCode=1;});
