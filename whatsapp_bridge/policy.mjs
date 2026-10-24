import crypto from 'node:crypto';
export function digest(value) { return crypto.createHash('sha256').update(value).digest('hex'); }
export function normalizeIncoming(message, mappings) {
  const jid = message?.key?.remoteJid;
  const group = mappings.find(g => g.jid === jid);
  if (!group || !jid.endsWith('@g.us') || !message.key.id || message.key.fromMe) return null;
  let body = message.message;
  for (let i=0;i<5;i++) {
    const nested = body?.ephemeralMessage?.message || body?.viewOnceMessage?.message || body?.viewOnceMessageV2?.message;
    if (!nested) break; body = nested;
  }
  const text = body?.conversation || body?.extendedTextMessage?.text || body?.imageMessage?.caption || body?.documentMessage?.caption || '';
  const type = body?.imageMessage ? 'image' : body?.documentMessage ? 'document' : text ? 'text' : null;
  if (!type) return null;
  const id = digest(jid + ':' + message.key.id);
  const timestamp = Number(message.messageTimestamp);
  if (!Number.isFinite(timestamp) || timestamp <= 0) return null;
  return {id, messageId:message.key.id, jid, groupName:group.name, site:group.site,
    sender:message.key.participant || '', senderName:message.pushName || '',
    text:text.slice(0,20000), type, timestamp:new Date(timestamp*1000).toISOString(),
    contentHash:digest(jid+':'+type+':'+text), status:type==='text' || text.trim() ? 'PENDING' : 'MEDIA_REVIEW'};
}
export function coreEvidence(item) {
 return {provider:'SPPG_BAILEYS',message_id:item.id,source_key:item.site+'_RECEIVING_GROUP',
 group_name:item.groupName,sender:item.sender,sender_name:item.senderName,message_type:item.type,text:item.text,
 provider_timestamp:item.timestamp, ...(item.type==='text'?{}:{media_id:item.messageId}),
 raw_payload:{group_jid:item.jid,message_id:item.messageId,content_hash:item.contentHash,stage_only:true}};
}
export function validateMappings(rows, groups) {
 if (!Array.isArray(rows) || rows.length>2) throw new Error('Pilih maksimal satu grup per dapur.');
 const jids=new Set(), sites=new Set();
 return rows.map(row=>{
  if (!['MAJA','CEMPLANG'].includes(row.site) || jids.has(row.jid) || sites.has(row.site) || !groups[row.jid]) throw new Error('Grup atau dapur tidak valid / ganda.');
  jids.add(row.jid);sites.add(row.site);
  return {jid:row.jid,site:row.site,name:groups[row.jid].subject};
 });
}
export function safeForAutoStage(item) { return item.status==='PENDING' && !item.duplicateOf; }
