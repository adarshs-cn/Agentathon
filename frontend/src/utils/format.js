// Small formatters shared by every page. Times are simulated wall-clock times sent as ISO strings ending in Z,
// so toISOString() shows exactly the time the supervisor saw (no timezone shift).

export function fmtTime(ts) {
  try {
    return new Date(ts).toISOString().slice(11, 19);
  } catch {
    return ts || '—';
  }
}

export function fmtDateTime(ts) {
  try {
    return new Date(ts).toISOString().slice(0, 16).replace('T', ' ');
  } catch {
    return ts || '—';
  }
}

export const inr = (v) =>
  v == null ? '—' : `₹${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;

export const inr2 = (v) =>
  v == null ? '—' : `₹${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;

export const pct = (v, digits = 0) => (v == null ? '—' : `${(100 * v).toFixed(digits)}%`);

export const num = (v) => (v == null ? '—' : Number(v).toLocaleString('en-IN'));

export function titleCase(s) {
  return (s || '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
