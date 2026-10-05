import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

test('LPDH navigation has its own in-flow layout without changing other modules', () => {
  const gate = readFileSync(new URL('../src/auth/AuthGate.jsx', import.meta.url), 'utf8');
  const css = readFileSync(new URL('../src/auth/auth.css', import.meta.url), 'utf8');
  assert.ok(gate.includes('" sppg-session-bar--lpdh" : ""'));
  assert.ok(gate.includes('/^\\/lpdh(?:\\/|$)/.test(window.location.pathname)'));
  const rule = css.match(/\.sppg-session-bar\.sppg-session-bar--lpdh\s*\{([^}]+)\}/)?.[1];
  assert.ok(rule);
  assert.match(rule, /position:\s*relative/);
  assert.match(rule, /inset:\s*auto/);
  assert.match(rule, /z-index:\s*auto/);
  assert.match(rule, /box-sizing:\s*border-box/);
  assert.match(css, /\.sppg-session-bar\{position:fixed/);
  assert.ok(css.indexOf('.sppg-session-bar.sppg-session-bar--lpdh') > css.indexOf('@media (max-width: 560px)'));
});
