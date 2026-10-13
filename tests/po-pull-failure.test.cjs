const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'..'),configs=new Map();
function config(file){if(configs.has(file))return configs.get(file);let code=fs.readFileSync(path.join(root,file),'utf8');const env={console,process,defineConfig:x=>x,react:()=>({name:'react'})};code=code.replace(/^import\s+(\w+)\s+from\s+["'](\.\/[^"']+)["'];?\s*$/gm,(_,name,dep)=>{env[name]=config(dep.slice(2));return'';}).replace(/^import .*;\s*$/gm,'').replace(/export default /g,'result = ');vm.createContext(env);vm.runInContext(code,env);configs.set(file,env.result);return env.result;}
const plugins=config('vite.po-list-independent.config.js').plugins.flat().filter(Boolean),ordered=[...plugins.filter(p=>p.enforce==='pre'),...plugins.filter(p=>p.enforce!=='pre')];
function transformed(relative){let code=fs.readFileSync(path.join(root,relative),'utf8');for(const plugin of ordered){const result=plugin.transform?.(code,path.join(root,relative));if(result)code=typeof result==='string'?result:result.code;}return code;}
(async()=>{
 const source=transformed('src/operations/OperationsPoPlanner.jsx'),fn=source.match(/  const pullDailyData = async \(\) => \{[\s\S]*?\n  \};(?=\n\n  const clearDailyPulledData)/)?.[0];assert.ok(fn);
 for(const site of ['MAJA','CEMPLANG']){
  let applied=0,scheduleWrites=0,error='';const original={id:1,po_qty:17};
  const env={activeSite:site,distributionDate:'2026-10-16',cookingDate:'2026-10-15',setLoading(){},setDailyPulled(){},setError:value=>error=value,setMessage(){},setSchedule:()=>scheduleWrites++,setPurchaseOrders(){},setPoListLoaded(){},applyPlanningSnapshot:()=>applied++,operationsApi:{syncCalculatorPlanning:async()=>({snapshot:{id:2}}),previewPoSchedule:async()=>({items:[]}),getInventoryBalances:async()=>{throw Error('Stock timeout');},getPurchaseOrders:async()=>({items:[original]})}};
  vm.createContext(env);vm.runInContext(fn+';globalThis.pull=pullDailyData;',env);await env.pull();assert.match(error,/Planning ditemukan/);assert.equal(applied,0);assert.equal(scheduleWrites,0);assert.equal(original.po_qty,17);
  env.operationsApi.syncCalculatorPlanning=async()=>({snapshot:null});await env.pull();assert.equal(applied,1,'genuinely missing plan may clear working set');
 }
 assert.ok(source.includes('dailyPulled && !planningSnapshot && !error'));
 let timers=[],requests=[];const env={URLSearchParams,AbortController,readSessionToken:()=>null,invalidateReads(){},setTimeout:(_fn,ms)=>{timers.push(ms);return timers.length;},clearTimeout(){},fetch:async(url,options)=>{requests.push({url,options});return{ok:true,status:200,json:async()=>({items:[]})};}};
 let code=transformed('src/operations/apiClient.js').replace(/^import .*;\s*$/gm,'').replace(/import\.meta\.env/g,'({})').replace(/export const /g,'const ');
 vm.createContext(env);vm.runInContext(code+';globalThis.api=operationsApi;',env);await env.api.getInventoryBalances({site:'CEMPLANG',forDate:'2026-10-16'});
 assert.equal(timers.at(-1),90000);assert.equal(requests.at(-1).options.timeoutMs,undefined);assert.match(requests.at(-1).url,/site=CEMPLANG/);
 console.log('PASS production-transformed PO failure: MAJA/CEMPLANG working sets preserved, missing notice suppressed, stock-only timeout applied');
})().catch(error=>{console.error(error);process.exitCode=1;});
