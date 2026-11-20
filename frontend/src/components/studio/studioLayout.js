// Where each node of the compiled LangGraph sits, and how each of its edges is drawn.
// The node and edge LIST comes from GET /api/graph (the real compiled graph); only positions are fixed here.

export const VIEW = { w: 2000, h: 1400 };
export const NODE = { w: 184, h: 86 };
export const TERMINAL_R = 34;

export const POS = {
  __start__: [80, 660],
  validate_event: [270, 660],
  load_borrower: [490, 660],
  guardrails: [710, 660],
  route: [930, 660],
  assign: [1150, 660],
  whatsapp: [1390, 400],
  email: [1390, 660],
  voice: [1390, 920],
  validate_output: [1630, 660],
  commit: [1870, 660],
  release: [1870, 380],
  close_event: [1630, 150],
  __end__: [1880, 150],
  monitor: [1630, 1060],
  recover: [1390, 1230],
};

const isTerminal = (id) => id.startsWith('__');
const hw = (id) => (isTerminal(id) ? TERMINAL_R : NODE.w / 2);
const hh = (id) => (isTerminal(id) ? TERMINAL_R : NODE.h / 2);
const CHANNELS = ['whatsapp', 'email', 'voice'];
const SPINE = ['validate_event', 'load_borrower', 'guardrails', 'route', 'assign'];

// An SVG path (cubic Bézier) for one edge, plus the point to place a moving pulse on.
export function edgePath(from, to) {
  const [x1, y1] = POS[from] || [0, 0];
  const [x2, y2] = POS[to] || [0, 0];
  const dx = x2 - x1;
  const dy = y2 - y1;

  // refusals: from the main line over the top to close_event
  if (to === 'close_event' && SPINE.includes(from)) {
    const sx = x1;
    const sy = y1 - hh(from);
    const ex = x2 - hw(to);
    const ey = y2;
    return `M ${sx} ${sy} C ${sx} ${sy - 260 - (x2 - x1) * 0.06}, ${ex - 300} ${ey}, ${ex} ${ey}`;
  }
  // recovery back into a channel (other than the one right above): swing out to the left of the channel column
  if (from === 'recover' && CHANNELS.includes(to) && to !== 'voice') {
    const sx = x1 - hw(from);
    const sy = y1;
    const ex = x2 - hw(to);
    const ey = y2 + (to === 'email' ? 14 : 10);
    const lane = x2 - hw(to) - (to === 'whatsapp' ? 46 : 26);
    return `M ${sx} ${sy} C ${lane} ${sy}, ${lane} ${ey}, ${ex} ${ey}`;
  }
  if (from === 'recover' && to === 'commit') {
    const sx = x1 + hw(from);
    const sy = y1;
    const ex = x2;
    const ey = y2 + hh(to);
    return `M ${sx} ${sy} C ${ex - 60} ${sy + 20}, ${ex} ${sy - 140}, ${ex} ${ey}`;
  }
  if (from === 'monitor' && to === 'recover') {
    const sx = x1 - hw(from);
    const sy = y1 + 10;
    const ex = x2 + hw(to) - 30;
    const ey = y2 - hh(to);
    return `M ${sx} ${sy} C ${sx - 80} ${sy}, ${ex} ${ey - 50}, ${ex} ${ey}`;
  }
  if (from === 'release' && to === 'close_event') {
    const sx = x1;
    const sy = y1 - hh(from);
    const ex = x2 + hw(to);
    const ey = y2;
    return `M ${sx} ${sy} C ${sx} ${ey}, ${ex + 60} ${ey}, ${ex} ${ey}`;
  }
  // mostly vertical
  if (Math.abs(dy) > Math.abs(dx)) {
    const sgn = dy > 0 ? 1 : -1;
    const sx = x1;
    const sy = y1 + sgn * hh(from);
    const ex = x2;
    const ey = y2 - sgn * hh(to);
    const k = Math.abs(ey - sy) * 0.5;
    return `M ${sx} ${sy} C ${sx} ${sy + sgn * k}, ${ex} ${ey - sgn * k}, ${ex} ${ey}`;
  }
  // mostly horizontal (left to right)
  const sgn = dx >= 0 ? 1 : -1;
  const sx = x1 + sgn * hw(from);
  const sy = y1;
  const ex = x2 - sgn * hw(to);
  const ey = y2;
  const k = Math.max(40, Math.abs(ex - sx) * 0.45);
  return `M ${sx} ${sy} C ${sx + sgn * k} ${sy}, ${ex - sgn * k} ${ey}, ${ex} ${ey}`;
}

// Camera: a transform that puts (x, y) at the centre of the view at `scale`.
export function cameraOn(id, scale) {
  if (!id || !POS[id]) return { x: 0, y: 0, scale: 1 };
  const [x, y] = POS[id];
  return { x: VIEW.w / 2 - x * scale, y: VIEW.h / 2 - y * scale, scale };
}
