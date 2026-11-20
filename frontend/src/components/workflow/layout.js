// Geometry of the workflow drawing. Pure functions, no React, so they can be checked from Node.
// Everything is in SVG user units; the SVG scales to its card with a fixed viewBox.

export const W = 108; // station width
export const H = 64; // station height
export const GAP = 24;
export const X0 = 20;
export const MAIN_Y = 28;
export const LOW_Y = 160;
export const VIEW_W = X0 * 2 + 9 * W + 8 * GAP; // 1204
export const VIEW_H = 244;

export const STATIONS = [
  { id: 'event', name: 'Event received', icon: 'event', lane: 0 },
  { id: 'borrower', name: 'Borrower loaded', icon: 'borrower', lane: 1 },
  { id: 'safety', name: 'Safety checks', icon: 'safety', lane: 2 },
  { id: 'agent_chosen', name: 'Agent chosen', icon: 'route', lane: 3 },
  { id: 'ownership', name: 'Ownership taken', icon: 'lock', lane: 4 },
  { id: 'agent_acts', name: 'Agent acts', icon: 'send', lane: 5 },
  { id: 'result', name: 'Result checked', icon: 'check', lane: 6 },
  { id: 'saved', name: 'State saved', icon: 'save', lane: 7 },
  { id: 'done', name: 'Done', icon: 'done', lane: 8 },
  { id: 'recover', name: 'Recover', icon: 'recover', lane: 5.5, low: true },
  { id: 'stopped', name: 'Stopped', icon: 'stop', lane: 2.5, low: true },
];

export const EDGES = [
  ['event', 'borrower'], ['borrower', 'safety'], ['safety', 'agent_chosen'], ['agent_chosen', 'ownership'],
  ['ownership', 'agent_acts'], ['agent_acts', 'result'], ['result', 'saved'], ['saved', 'done'],
  ['result', 'recover'], ['recover', 'agent_acts'], ['recover', 'saved'],
  ['event', 'stopped'], ['safety', 'stopped'], ['agent_chosen', 'stopped'], ['ownership', 'stopped'],
];

const BOX = {};
for (const s of STATIONS) {
  BOX[s.id] = { ...s, x: X0 + s.lane * (W + GAP), y: s.low ? LOW_Y : MAIN_Y };
}
export const boxes = BOX;

export const cx = (id) => BOX[id].x + W / 2;
export const cy = (id) => BOX[id].y + H / 2;

// Where each incoming edge lands along Stopped's top edge, so the arrowheads do not pile up.
const STOP_SPREAD = { event: -40, safety: -14, agent_chosen: 14, ownership: 40 };

// Path of an edge between two stations. Straight along the main lane, a soft curve for everything else.
export function edgePath(from, to) {
  const a = BOX[from];
  const b = BOX[to];
  if (!a.low && !b.low) {
    return `M ${a.x + W} ${cy(from)} L ${b.x - 4} ${cy(to)}`;
  }
  if (to === 'stopped') {
    const sx = cx(from);
    const sy = a.y + H;
    const tx = cx('stopped') + (STOP_SPREAD[from] ?? 0);
    const ty = b.y - 4;
    return `M ${sx} ${sy} C ${sx} ${sy + 70}, ${tx} ${ty - 70}, ${tx} ${ty}`;
  }
  if (to === 'recover') {
    // Result checked (above, to the right) down into Recover's top-right.
    const sx = cx(from);
    const sy = a.y + H;
    const tx = cx('recover') + 26;
    const ty = b.y - 4;
    return `M ${sx} ${sy} C ${sx} ${sy + 60}, ${tx} ${ty - 60}, ${tx} ${ty}`;
  }
  if (from === 'recover' && to === 'agent_acts') {
    // The retry loop: up and to the left, back into Agent acts.
    const sx = cx('recover') - 26;
    const sy = a.y;
    const tx = cx('agent_acts') - 10;
    const ty = b.y + H + 4;
    return `M ${sx} ${sy} C ${sx} ${sy - 60}, ${tx} ${ty + 60}, ${tx} ${ty}`;
  }
  // recover -> saved: out of Recover's right side, up into State saved's bottom.
  const sx = a.x + W;
  const sy = cy(from);
  const tx = cx(to);
  const ty = b.y + H + 4;
  return `M ${sx} ${sy} C ${sx + 70} ${sy}, ${tx} ${ty + 70}, ${tx} ${ty}`;
}

export const edgeKey = (a, b) => `${a}>${b}`;
