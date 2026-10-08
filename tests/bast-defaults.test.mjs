import assert from 'node:assert/strict';
import {defaultBastRows} from '../src/lpdh/bastDefaults.mjs';
const original=[{code:'KS-01',bastNo:'',bastLink:''},{code:'KS-02',bastNo:'BAST-ASLI-123',bastLink:'https://drive.google.com/file/d/asli/view'}];
const next=defaultBastRows(original,'2026-10-08');
assert.equal(next[0].bastNo,'DRAFT-WAJIB-DIGANTI/2026-10-08/KS-01');assert.ok(next[0].bastLink.endsWith('/2026-10-08/KS-01'));
assert.deepEqual(next[1],original[1]);assert.equal(original[0].bastNo,'');
const tomorrow=defaultBastRows(next,'2026-10-09');assert.ok(tomorrow[0].bastNo.includes('2026-10-09'));assert.deepEqual(tomorrow[1],original[1]);
assert.deepEqual(defaultBastRows(original,'2026-10-08',true),original);
assert.deepEqual(defaultBastRows(original,''),original);
const half=defaultBastRows([{code:'PS-01',bastNo:'ASLI',bastLink:' '}],'2026-10-08');assert.equal(half[0].bastNo,'ASLI');assert.ok(half[0].bastLink.includes('example.invalid'));
console.log('PASS new date defaults, next-day dummy dates, preserving real evidence and historical snapshots');

