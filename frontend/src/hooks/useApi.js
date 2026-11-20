import { useEffect, useRef, useState } from 'react';
import { useSim } from '../context/simState';

// useApi(() => api.faults(), [deps], { live: true })
//  - keeps the previous data on screen while it reloads (no flicker)
//  - live: true  re-fetches whenever the simulation produced new decisions
export function useApi(fn, deps = [], { live = false } = {}) {
  const { tick } = useSim();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let cancelled = false;
    fnRef
      .current()
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setError(null);
        }
      })
      .catch((err) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, live ? tick : 0]);

  return { data, error, loading };
}
