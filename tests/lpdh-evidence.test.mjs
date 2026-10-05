import assert from 'node:assert/strict';
import {evidenceGroups, applyEvidence} from '../src/lpdh/lpdhEvidence.js';
const daily = {volunteerPayments:[
  {name:'Synthetic A',sourceDocumentId:1,aggregatePayment:true,receiptNo:'TEST/1',amount:100,evidenceLink:'',paymentReference:''},
  {name:'Synthetic B',sourceDocumentId:1,aggregatePayment:true,receiptNo:'TEST/1',amount:200,evidenceLink:'',paymentReference:''},
  {name:'Historical',receiptNo:'OLD',amount:300,evidenceLink:'old'}],
  operations:[{sourceDocumentId:2,invoiceNo:'TEST/2',evidenceLink:'a'}, {sourceDocumentId:2,invoiceNo:'TEST/2',evidenceLink:'b'},
              {sourceDocumentId:3,invoiceNo:'TEST/3',evidenceLink:'c'}]};
const groups = evidenceGroups(daily);
assert.equal(groups.length,4);
const wages = groups.find(g=>g.number==='TEST/1');
let updated = applyEvidence(daily,wages,'evidenceLink','https://example.test/signed');
updated = applyEvidence(updated,wages,'paymentReference','BANK-TEST');
assert.deepEqual(updated.volunteerPayments.slice(0,2).map(x=>[x.evidenceLink,x.paymentReference]),Array(2).fill(['https://example.test/signed','BANK-TEST']));
assert.equal(updated.volunteerPayments[2],daily.volunteerPayments[2]);
assert.equal(daily.volunteerPayments[0].evidenceLink,'');
assert.deepEqual(updated.volunteerPayments.map(x=>x.amount),[100,200,300]);
const conflicting = groups.find(g=>g.number==='TEST/2');
assert.deepEqual(conflicting.conflictingFields,['evidenceLink']);
assert.equal(conflicting.evidenceLink,'');
assert.throws(()=>applyEvidence(daily,wages,'amount',500));
assert.equal(applyEvidence(updated,wages,'paymentReference','').volunteerPayments[1].paymentReference,'');
console.log('PASS package evidence: common proof/reference, separate invoices, conflicts, explicit clearing, financial immutability');
