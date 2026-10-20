const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const deps = process.env.SPPG_UI_TEST_MODULES || path.join(root, 'node_modules');
const React = require(deps + '/react');
const { act, create } = require(deps + '/react-test-renderer');
const esbuild = require(deps + '/esbuild');
const temp = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'sppg-calendar-actions-'));
const output = path.join(temp, 'test.cjs');
const configs = new Map();
function loadConfig(file) {
  if (configs.has(file)) return configs.get(file);
  let code = fs.readFileSync(path.join(root, file), 'utf8');
  const env = { console, process, defineConfig: x => x, react: () => ({ name: 'react' }) };
  code = code.replace(/^import\s+(\w+)\s+from\s+["'](\.\/[^"']+)["'];?\s*$/gm, (_, name, dep) => { env[name] = loadConfig(dep.slice(2)); return ''; });
  code = code.replace(/^import .*;\s*$/gm, '').replace(/export default /g, 'result = ');
  vm.createContext(env); vm.runInContext(code, env, { filename: file });
  configs.set(file, env.result); return env.result;
}
const plugins = loadConfig('vite.po-list-independent.config.js').plugins.flat().filter(Boolean);
const ordered = [...plugins.filter(p => p.enforce === 'pre'), ...plugins.filter(p => p.enforce !== 'pre')];


const calls = [];
let physical = 10, allowConfirm = true, saveResolve, failProjection = false;
const day = new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Jakarta'}).format(new Date());
const addDay = (day, count) => { const d=new Date(day+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+count);return d.toISOString().slice(0,10); };
const target = addDay(day,2), cooking = addDay(day,1);
const snapshot = {id:50,site:'MAJA',distribution_date:target,items:[{id:1,item_name:'Jeruk Medan',planned_qty:12,unit:'kg',preferred_vendor_code:'HOLIL'},{id:2,item_name:'Kentang',planned_qty:20,unit:'kg',preferred_vendor_code:'HOLIL'}]};
global.__AUTO_API = new Proxy({}, { get: (_, name) => (arg,payload) => {
  calls.push({name,arg,payload});
  if(name==='syncCalculatorPlanning') return Promise.resolve({snapshot});
  if(name==='getInventoryBalances') {
    if(arg.site==='KOPERASI') return Promise.resolve({items:[]});
    if(failProjection) { failProjection=false;return Promise.reject(new Error('projection unavailable')); }
    return Promise.resolve({items:[{item_name:'Jeruk Medan',stock_type_code:'JERUK_MEDAN',item_aliases:['Jeruk','Jeruk Medan'],unit:'kg',actual_balance:physical,available_for_po:Math.max(0,physical-4),planned_depletion:4},{item_name:'Kentang',unit:'kg',actual_balance:2,available_for_po:2}]});
  }
  if(name==='confirmPoWarehouseStock') return new Promise(resolve=>{saveResolve=()=>{physical=arg.target_balance;resolve({committed:true,itemName:'Jeruk Medan',movementId:50});};});
  return Promise.resolve({items:[]});
} });
global.window={confirm:()=>allowConfirm,addEventListener(){},removeEventListener(){},dispatchEvent(){},setTimeout:fn=>fn()};
global.document={visibilityState:'visible',addEventListener(){},removeEventListener(){},getElementById:()=>null};
global.CustomEvent=class {};
let view;
const textOf=node=>React.Children.toArray(node.props.children).filter(x=>typeof x==='string').join('');
const button=label=>view.root.findAllByType('button').find(x=>textOf(x).trim()===label);
const math=title=>view.root.findAll(node=>node.props.title===title && typeof node.props.onChange==='function')[0];
(async()=>{
  await esbuild.build({ stdin: { contents: `export {default as Planner} from './src/operations/OperationsPoPlanner.jsx'; `, resolveDir: root }, bundle: true, platform: 'node', format: 'cjs', outfile: output, plugins: [{ name: 'production-and-fixtures', setup(build) {
    build.onResolve({ filter: /^react$/ }, () => ({ path: require.resolve(deps + '/react'), external: true }));
    build.onResolve({ filter: /^\.\/apiClient(?:\.js)?$/ }, () => ({ path: 'api', namespace: 'fixture' }));
    build.onLoad({ filter: /.*/, namespace: 'fixture' }, () => ({ contents: 'export const operationsApi=global.__AUTO_API;', loader: 'js' }));
    build.onLoad({ filter: /src\/.*\.(jsx|js)$/ }, args => {
      let code = fs.readFileSync(args.path, 'utf8');
      for (const plugin of ordered) { const result = plugin.transform?.(code, args.path); if (result) code = typeof result === 'string' ? result : result.code; }
      return { contents: code, loader: args.path.endsWith('.jsx') ? 'jsx' : 'js' };
    });
  } }] });
  const {Planner}=require(output);
  await act(async()=>{view=create(React.createElement(Planner,{fixedSite:'MAJA'}));});
  const dates=view.root.findAllByType('input').filter(x=>x.props.type==='date');
  await act(async()=>dates[0].props.onChange({target:{value:target}}));
  await act(async()=>dates[1].props.onChange({target:{value:cooking}}));
  const pull=view.root.findAllByType('button').find(x=>textOf(x).includes('Tarik Data Kalkulator'));
  assert.ok(pull,'daily pull button');
  await act(async()=>pull.props.onClick());
  assert.equal(math('Jeruk Medan').props.value,6,'12 - (10 - 4) = 6');
  await act(async()=>math('Jeruk Medan').props.onChange(99));
  await act(async()=>math('Kentang').props.onChange(77));
  await act(async()=>math('Stok gudang Jeruk Medan').props.onChange(15));
  assert.equal(calls.filter(x=>x.name==='confirmPoWarehouseStock').length,0,'typing never writes warehouse stock');
  allowConfirm=false;
  await act(async()=>button('Simpan stok & hitung PO').props.onClick());
  assert.equal(calls.filter(x=>x.name==='confirmPoWarehouseStock').length,0,'cancel leaves warehouse unchanged');
  allowConfirm=true;
  const save=button('Simpan stok & hitung PO').props.onClick;
  act(()=>{save();save();});
  assert.equal(calls.filter(x=>x.name==='confirmPoWarehouseStock').length,1,'double click sends one stock write');
  await act(async()=>saveResolve());
  assert.equal(math('Stok gudang Jeruk Medan').props.value,15,'server-confirmed physical stock shown');
  assert.equal(math('Jeruk Medan').props.value,1,'changed stock recalculates previously manually edited purchase qty');
  assert.equal(math('Kentang').props.value,77,'unrelated manual purchase edit preserved');
  const saved=calls.find(x=>x.name==='confirmPoWarehouseStock').arg;
  assert.equal(saved.expected_actual_balance,10);assert.equal(saved.target_balance,15);assert.equal(saved.site,'MAJA');assert.equal(saved.cooking_date,cooking);
  await act(async()=>math('Stok gudang Jeruk Medan').props.onChange(14));
  act(()=>{button('Simpan stok & hitung PO').props.onClick();});
  failProjection=true;
  await act(async()=>saveResolve());
  assert.ok(button('Tarik ulang stok & PO'),'successful stock write + failed projection offers read-only recovery');
  const writes=calls.filter(x=>x.name==='confirmPoWarehouseStock').length;
  await act(async()=>button('Tarik ulang stok & PO').props.onClick());
  assert.equal(calls.filter(x=>x.name==='confirmPoWarehouseStock').length,writes,'recovery reloads without a second stock write');
  assert.equal(math('Jeruk Medan').props.value,2,'12 - (14 - 4) = 2 after recovery');
  await act(async()=>view.unmount());
  console.log('PASS production PO stock: explicit save, cancel, duplicate click, physical stock persistence, cooking depletion, forced purchase recalculation, unrelated edits, projection failure and read-only recovery');
})().catch(err=>{console.error(err);process.exitCode=1});
