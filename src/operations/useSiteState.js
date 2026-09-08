import { useCallback, useState } from 'react';

// In-memory view state only: never reuse these snapshots for a new PO request.
// Each setter captures its site, so a late response cannot overwrite another
// warehouse's rows, draft, loading state or error after the user switches sites.
export function updateSiteState(current, site, next, initialValue) {
  const previous = current.has(site) ? current.get(site) : initialValue;
  const value = typeof next === 'function' ? next(previous) : next;
  if (current.has(site) && Object.is(value, previous)) return current;
  const result = new Map(current);
  result.set(site, value);
  return result;
}

export function useSiteState(site, initial) {
  const [initialValue] = useState(initial);
  const [values, setValues] = useState(() => new Map());
  const setValue = useCallback(next => {
    setValues(current => updateSiteState(current, site, next, initialValue));
  }, [site, initialValue]);
  return [values.has(site) ? values.get(site) : initialValue, setValue];
}
