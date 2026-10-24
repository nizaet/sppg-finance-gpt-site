import {DatabaseSync} from 'node:sqlite';import test from 'node:test';import assert from 'node:assert/strict';import http from 'node:http';import {spawn} from 'node:child_process';import {mkdtempSync,rmSync} from 'node:fs';import os from 'node:os';import path from 'node:path';
test('HTTP gate: OWNER login, QR privacy, same-origin writes, no stock mutation endpoints', {timeout:20000},async()=>{
 const calls=[];const core=http.createServer(async(req,res)=>{let raw='';for await(const part of req)raw+=part;calls.push(req.url);res.setHeader('Content-Type','application/json');if(req.url==='/v1/auth/login'){if(JSON.parse(raw).password!=='correct'){res.writeHead(401);res.end('{}');return;}res.end(JSON.stringify({token:'owner-token',role:'OWNER'}));}else if(req.url==='/v1/auth/me'&&req.headers.authorization==='Bearer owner-token')res.end(JSON.stringify({role:'OWNER',expiresAt:Math.floor(Date.now()/1000)+600}));else{res.writeHead(401);res.end('{}');}});
 await new Promise(resolve=>core.listen(0,'127.0.0.1',resolve));const directory=mkdtempSync(path.join(os.tmpdir(),'sppg-wa-'));
 const child=spawn(process.execPath,['server.mjs'],{cwd:new URL('.',import.meta.url),env:{...process.env,PORT:'0',DATA_DIR:directory,SPPG_CORE_API_URL:`http://127.0.0.1:${core.address().port}`,SPPG_GPT_API_KEY:'server-only-key'},stdio:['ignore','pipe','pipe']});
 try{
 const port=await new Promise((resolve,reject)=>{let text='';child.stdout.on('data',chunk=>{text+=chunk;const m=text.match(/port=(\d+)/);if(m)resolve(m[1]);});child.on('exit',code=>reject(new Error('server exited '+code)));});
 const base='http://127.0.0.1:'+port,origin='https://127.0.0.1:'+port;
 const call=(route,body,cookie,withOrigin=true)=>fetch(base+route,{...(body===undefined?{}:{method:'POST',body:JSON.stringify(body)}),headers:{'Content-Type':'application/json',...(withOrigin?{Origin:origin}:{}),...(cookie?{Cookie:cookie}:{})}});
 assert.equal((await call('/health')).status,200);
 assert.equal((await call('/internal/reports')).status,401);
 const queue=await fetch(base+'/internal/reports',{headers:{Authorization:'Bearer server-only-key'}});assert.equal(queue.status,200);assert.equal((await queue.json()).mode,'CHATGPT_REVIEW');
 const local=new DatabaseSync(path.join(directory,'bridge.sqlite'));
 const report={id:'REPORT',site:'MAJA',reportType:'STOCK_OPNAME',text:'#SO MAJA\nGula 5 kg',contentHash:'HASH'};
 local.prepare('INSERT INTO inbox(id,content_hash,payload) VALUES(?,?,?)').run(report.id,report.contentHash,JSON.stringify(report));local.close();
 const internal=(url,body)=>fetch(base+url,{method:body?'POST':'GET',headers:{Authorization:'Bearer server-only-key','Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});
 assert.equal((await (await internal('/internal/reports')).json()).items[0].text,report.text);
 assert.equal((await internal('/internal/reports/REPORT/resolve',{contentHash:'WRONG',approvalId:'00000000-0000-0000-0000-000000000000'})).status,409);
 assert.equal((await internal('/internal/reports/REPORT/resolve',{contentHash:'HASH',approvalId:'00000000-0000-0000-0000-000000000000'})).status,200);
 assert.equal((await (await internal('/internal/reports')).json()).items.length,0);

 assert.equal((await call('/api/status')).status,401);
 assert.equal((await call('/api/connect',{},null,false)).status,403);
 assert.equal((await call('/api/login',{password:'wrong'})).status,401);
 const login=await call('/api/login',{password:'correct'});assert.equal(login.status,200);const set=login.headers.get('set-cookie');assert.match(set,/HttpOnly/);assert.match(set,/Secure/);assert.match(set,/SameSite=Strict/);const cookie=set.split(';')[0];
 const status=await (await call('/api/status',undefined,cookie)).json();assert.equal(status.connection,'DISCONNECTED');assert.equal(status.qr,null);assert.equal(status.mode,'CHATGPT_REVIEW');assert.equal(JSON.stringify(status).includes('server-only-key'),false);
 assert.equal((await call('/api/groups',{groups:[]},cookie)).status,409);
 assert.equal((await call('/api/reset',{},cookie)).status,422);
 assert.equal((await call('/api/push',{endpoint:'http://127.0.0.1/private'},cookie)).status,422);
 assert.equal((await call('/api/inbox',undefined,cookie)).status,200);
 assert.equal(calls.some(p=>p.includes('receiving')||p.includes('ingest')),false);
 }finally{child.kill('SIGTERM');await new Promise(resolve=>child.once('exit',resolve));await new Promise(resolve=>core.close(resolve));rmSync(directory,{recursive:true,force:true});}
});
