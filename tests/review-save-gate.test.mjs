import assert from 'node:assert/strict';
import {savedDailyMatches,pendingReview} from '../src/lpdh/reviewSaveGate.mjs';
const data={pm:{rows:[]}}, saved=JSON.stringify(data);
assert.equal(savedDailyMatches(data,null),false);
assert.equal(savedDailyMatches(data,saved),true);
assert.equal(savedDailyMatches({...data,lpdhNumber:'changed'},saved),false);
const preview={ready:true,incentiveCalculated:5572000,production:{incentivePm:2786},topup:{requiredRaw:100,requiredOperational:200,requiredIncentive:5572000,proposalTotal:5572300}};
const pending=pendingReview(preview);
assert.equal(pending.incentiveCalculated,0);
assert.equal(pending.production.incentivePm,0);
assert.equal(pending.topup.requiredIncentive,0);
assert.equal(pending.topup.proposalTotal,300);
assert.equal(pending.ready,false);
assert.equal(preview.incentiveCalculated,5572000);
console.log('PASS pending/saved/edited status, Review incentive zero and non-mutating preview');

