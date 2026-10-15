import assert from 'node:assert/strict';
import {volunteerRecap} from '../src/lpdh/volunteerRecap.mjs';
const period = {start:'2026-10-05',end:'2026-10-09'};
const line = (name, amount, type='Relawan') => ({itemName:name,lineTotal:amount,metadata:{recipientType:type,role:'Masak'}});
const doc = (id, day, items, status='FINAL', type='UPAH_RELAWAN') => ({id, serviceDate:day, documentNumber:`${id}/UPAH`, status, documentType:type, items});
const a = doc(1,'2026-10-05',[line('Ani',100000),line('Guru 1',40000,'Guru'),line('Kader 1',20000,'Kader')]);
const data = [a,a,doc(2,'2026-10-06',[line('  ANI ',90000)]),doc(3,'2026-10-06',[line('Ani',10000)]),doc(4,'2026-10-07',[line('Budi',80000)]),doc(5,'2026-10-07',[line('Ani',999)],'DRAFT'),doc(6,'2026-10-07',[line('Ani',999)],'CANCELLED'),doc(7,'2026-10-10',[line('Ani',999)]),doc(8,'2026-10-07',[line('Ani',999)],'FINAL','OPERASIONAL')];
const before = JSON.stringify(data), result = volunteerRecap(data, period);
assert.equal(result.length,2);
assert.equal(result[0].name,'Ani');assert.equal(result[0].dayCount,2);assert.equal(result[0].invoiceCount,3);assert.equal(result[0].amount,200000);assert.equal(result[0].details.length,3);
assert.equal(result.reduce((s,p)=>s+p.amount,0),280000);
assert.equal(JSON.stringify(data),before);
assert.deepEqual(volunteerRecap([],period),[]);
assert.equal(volunteerRecap([doc(9,'2026-10-05',[{itemName:'Lama',lineTotal:50000}])],period)[0].amount,50000);
console.log('PASS volunteer name recap, combined package exclusions, distinct days, duplicate invoices, period and status, immutable snapshots');

