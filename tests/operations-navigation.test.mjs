import test from 'node:test';
import assert from 'node:assert/strict';
import { OPERATION_TABS, operationsUrl, readOperationsRoute, operationsRouteKey } from '../src/operations/navigation.js';
import { updateSiteState } from '../src/operations/useSiteState.js';

test('every module has a shareable URL that reopens the same module', () => {
  for (const tab of OPERATION_TABS) {
    const url = new URL(operationsUrl(tab), 'https://sppg.example');
    assert.equal(readOperationsRoute(url).tab, tab);
  }
  assert.equal(operationsUrl('accounting'), '/operations/accounting');
  assert.equal(operationsUrl('po', 'CEMPLANG'), '/operations/po?site=CEMPLANG');
});

test('warehouse deep links retain location and legacy operations URL still works', () => {
  for (const site of ['MAJA', 'CEMPLANG', 'KOPERASI']) {
    assert.deepEqual(readOperationsRoute(new URL(operationsUrl('inventory', site), 'https://sppg.example')), {tab:'inventory', site});
  }
  assert.deepEqual(readOperationsRoute({pathname:'/operations/', search:''}), {tab:'today', site:''});
  assert.deepEqual(readOperationsRoute({pathname:'/operations/vendors', search:''}), {tab:'vendors', site:'ALL'});
});

test('invalid routes and cross-module site values do not select an arbitrary warehouse', () => {
  assert.deepEqual(readOperationsRoute({pathname:'/operations/unknown', search:'?site=KOPERASI'}), {tab:'today', site:''});
  assert.deepEqual(readOperationsRoute({pathname:'/operations/po', search:'?site=KOPERASI'}), {tab:'po', site:'MAJA'});
  assert.equal(operationsUrl('https://evil.example', 'CEMPLANG'), '/operations');
});

test('scroll position keys distinguish warehouses and modules', () => {
  const keys = [
    {tab:'inventory',site:'MAJA'}, {tab:'inventory',site:'CEMPLANG'},
    {tab:'po',site:'MAJA'}, {tab:'accounting',site:''},
  ].map(operationsRouteKey);
  assert.equal(new Set(keys).size, 4);
});

test('late Maja response updates only Maja after switching to Cemplang', async () => {
  let state = new Map();
  const setFor = site => next => {state = updateSiteState(state, site, next, []);};
  const setMaja = setFor('MAJA'), setCemplang = setFor('CEMPLANG');
  let release;
  const pending = new Promise(resolve => {release=resolve;}).then(setMaja);
  setCemplang([{item:'Beras Cemplang',qty:22}]);
  release([{item:'Beras Maja',qty:11}]);
  await pending;
  assert.equal(state.get('CEMPLANG')[0].qty, 22);
  assert.equal(state.get('MAJA')[0].qty, 11);
});

test('draft updates preserve other warehouses and functional setters use the correct previous draft', () => {
  const first = updateSiteState(new Map(), 'MAJA', {text:'SO Maja'}, {});
  const second = updateSiteState(first, 'CEMPLANG', {text:'SO Cemplang'}, {});
  const third = updateSiteState(second, 'MAJA', old => ({...old, reporter:'Petugas Maja'}), {});
  assert.deepEqual(third.get('MAJA'), {text:'SO Maja',reporter:'Petugas Maja'});
  assert.deepEqual(third.get('CEMPLANG'), {text:'SO Cemplang'});
  assert.deepEqual(first.get('MAJA'), {text:'SO Maja'});
});
