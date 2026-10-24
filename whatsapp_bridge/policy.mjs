import crypto from 'node:crypto';
export function digest(value) { return crypto.createHash('sha256').update(value).digest('hex'); }
export function triggerInfo(text) {
 const first=String(text||'').split(/\r?\n/).map(x=>x.trim()).find(Boolean)||'';
 const clean=first.replace(/^[* _`]+|[* _`]+$/g,'').trim();
 const match=clean.match(/^#(SO|TERIMA)\s+(MAJA|CEMPLANG)$/i);
 return match?{type:match[1].toUpperCase()==='SO'?'STOCK_OPNAME':'RECEIVING',site:match[2].toUpperCase()}:null;
}
export function reportType(text) { return triggerInfo(text)?.type || 'OTHER'; }
export function normalizeIncoming(message, mappings) {
  const jid = message?.key?.remoteJid;
  const group = mappings.find(g => g.jid === jid);
  if (!group || (!jid.endsWith('@g.us') && !(group.mode==='STOCK_OPNAME' && /@(s.whatsapp.net|lid)$/.test(jid))) || !message.key.id || message.key.fromMe) return null;
  let body = message.message;
  const isRevision = Boolean(body?.editedMessage);
  if (isRevision) body = body.editedMessage.message;
  for (let i=0;i<5;i++) {
    const nested = body?.ephemeralMessage?.message || body?.viewOnceMessage?.message || body?.viewOnceMessageV2?.message;
    if (!nested) break; body = nested;
  }
  const text = body?.conversation || body?.extendedTextMessage?.text || body?.imageMessage?.caption || body?.documentMessage?.caption || '';
  const type = body?.imageMessage ? 'image' : body?.documentMessage ? 'document' : text ? 'text' : null;
  if (!type) return null;
  const trigger=triggerInfo(text);
  const report = trigger?.type || 'OTHER';
  if(report==='OTHER' || (group.mode==='STOCK_OPNAME' && report!=='STOCK_OPNAME') || (group.mode==='RECEIVING' && report!=='RECEIVING'))return null;
  const id = digest(jid + ':' + message.key.id);
  const timestamp = Number(message.messageTimestamp);
  if (!Number.isFinite(timestamp) || timestamp <= 0) return null;
  return {id, reportType:report, messageId:message.key.id, jid, groupName:group.name, site:group.site,
    sender:message.key.participant || jid, senderName:message.pushName || '',
    text:text.slice(0,20000), type, timestamp:new Date(timestamp*1000).toISOString(),
    contentHash:digest(jid+':'+type+':'+text), status:trigger.site!==group.site ? 'SITE_REVIEW' : isRevision ? 'REVISION_REVIEW' : type==='text' || text.trim() ? 'PENDING' : 'MEDIA_REVIEW'};
}
export function coreEvidence(item) {
 return {provider:'SPPG_BAILEYS',message_id:item.id,source_key:item.site+'_RECEIVING_GROUP',
 group_name:item.groupName,sender:item.sender,sender_name:item.senderName,message_type:item.type,text:item.text,
 provider_timestamp:item.timestamp, ...(item.type==='text'?{}:{media_id:item.messageId}),
 raw_payload:{group_jid:item.jid,message_id:item.messageId,content_hash:item.contentHash,stage_only:true}};
}
export function validateMappings(rows, groups) {
 if (!Array.isArray(rows) || rows.length>4) throw new Error('Pilih maksimal empat grup laporan.');
 const jids=new Set(), roles=new Set();
 return rows.map(row=>{
  const mode=row.mode || 'MIXED';
  const role=row.site+':'+mode;
  if (!['MAJA','CEMPLANG'].includes(row.site) || !['RECEIVING','STOCK_OPNAME','MIXED'].includes(mode) || jids.has(row.jid) || roles.has(role) || !groups[row.jid] || (!row.jid.endsWith('@g.us') && !(mode==='STOCK_OPNAME' && /@(s.whatsapp.net|lid)$/.test(row.jid)))) throw new Error('Grup atau dapur tidak valid / ganda.');
  jids.add(row.jid);roles.add(role);
  return {jid:row.jid,site:row.site,mode,name:groups[row.jid].subject};
 });
}
export function safeForAutoStage(item) { return item.status==='PENDING' && item.reportType==='RECEIVING' && !item.duplicateOf; }
