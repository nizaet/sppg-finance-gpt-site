const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),esbuild=require('esbuild'),React=require('react');
const{create,act}=require('react-test-renderer');
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'lpdh-cost-decimal-')),'ui.cjs');
 await esbuild.build({entryPoints:[path.join(root,'src/lpdh/LpdhSheets.jsx')],outfile:out,bundle:true,platform:'node',format:'cjs',define:{'import.meta.env':'{}'},plugins:[{name:'react-external',setup(build){build.onResolve({filter:/^react$/},()=>({path:require.resolve('react'),external:true}));}}]});
 const Sheet=require(out).default,text=node=>node.children.map(x=>typeof x==='string'?x:text(x)).join('');let view;
 const preview={rawTotal:9242.3,rawPerPortion:9242.3,weightedRawPagu:9242.12,rawStatus:'MELEBIHI PAGU',operationalTotal:3000.3,operationalPerPm:3000.3,operationalPagu:3000.1,operationalStatus:'MELEBIHI PAGU'};
 await act(async()=>{view=create(React.createElement(Sheet,{activeSheet:'B_BahanBaku',preview}));});
 for(const value of ['Rp 9.242,30','Rp 9.242,12','Rp 0,18','MELEBIHI PAGU'])assert.ok(text(view.root).includes(value),value);
 await act(async()=>view.update(React.createElement(Sheet,{activeSheet:'C_Operasional',preview})));
 for(const value of ['Rp 3.000,30','Rp 3.000,10','Rp 0,20'])assert.ok(text(view.root).includes(value),value);
 await act(async()=>view.update(React.createElement(Sheet,{activeSheet:'B_BahanBaku',preview:{...preview,rawPerPortion:9242.121}})));
 assert.ok(text(view.root).includes('< Rp 0,01'));view.unmount();
 console.log('PASS two-decimal cost/pagu, visible excess, small excess not displayed as zero');
})().catch(e=>{console.error(e);process.exitCode=1;});
