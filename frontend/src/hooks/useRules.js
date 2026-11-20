import { useEffect, useState } from 'react';
import { api } from '../api/client';

// The D12 rule book, fetched once and shared: every rule id on screen can explain itself.
let cache = null;
let inflight = null;

export function loadRules() {
  if (cache) return Promise.resolve(cache);
  if (!inflight) {
    inflight = api
      .rules()
      .then((r) => {
        cache = Object.fromEntries(r.items.map((x) => [x.rule_id, x]));
        return cache;
      })
      .catch(() => {
        inflight = null;
        return {};
      });
  }
  return inflight;
}

export function useRules() {
  const [rules, setRules] = useState(cache || {});
  useEffect(() => {
    let live = true;
    loadRules().then((r) => live && setRules(r));
    return () => {
      live = false;
    };
  }, []);
  return rules;
}
