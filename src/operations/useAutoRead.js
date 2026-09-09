import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { cachedRead, peekRead, READ_TTL_MS, subscribeReads } from './readCache.js';
export const OperationsActiveContext = createContext(true);

// Hidden retained tabs keep their state but do not poll the API.
export function useAutoRead(key, fetcher, enabled = true) {
  const active = useContext(OperationsActiveContext) && enabled;
  const latest = useRef({ key, fetcher });
  latest.current = { key, fetcher };
  const generation = useRef(0);
  const [state, setState] = useState(() => ({ key, ...peekRead(key), loading: false, error: '' }));
  const refresh = useCallback(async (force = true) => {
    const requested = latest.current;
    const ticket = ++generation.current;
    setState(old => ({ ...(old.key === requested.key ? old : { key: requested.key, ...peekRead(requested.key) }), loading: true, error: '' }));
    try {
      const result = await cachedRead(requested.key, () => requested.fetcher(force), force);
      if (ticket === generation.current && requested.key === latest.current.key) setState({ key: requested.key, ...result, loading: false, error: '' });
      return result.data;
    } catch (error) {
      if (ticket === generation.current && requested.key === latest.current.key) setState(old => ({ ...old, loading: false, error: error.message || 'Gagal memuat data' }));
      throw error;
    }
  }, []);
  useEffect(() => {
    if (!active) return;
    const load = () => { if (document.visibilityState !== 'hidden') refresh(false).catch(() => {}); };
    load();
    const interval = setInterval(load, READ_TTL_MS);
    let debounce;
    const unsubscribe = subscribeReads(() => {
      ++generation.current; // Ignore a response started before a successful mutation.
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        if (document.visibilityState !== 'hidden') refresh(true).catch(() => {});
      }, 400);
    });
    window.addEventListener('focus', load);
    document.addEventListener?.('visibilitychange', load);
    return () => {
      ++generation.current;
      clearInterval(interval); clearTimeout(debounce); unsubscribe();
      window.removeEventListener('focus', load);
      document.removeEventListener?.('visibilitychange', load);
    };
  }, [key, active, refresh]);
  const visible = state.key === key ? state : { key, ...peekRead(key), loading: active, error: '' };
  return { ...visible, refresh };
}
