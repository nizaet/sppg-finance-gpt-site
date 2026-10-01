const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
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
const file = path.join(root, 'src/operations/OperationsPoPlanner.jsx');
let source = fs.readFileSync(file, 'utf8');
for (const plugin of ordered) { const result = plugin.transform?.(source, file); if (result) source = typeof result === 'string' ? result : result.code; }
const env = {}; vm.createContext(env);
vm.runInContext(source.slice(source.indexOf('function normalize('), source.indexOf('export default function OperationsPoPlanner')), env);
const stock = (item, rows) => env.stockForItem(item, env.buildStockLookup(rows));
const row = (name, unit, amount, extra = {}) => ({ item_name: name, unit, available_for_po: amount, actual_balance: amount, projected_balance: amount, ...extra });
assert.equal(env.operationalPlanningUnit({item_name:'Lada Putih Ladaku',unit:'pcs'}),'kg');
assert.equal(env.operationalPlanningUnit({item_name:'Saus tiram Saori',unit:'liter'}),'kg');
assert.equal(env.safeVendorForPlanningItem({item_name:'Tempe',category_code:'TEMPE_TAHU'},'MAJA').vendor,'KOPERASI');
assert.equal(env.safeVendorForPlanningItem({item_name:'Tempe',category_code:'TEMPE_TAHU'},'CEMPLANG').vendor,'KOPERASI');
assert.equal(env.poCoversItem({status:'SENT',coverage_dates:['2026-09-15'],item_refs:[{item_name:'tempe',unit:'papan'}]},{item_name:'Tempe',unit:'papan'},'2026-09-15'),true);
assert.equal(env.poCoversItem({status:'SENT',coverage_dates:['2026-09-14'],item_refs:[{item_name:'tempe',unit:'papan'}]},{item_name:'Tempe',unit:'papan'},'2026-09-15'),false);
assert.equal(stock({item_name:'Bawang Putih Bubuk',unit:'kg'}, [row('Bawang Putih','kg',10.9)]).balance,0);
assert.equal(stock({item_name:'Ketumbar',unit:'kg'}, [row('Ketumbar','pcs',1)]).balance,0);
assert.match(stock({item_name:'Ketumbar',unit:'kg'}, [row('Ketumbar','pcs',1)]).unitWarning,/pcs/);
assert.equal(stock({item_name:'Garam',unit:'kg'}, [row('Garam','pcs',3)]).balance,1.5);
assert.equal(stock({item_name:'Kaldu Jamur Totole',unit:'pack'}, [row('Kaldu Jamur','pouch',0.6)]).balance,0.6);
const cemplangSalt = env.draftItemsForSnapshot({items:[{id:1,item_name:'Garam',planned_qty:5,unit:'kg',preferred_vendor_code:'KOPERASI'}]},[row('Garam','pcs',3)],[],'CEMPLANG')[0];
assert.equal(cemplangSalt.stock_qty,1.5,'3 confirmed 500 g salt packets must display as 1.5 kg');
assert.equal(cemplangSalt.recommended_po_qty,3.5,'salt PO subtracts converted physical stock');
assert.equal(cemplangSalt.stock_requires_review,false);
const cemplangMushroom = env.draftItemsForSnapshot({items:[{id:2,item_name:'Kaldu Jamur Totole',planned_qty:5,unit:'pack',preferred_vendor_code:'KOPERASI'}]},[row('Kaldu Jamur','pouch',0.6)],[],'CEMPLANG')[0];
assert.equal(cemplangMushroom.stock_qty,0.6,'confirmed pouch stock must be visible in packs');
assert.equal(cemplangMushroom.recommended_po_qty,4.4,'mushroom seasoning PO subtracts pouch stock one-for-one');
assert.equal(env.draftItemsForSnapshot({items:[{id:2,item_name:'Minyak Goreng',planned_qty:44,unit:'liter'}]},[row('Minyak Goreng','liter',10,{available_for_po:6,planned_depletion:4})],[],'CEMPLANG')[0].recommended_po_qty,38,'N+1 uses stock after N0');
assert.equal(env.draftItemsForSnapshot({items:[{id:3,item_name:'Minyak Goreng',planned_qty:44,unit:'liter'}]},[row('Minyak Goreng','liter',10)],[],'CEMPLANG')[0].recommended_po_qty,34,'N0 uses physical stock');
const sharedStock = env.draftItemsForSnapshot({items:[
  {id:4,item_name:'Beras',planned_qty:5,unit:'kg'},
  {id:5,item_name:'Beras Putih Lokal',planned_qty:5,unit:'kg'},
]},[row('Beras','kg',6)],[],'CEMPLANG');
assert.deepEqual(sharedStock.map(x=>x.recommended_po_qty),[0,4],'a shared warehouse balance is allocated once across duplicate planning lines');
assert.equal(stock({item_name:'Tepung Beras',unit:'kg'}, [row('Tepung Beras','pcs',11),row('Tepung Beras','kg',4)]).balance,4);
assert.equal(stock({item_name:'Knorr Chicken Powder',unit:'kg'}, [row('Kaldu Ayam Bubuk','kg',2,{raw_item_names:['Knorr Chicken','Chicken Powder','Kaldu Ayam Bubuk']})]).balance,2);
assert.equal(stock({item_name:'Bombay',unit:'kg'}, [row('bawang bombay','kg',2,{raw_item_names:['Bombay','Bawang Bombay'],actual_balance:7,projected_balance:2,planned_depletion:5})]).balance,2);
assert.equal(stock({item_name:'Bombay',unit:'kg'}, [row('bawang bombay','kg',0,{actual_balance:7,projected_balance:0})]).balance,0,'zero remainder must not fall back to physical stock');
assert.equal(stock({item_name:'Bawang Putih',unit:'kg'}, [row('Bawang Putih','gr',500)]).balance,0.5);
assert.equal(stock({item_name:'Minyak Goreng',unit:'liter'}, [row('Minyak Goreng','dus',1)]).balance,12);
assert.equal(stock({item_name:'Saus tiram Saori',unit:'liter'}, [row('Saus Tiram','liter',2)]).balance,2);
assert.equal(stock({item_name:'Saus tiram Saori',unit:'kg'}, [row('Saus Tiram','botol',2)]).balance,2);
assert.equal(stock({item_name:'Lada Putih Ladaku',unit:'kg'}, [row('Lada Putih','pcs',1)]).balance,1);
assert.equal(stock({item_name:'Daun Salam',unit:'ikat'}, [row('Daun Salam','kg',0.3),row('Daun Salam','ikat',1)]).balance,1);
assert.equal(stock({item_name:'Beras Putih',unit:'kg'}, [row('Beras','kg',7,{available_for_po:0})]).balance,0);
console.log('PASS production PO stock matching: identity, units, aliases and zero remainder');
