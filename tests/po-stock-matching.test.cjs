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
vm.runInContext(source.slice(source.indexOf('function normalize('), source.indexOf('function dateRange(')), env);
const stock = (item, rows) => env.stockForItem(item, env.buildStockLookup(rows));
const row = (name, unit, amount, extra = {}) => ({ item_name: name, unit, available_for_po: amount, actual_balance: amount, projected_balance: amount, ...extra });
assert.equal(stock({item_name:'Bawang Putih Bubuk',unit:'kg'}, [row('Bawang Putih','kg',10.9)]).balance,0);
assert.equal(stock({item_name:'Ketumbar',unit:'kg'}, [row('Ketumbar','pcs',1)]).balance,0);
assert.match(stock({item_name:'Ketumbar',unit:'kg'}, [row('Ketumbar','pcs',1)]).unitWarning,/pcs/);
assert.equal(stock({item_name:'Tepung Beras',unit:'kg'}, [row('Tepung Beras','pcs',11),row('Tepung Beras','kg',4)]).balance,4);
assert.equal(stock({item_name:'Knorr Chicken Powder',unit:'kg'}, [row('Kaldu Ayam Bubuk','kg',2,{raw_item_names:['Knorr Chicken','Chicken Powder','Kaldu Ayam Bubuk']})]).balance,2);
assert.equal(stock({item_name:'Bombay',unit:'kg'}, [row('bawang bombay','kg',2,{raw_item_names:['Bombay','Bawang Bombay'],actual_balance:7,projected_balance:2,planned_depletion:5})]).balance,2);
assert.equal(stock({item_name:'Bombay',unit:'kg'}, [row('bawang bombay','kg',0,{actual_balance:7,projected_balance:0})]).balance,0,'zero remainder must not fall back to physical stock');
assert.equal(stock({item_name:'Bawang Putih',unit:'kg'}, [row('Bawang Putih','gr',500)]).balance,0.5);
assert.equal(stock({item_name:'Minyak Goreng',unit:'liter'}, [row('Minyak Goreng','dus',1)]).balance,12);
assert.equal(stock({item_name:'Daun Salam',unit:'ikat'}, [row('Daun Salam','kg',0.3),row('Daun Salam','ikat',1)]).balance,1);
assert.equal(stock({item_name:'Beras Putih',unit:'kg'}, [row('Beras','kg',7,{available_for_po:0})]).balance,0);
console.log('PASS production PO stock matching: identity, units, aliases and zero remainder');
