import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import { SimCtx } from './simState';

// One live connection for the whole app: the overview numbers, the sim clock and the decision feed.
// Pages that show other data call `useApi(..., { live: true })`, which re-fetches whenever `tick` moves.

const MAX_FEED = 60;

export function SimProvider({ children }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [connected, setConnected] = useState(false);
  const [tick, setTick] = useState(0);
  const [lastFault, setLastFault] = useState(null);
  const [notifs, setNotifs] = useState({ unseen: 0, items: [] });
  const [toast, setToast] = useState(null);
  const refreshNotifs = useCallback(() => api.notifications().then(setNotifs).catch(() => {}), []);
  const markSeen = useCallback((ids) => api.notificationsSeen(ids).then(setNotifs).catch(() => {}), []);
  const dirty = useRef(false);
  const runSubs = useRef(new Set());
  const subscribeRun = useCallback((fn) => {
    runSubs.current.add(fn);
    return () => runSubs.current.delete(fn);
  }, []);

  const load = useCallback(
    () =>
      api
        .overview()
        .then((d) => {
          setData(d);
          setError(null);
        })
        .catch((err) => setError(err.message)),
    []
  );

  useEffect(() => {
    load();
    refreshNotifs();
    const es = new EventSource(api.streamUrl());
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);

    es.addEventListener('counters', (msg) => {
      const payload = JSON.parse(msg.data);
      // Ignore live numbers until the first full overview has loaded (they carry no feed list).
      setData((prev) => (prev ? { ...prev, ...payload } : prev));
    });

    es.addEventListener('event', (msg) => {
      const evt = JSON.parse(msg.data);
      dirty.current = true;
      if (evt.type === 'FAULT_DETECTED') setLastFault(evt);
      setData((prev) => {
        if (!prev) return prev;
        return { ...prev, recent_decisions: [evt, ...(prev.recent_decisions || [])].slice(0, MAX_FEED) };
      });
    });

    // The live run of one demo event: forwarded as-is to whoever is listening (the workflow graph).
    ['run_start', 'step', 'run_end'].forEach((name) => {
      es.addEventListener(name, (msg) => {
        const payload = JSON.parse(msg.data);
        runSubs.current.forEach((fn) => fn({ type: name, payload }));
        if (name === 'run_end') {
          dirty.current = true;
          load(); // the tiles reflect the finished run straight away, not on the next 1-second tick
        }
      });
    });

    // A real run hit a fault and the supervisor recovered it: drop a notice and bump the bell.
    es.addEventListener('notify', (msg) => {
      setToast(JSON.parse(msg.data));
      refreshNotifs();
      dirty.current = true;
    });

    es.addEventListener('reset', () => {
      refreshNotifs();
      setData(null);
      setLastFault(null);
      load();
      setTick((t) => t + 1);
    });

    // Pages refresh from the API at most every 1.5 s, and only if something actually happened.
    const timer = setInterval(() => {
      if (dirty.current) {
        dirty.current = false;
        setTick((t) => t + 1);
      }
    }, 1500);

    return () => {
      clearInterval(timer);
      es.close();
    };
  }, [load, refreshNotifs]);

  const simControl = useCallback(
    async (action, body) => {
      const clock = await api.simControl(action, body);
      if (action === 'reset') {
        setData(null);
        await load();
        setTick((t) => t + 1);
      } else if (clock && clock.sim_time) {
        setData((prev) => (prev ? { ...prev, sim_clock: clock } : prev));
      }
    },
    [load]
  );

  return (
    <SimCtx.Provider value={{ data, error, connected, simControl, subscribeRun, tick, lastFault, clearFault: () => setLastFault(null), notifs, toast, clearToast: () => setToast(null), markSeen }}>
      {children}
    </SimCtx.Provider>
  );
}
