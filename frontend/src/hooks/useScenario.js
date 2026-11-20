import { useCallback } from 'react';
import { api } from '../api/client';
import { useApi } from './useApi';

// The 15 demo events and where each stands. Refreshes whenever a run finishes (live) or on demand.
export function useScenario() {
  const { data, error, loading } = useApi(() => api.scenario(), [], { live: true });
  const refresh = useCallback(() => api.scenario(), []);
  return { items: data?.items || [], demoContact: data?.demo_contact, done: data?.done ?? 0, total: data?.total ?? 15, error, loading, refresh };
}
