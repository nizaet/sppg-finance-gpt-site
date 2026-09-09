// Session-memory cache only: never persist financial data in browser storage.
const entries = new Map();
const listeners = new Set();
export const READ_TTL_MS = 60_000;
export function peekRead(key) { return entries.get(key)?.value; }
export function cachedRead(key, fetcher, force = false) {
  const previous = entries.get(key);
  if (previous?.pending) return previous.pending;
  if (!force && previous?.value && Date.now() - previous.value.updatedAt < READ_TTL_MS) return Promise.resolve(previous.value);
  const entry = { value: previous?.value };
  entries.set(key, entry);
  entry.pending = Promise.resolve().then(fetcher).then(data => {
    const value = { data, updatedAt: Date.now() };
    if (entries.get(key) === entry) entry.value = value;
    return value;
  }).finally(() => { delete entry.pending; });
  // Bound memory even when an operator browses many calendar months.
  if (entries.size > 32) entries.delete(entries.keys().next().value);
  return entry.pending;
}
export function invalidateReads() {
  entries.clear();
  listeners.forEach(listener => listener());
}
export function subscribeReads(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
