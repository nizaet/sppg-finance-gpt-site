import express from 'express';
import { DatabaseSync } from 'node:sqlite';
import { mkdirSync, readFileSync, rmSync } from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import pino from 'pino';
import QRCode from 'qrcode';
import webpush from 'web-push';
import makeWASocket, { useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion } from '@whiskeysockets/baileys';
import { digest, normalizeIncoming, coreEvidence, validateMappings, safeForAutoStage } from './policy.mjs';

process.umask(0o077);
const app=express(), dataDir=process.env.DATA_DIR || '/data';
const core=(process.env.SPPG_CORE_API_URL || '').replace(/\/$/,'');
if (!core || !process.env.SPPG_GPT_API_KEY) throw new Error('Core URL and server credential are required');
mkdirSync(dataDir,{recursive:true,mode:0o700});
const db=new DatabaseSync(path.join(dataDir,'bridge.sqlite'));
db.exec(`PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS inbox(id TEXT PRIMARY KEY, content_hash TEXT, payload TEXT NOT NULL, staged INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS subscriptions(id TEXT PRIMARY KEY, payload TEXT NOT NULL);`);
const setting=(key,fallback)=>{const row=db.prepare('SELECT value FROM settings WHERE key=?').get(key);return row?JSON.parse(row.value):fallback;};
const save=(key,value)=>db.prepare('INSERT OR REPLACE INTO settings VALUES(?,?)').run(key,JSON.stringify(value));
let mappings=setting('groups',[]), socket, connecting=false, qr=null, waStatus='DISCONNECTED', retry, attempt=0, stopped=false;
const contacts=new Map(setting('contacts',[]).map(c=>[c.id,c]));
let queue=Promise.resolve(), flushing=false;
const status={lastMessageAt:null,lastStageAt:null,stageError:false};
let vapid=setting('vapid',null);
if(!vapid){vapid=webpush.generateVAPIDKeys();save('vapid',vapid);}
webpush.setVapidDetails('https://sppg-finance-gpt-site-production-5b7d.up.railway.app',vapid.publicKey,vapid.privateKey);
async function coreCall(route,body,token=process.env.SPPG_GPT_API_KEY){
 const response=await fetch(core+route,{method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)}),signal:AbortSignal.timeout(30000)});
 const data=await response.json().catch(()=>({}));
 if(!response.ok) {const e=new Error('SPPG Core tidak dapat memproses permintaan ('+response.status+').');e.status=response.status;throw e;}
 return data;
}
async function notify(item){
 const text=JSON.stringify({title:(item.reportType==='STOCK_OPNAME'?'Laporan SO ':'Laporan barang datang ')+item.site,body:'Laporan baru perlu diperiksa. Stok belum berubah.',url:'/'});
 for(const row of db.prepare('SELECT * FROM subscriptions').all()){
  try{await webpush.sendNotification(JSON.parse(row.payload),text,{TTL:3600});}
  catch(e){if([404,410].includes(e.statusCode))db.prepare('DELETE FROM subscriptions WHERE id=?').run(row.id);}
 }
}
async function flush(){
 if(flushing)return;flushing=true;
 try{
 for(const row of db.prepare('SELECT * FROM inbox WHERE staged=0 LIMIT 20').all()){
  const item=JSON.parse(row.payload);if(!safeForAutoStage(item))continue;
  try{const staged=await coreCall('/v1/whatsapp/ingest-normalized',coreEvidence(item));item.core=staged;db.prepare('UPDATE inbox SET staged=1,payload=? WHERE id=?').run(JSON.stringify(item),item.id);status.lastStageAt=new Date().toISOString();status.stageError=false;}
  catch{status.stageError=true;break;}
 }
 }finally{flushing=false;}
}
function capture(message){
 const item=normalizeIncoming(message,mappings);if(!item)return;
 const old=db.prepare('SELECT payload FROM inbox WHERE id=?').get(item.id);
 if(old){
  const prior=JSON.parse(old.payload);
  if(prior.contentHash!==item.contentHash){prior.revisions=[...(prior.revisions||[]),{text:item.text,at:new Date().toISOString()}];prior.status='REVISION_REVIEW';db.prepare('UPDATE inbox SET payload=? WHERE id=?').run(JSON.stringify(prior),item.id);}
  return;
 }
 const duplicate=db.prepare('SELECT id FROM inbox WHERE content_hash=? LIMIT 1').get(item.contentHash);
 if(duplicate){item.duplicateOf=duplicate.id;item.status='DUPLICATE_REVIEW';}
 db.prepare('INSERT INTO inbox(id,content_hash,payload) VALUES(?,?,?)').run(item.id,item.contentHash,JSON.stringify(item));
 status.lastMessageAt=item.timestamp;void notify(item);void flush();
}
async function connect(){
 if(connecting || socket || stopped)return;connecting=true;waStatus='CONNECTING';qr=null;
 try{
 const {state,saveCreds}=await useMultiFileAuthState(path.join(dataDir,'auth'));
 const {version}=await fetchLatestBaileysVersion({timeout:10000});
 console.info('WhatsApp connecting',JSON.stringify({version}));
 const sock=makeWASocket({version,connectTimeoutMs:20000,auth:state,logger:pino({level:'silent'}),printQRInTerminal:false,
  markOnlineOnConnect:false,syncFullHistory:false,shouldSyncHistoryMessage:()=>false,
  getMessage:async()=>undefined,browser:['SPPG Receiving','Chrome','1.0.0']});socket=sock;
 for(const event of ['contacts.upsert','contacts.update'])sock.ev.on(event,rows=>{for(const c of rows){if(c.id && /@(s.whatsapp.net|lid)$/.test(c.id))contacts.set(c.id,{...contacts.get(c.id),...c});}save('contacts',[...contacts.values()].map(c=>({id:c.id,name:c.name,notify:c.notify,verifiedName:c.verifiedName})));});
 sock.ev.on('creds.update',()=>{if(socket!==sock)return;queue=queue.then(saveCreds).catch(()=>{waStatus='SESSION_SAVE_ERROR';});});
 sock.ev.on('connection.update',update=>{
  if(socket!==sock)return;
  if(update.qr){qr=update.qr;waStatus='SCAN_QR';console.info('WhatsApp QR ready');}
  if(update.connection==='open'){qr=null;waStatus='CONNECTED';attempt=0;}
  if(update.connection==='close'){
   socket=null;qr=null;connecting=false;
   const code=update.lastDisconnect?.error?.output?.statusCode;
   console.warn('WhatsApp connection closed',JSON.stringify({code,reason:update.lastDisconnect?.error?.message}));
   if(code===DisconnectReason.loggedOut){waStatus='LOGGED_OUT';return;}
   waStatus='RECONNECTING';if(!stopped)retry=setTimeout(()=>void connect(),Math.min(60000,2000*2**Math.min(attempt++,5)));
  }
 });
 sock.ev.on('messages.update',updates=>{for(const change of updates){if(change.update?.message?.editedMessage)capture({key:change.key,...change.update});}});
 sock.ev.on('messages.upsert',({messages,type})=>{if(type!=='notify')return;for(const message of messages)capture(message);});
 }catch(e){socket=null;waStatus='CONNECTION_ERROR';console.warn('WhatsApp connection failed',e.message);}finally{connecting=false;}
}
app.disable('x-powered-by');app.set('trust proxy',1);
app.use((req,res,next)=>{res.set({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'"});next();});
app.use(express.json({limit:'64kb'}));
const cookie=req=>{const raw=(req.headers.cookie||'').split(';').map(x=>x.trim()).find(x=>x.startsWith('bridge_session='));return raw?decodeURIComponent(raw.slice(15)):null;};
const authCache=new Map(), loginAttempts=new Map();
function sameOrigin(req,res,next){if(!['GET','HEAD','OPTIONS'].includes(req.method) && req.headers.origin!==`https://${req.get('host')}`){return res.status(403).json({error:'Origin tidak valid'});}next();}
app.use('/api',sameOrigin);
app.get('/health',(_req,res)=>res.json({status:'ok',service:'sppg-whatsapp-bridge',mode:'stage-only'}));
app.post('/api/login',async(req,res)=>{
 const ip=req.ip,now=Date.now(),entry=loginAttempts.get(ip)||{n:0,since:now};if(now-entry.since>600000){entry.n=0;entry.since=now;}entry.n++;loginAttempts.set(ip,entry);
 if(entry.n>10)return res.status(429).json({error:'Terlalu banyak percobaan login. Tunggu 10 menit.'});
 try{const result=await coreCall('/v1/auth/login',{username:'OWNER',password:String(req.body.password||''),remember:true},'');
 if(result.role!=='OWNER')throw new Error();res.cookie('bridge_session',result.token,{httpOnly:true,secure:true,sameSite:'strict',path:'/',maxAge:30*86400000});loginAttempts.delete(ip);res.json({ok:true});}
 catch{res.status(401).json({error:'Login OWNER gagal.'});}
});
app.use('/api',async(req,res,next)=>{
 const token=cookie(req);if(!token)return res.status(401).json({error:'Login OWNER diperlukan.'});
 try{const key=digest(token),cached=authCache.get(key);let identity;
 if(cached && cached.until>Date.now())identity=cached.identity;else{identity=await coreCall('/v1/auth/me',undefined,token);authCache.set(key,{until:Date.now()+30000,identity});}
 if(identity.role!=='OWNER'||identity.expiresAt*1000<Date.now())throw new Error();next();}
 catch{res.status(401).json({error:'Sesi OWNER berakhir. Silakan login kembali.'});}
});
app.post('/api/logout',(req,res)=>{authCache.delete(digest(cookie(req)||''));res.clearCookie('bridge_session',{path:'/',secure:true,sameSite:'strict'});res.json({ok:true});});
app.get('/api/status',async(_req,res)=>res.json({connection:waStatus,qr:qr?await QRCode.toDataURL(qr):null,groups:mappings,...status,coreUrl:core,mode:'STAGE_ONLY',vapidPublicKey:vapid.publicKey}));
app.post('/api/reset',async(req,res)=>{if(req.body.confirmation!=='RESET_LINK')return res.status(422).json({error:'Konfirmasi putuskan perangkat diperlukan.'});stopped=true;clearTimeout(retry);const previous=socket;socket=null;try{await previous?.logout();}catch{}await queue;rmSync(path.join(dataDir,'auth'),{recursive:true,force:true});qr=null;waStatus='DISCONNECTED';res.json({ok:true});});
app.post('/api/connect',async(_req,res)=>{stopped=false;clearTimeout(retry);await connect();res.json({ok:true,connection:waStatus});});
app.get('/api/groups',async(_req,res)=>{if(waStatus!=='CONNECTED'||!socket)return res.status(409).json({error:'Hubungkan WhatsApp terlebih dahulu.'});try{const groups=await socket.groupFetchAllParticipating();res.json({items:Object.values(groups).map(g=>({jid:g.id,name:g.subject}))});}catch{res.status(502).json({error:'Daftar grup belum dapat dibaca.'});}});
app.get('/api/contacts',(_req,res)=>res.json({items:[...contacts.values()].map(c=>({jid:c.id,name:c.name||c.notify||c.verifiedName||c.id.split('@')[0]}))}));
app.post('/api/contact',async(req,res)=>{if(!socket||waStatus!=='CONNECTED')return res.status(409).json({error:'WhatsApp belum tersambung.'});try{let number=String(req.body.number||'').replace(/[^0-9]/g,'');if(number.startsWith('0'))number='62'+number.slice(1);if(!/^[1-9][0-9]{7,14}$/.test(number))throw new Error();const [found]=await socket.onWhatsApp(number);if(!found?.exists)throw new Error();const contact={id:found.jid,name:number};contacts.set(contact.id,contact);save('contacts',[...contacts.values()]);res.json({jid:contact.id,name:contact.name});}catch{res.status(422).json({error:'Nomor WhatsApp tidak ditemukan. Gunakan nomor dengan kode negara, misalnya 62812…'});}});
app.post('/api/groups',async(req,res)=>{if(!socket||waStatus!=='CONNECTED')return res.status(409).json({error:'WhatsApp belum tersambung.'});try{const groups=await socket.groupFetchAllParticipating();const available={...groups};for(const c of contacts.values())available[c.id]={subject:c.name||c.notify||c.verifiedName||c.id.split('@')[0]};mappings=validateMappings(req.body.groups,available);save('groups',mappings);res.json({groups:mappings});}catch{res.status(422).json({error:'Pilih grup atau chat personal SO yang valid, maksimal empat sumber laporan.'});}});
app.get('/api/inbox',(_req,res)=>res.json({items:db.prepare('SELECT payload,staged FROM inbox ORDER BY rowid DESC LIMIT 100').all().map(row=>({...JSON.parse(row.payload),staged:!!row.staged}))}));
app.post('/api/push', (req,res)=>{const sub=req.body;try{const url=new URL(sub.endpoint);const hosts=['fcm.googleapis.com','updates.push.services.mozilla.com','web.push.apple.com'];if(url.protocol!=='https:'||!hosts.includes(url.hostname)||!sub.keys?.p256dh||!sub.keys?.auth)throw new Error();db.prepare('INSERT OR REPLACE INTO subscriptions VALUES(?,?)').run(digest(sub.endpoint),JSON.stringify(sub));res.json({ok:true});}catch{res.status(422).json({error:'Langganan notifikasi tidak valid.'});}});
app.use(express.static(new URL('./public/',import.meta.url).pathname,{etag:false}));
app.use((error,_req,res,_next)=>res.status(500).json({error:'Permintaan gagal. Data belum dikonfirmasi.'}));
const server=app.listen(Number(process.env.PORT||8080),'0.0.0.0',()=>console.log('SPPG WhatsApp bridge ready (stage-only) port='+server.address().port));
setInterval(()=>void flush(),30000);
try{const creds=JSON.parse(readFileSync(path.join(dataDir,'auth/creds.json'),'utf8'));if(creds.registered)void connect();}catch{}
for(const signal of ['SIGTERM','SIGINT'])process.on(signal,()=>{stopped=true;clearTimeout(retry);socket?.end(undefined);queue.finally(()=>{db.close();process.exit(0);});});
