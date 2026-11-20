const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001';

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`${options.method || 'GET'} ${path} failed: ${res.status} ${body}`);
  }
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) return res.json();
  return res.text();
}

export const api = {
  overview: () => request('/api/overview'),
  borrowerState: (accountId) => request(`/api/borrowers/${accountId}/state`),
  borrowerTrace: (accountId, params = {}) =>
    request(`/api/borrowers/${accountId}/trace?${new URLSearchParams(params)}`),
  agents: () => request('/api/agents'),
  faults: () => request('/api/faults'),
  ownership: () => request('/api/ownership'),
  budgets: () => request('/api/budgets'),
  decisions: (params = {}) => request(`/api/decisions?${new URLSearchParams(params)}`),
  accountsSearch: (q) => request(`/api/accounts/search?q=${encodeURIComponent(q)}`),
  accountsList: (params = {}) => request(`/api/accounts?${new URLSearchParams(params)}`),
  accountsFilterOptions: () => request('/api/accounts/filter-options'),
  simControl: (action, body) =>
    request(`/api/simulation/${action}`, { method: 'POST', body: JSON.stringify(body || {}) }),
  rules: () => request('/api/rules'),
  simulation: () => request('/api/simulation'),
  scenario: () => request('/api/scenario'),
  scenarioRun: (id, paceMs) => request(`/api/scenario/${id}/run?pace_ms=${paceMs}`, { method: 'POST' }),
  scenarioSteps: (id) => request(`/api/scenario/${id}/steps`),
  scenarioReset: () => request('/api/scenario/reset', { method: 'POST' }),
  drilldown: (tile) => request(`/api/overview/drilldown/${tile}`),
  streamUrl: () => `${BASE_URL}/api/stream`,
};

export { BASE_URL };
