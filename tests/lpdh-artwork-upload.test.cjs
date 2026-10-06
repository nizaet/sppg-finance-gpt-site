const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const React = require('react');
const {create, act} = require('react-test-renderer');
const esbuild = require('esbuild');
const text = n => n.children.map(c => typeof c === 'string' ? c : text(c)).join('');
(async () => {
  const output = path.join(fs.mkdtempSync(path.join(os.tmpdir(),'lpdh-artwork-')),'test.cjs');
  await esbuild.build({entryPoints:[path.join(__dirname,'../src/lpdh/LpdhForms.jsx')],outfile:output,bundle:true,platform:'node',format:'cjs',define:{'import.meta.env':'{}'},plugins:[{name:'react',setup(build){build.onResolve({filter:/^react$/},()=>({path:require.resolve('react'),external:true}));}}]});
  const {MasterPanel} = require(output);
  const readers = []; let current;
  global.FileReader = class {
    constructor(){readers.push(this);}
    readAsDataURL(){}
    abort(){this.onloadend?.();}
    finish(value){this.result=value;this.onload?.();this.onloadend?.();}
  };
  const api = {officialTemplateStatus:async()=>({installed:true})};
  function Fixture(){const [masters,setMasters]=React.useState({assets:{vendorLogo:'keep'}});current=masters;return React.createElement(MasterPanel,{site:'MAJA',masters,setMasters,api,issueTarget:{tab:'signers',token:1}});}
  let view; await act(async()=>{view=create(React.createElement(Fixture));});
  const upload = label => view.root.findAllByType('label').find(n=>text(n).startsWith(label)).findByType('input');
  await act(async()=>{upload('TTD Kepala SPPG').props.onChange({target:{files:[{size:100}]}});upload('Stempel SPPG').props.onChange({target:{files:[{size:100}]}});});
  assert.equal(view.root.findAllByType('button').find(n=>text(n).includes('Simpan Semua Master')).props.disabled,true);
  await act(async()=>readers[1].finish('data:image/png;base64,stamp'));
  await act(async()=>readers[0].finish('data:image/png;base64,signature'));
  assert.equal(current.assets.approvalSppgStamp,'data:image/png;base64,stamp');
  assert.equal(current.assets.approvalSppgSignature,'data:image/png;base64,signature');
  assert.equal(current.assets.vendorLogo,'keep');
  assert.equal(view.root.findAllByType('button').find(n=>text(n).includes('Simpan Semua Master')).props.disabled,false);
  await act(async()=>view.unmount());
  console.log('PASS concurrent artwork uploads preserve both files and existing assets; save waits for readers');
})().catch(error=>{console.error(error);process.exitCode=1;});
