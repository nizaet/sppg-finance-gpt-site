import test from 'node:test';import assert from 'node:assert/strict';
import {normalizeIncoming,coreEvidence,validateMappings,safeForAutoStage,reportType} from './policy.mjs';
const groups=[{jid:'123@g.us',name:'Penerimaan Maja',site:'MAJA',mode:'RECEIVING'}];
const msg=(text='#TERIMA MAJA\nBuncis 60 kg')=>({key:{remoteJid:'123@g.us',id:'ONE',participant:'sender@s.whatsapp.net'},message:{conversation:text},messageTimestamp:1792800000});
test('only selected group; no direct/private/outgoing or history assumptions',()=>{assert.equal(normalizeIncoming(msg(),[]),null);assert.equal(normalizeIncoming({...msg(),key:{...msg().key,fromMe:true}},groups),null);assert.equal(normalizeIncoming({...msg(),key:{...msg().key,remoteJid:'private@s.whatsapp.net'}},groups),null);});
test('actual original report and site retained; same message id stable',()=>{const a=normalizeIncoming(msg(),groups),b=normalizeIncoming(msg(),groups);assert.equal(a.id,b.id);assert.equal(a.text,'#TERIMA MAJA\nBuncis 60 kg');assert.equal(a.site,'MAJA');assert.notEqual(a.contentHash,normalizeIncoming(msg('#TERIMA MAJA\nBuncis 50 kg'),groups).contentHash);});
test('capture captions, flag captionless image for manual review',()=>{const m=msg();m.message={imageMessage:{caption:''}};assert.equal(normalizeIncoming(m,groups),null);m.message.imageMessage.caption='#TERIMA MAJA';const item=normalizeIncoming(m,groups);assert.equal(safeForAutoStage(item),true);m.message.imageMessage.caption='#TERIMA MAJA\nDatang 60 kg buncis';assert.equal(normalizeIncoming(m,groups).text,m.message.imageMessage.caption);});
test('skip unsupported protocol and invalid timestamp',()=>{assert.equal(normalizeIncoming({...msg(),message:{protocolMessage:{}}},groups),null);assert.equal(normalizeIncoming({...msg(),messageTimestamp:0},groups),null);});
test('staging payload has no commit field or auth; correct existing source key',()=>{const evidence=coreEvidence(normalizeIncoming(msg(),groups));assert.equal(evidence.source_key,'MAJA_RECEIVING_GROUP');assert.equal(evidence.provider,'SPPG_BAILEYS');assert.equal(evidence.raw_payload.stage_only,true);assert.equal('commit'in evidence,false);});
test('group mapping requires membership, distinct kitchens and group ids',()=>{const available={'123@g.us':{subject:'Maja'},'456@g.us':{subject:'Cemplang'}};assert.equal(validateMappings([{jid:'123@g.us',site:'MAJA'}],available)[0].name,'Maja');for(const rows of [[{jid:'no',site:'MAJA'}],[{jid:'123@g.us',site:'GLOBAL'}],[{jid:'123@g.us',site:'MAJA'},{jid:'123@g.us',site:'CEMPLANG'}],[{jid:'123@g.us',site:'MAJA'},{jid:'456@g.us',site:'MAJA'}]])assert.throws(()=>validateMappings(rows,available));});
test('duplicate or revision never auto-stage',()=>{for(const status of ['REVISION_REVIEW','DUPLICATE_REVIEW','MEDIA_REVIEW'])assert.equal(safeForAutoStage({status}),false);assert.equal(safeForAutoStage({status:'PENDING',duplicateOf:'other'}),false);assert.equal(safeForAutoStage({status:'PENDING',reportType:'RECEIVING'}),true);});

test('edited message preserves original ID and is held for manual review',()=>{const original=normalizeIncoming(msg(),groups);const edit=msg();edit.message={editedMessage:{message:{conversation:'#TERIMA MAJA\nBuncis 50 kg'}}};const revised=normalizeIncoming(edit,groups);assert.equal(revised.id,original.id);assert.equal(revised.text,'#TERIMA MAJA\nBuncis 50 kg');assert.equal(revised.status,'REVISION_REVIEW');assert.equal(safeForAutoStage(revised),false);});

test('only first-line explicit triggers; casual chat and quoted mentions ignored',()=>{assert.equal(reportType('#SO MAJA\nGula 5 kg'),'STOCK_OPNAME');assert.equal(reportType('#TERIMA MAJA\nBuncis 60 kg'),'RECEIVING');for(const text of ['Terima kasih','SO BARANG\nGula 5 kg','Barang datang buncis 60 kg','Gula 5 kg','Tolong cek #SO MAJA','Ini laporan\n#SO MAJA','SO sudah dicek 5 kg'])assert.equal(reportType(text),'OTHER',text);assert.equal(reportType('*#so maja*\nGula 5 kg'),'STOCK_OPNAME');assert.equal(safeForAutoStage({status:'PENDING',reportType:'STOCK_OPNAME'}),false);});
test('cross-site trigger is held, never silently assigned to the group kitchen',()=>{const item=normalizeIncoming(msg('#TERIMA CEMPLANG\nBuncis 60 kg'),groups);assert.equal(item.status,'SITE_REVIEW');assert.equal(safeForAutoStage(item),false);});

test('personal SO allowlist: only selected sender, SO keyword, inbound and correct site',()=>{
 const jid='628123456789@s.whatsapp.net',rows=[{jid,name:'Arya',site:'MAJA',mode:'STOCK_OPNAME'}];
 const make=text=>({...msg(text),key:{remoteJid:jid,id:'PERSONAL'},pushName:'Arya'});
 const item=normalizeIncoming(make('#SO MAJA\nGula 5 kg'),rows);
 assert.equal(item.reportType,'STOCK_OPNAME');assert.equal(item.sender,jid);assert.equal(item.groupName,'Arya');assert.equal(safeForAutoStage(item),false);
 for(const text of ['Halo','#TERIMA MAJA\nGula 5 kg','Ini contoh\n#SO MAJA'])assert.equal(normalizeIncoming(make(text),rows),null);
 assert.equal(normalizeIncoming(make('#SO MAJA\nGula 5 kg'),[]),null);
 assert.equal(normalizeIncoming({...make('#SO MAJA'),key:{remoteJid:jid,id:'X',fromMe:true}},rows),null);
 assert.equal(normalizeIncoming(make('#SO CEMPLANG\nGula 5 kg'),rows).status,'SITE_REVIEW');
 assert.equal(validateMappings(rows,{[jid]:{subject:'Arya'}})[0].mode,'STOCK_OPNAME');
 assert.throws(()=>validateMappings([{...rows[0],mode:'RECEIVING'}],{[jid]:{subject:'Arya'}}));
});
