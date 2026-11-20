// Pure state for the Workflow Studio: which node is working, which edges were travelled, and the trace text per visit.
// Fed by the live stream (run_start, step start/end, trace pieces, run_end) or by a replay of the saved steps.

export const initialStudio = {
  phase: 'idle', // idle | running | done
  eventId: null,
  active: null, // node id currently working
  activeSeq: null,
  visits: [], // { seq, node, status: 'active' | 'done', llm, think, text, source, label, did, stop, fault }
  edges: [], // travelled, in order: 'from>to'
  lastEdge: null,
  outcome: null,
  outcomeLabel: null,
  summary: null,
};

const lastNode = (s) => (s.visits.length ? s.visits[s.visits.length - 1].node : '__start__');

function addEdge(s, from, to) {
  const key = `${from}>${to}`;
  return { edges: s.edges.includes(key) ? s.edges : [...s.edges, key], lastEdge: key };
}

function fromStep(step) {
  const t = step.trace || {};
  return {
    seq: step.seq,
    node: step.node,
    status: 'done',
    llm: t.source === 'llm' || t.source === 'rules-fallback',
    think: t.think || '',
    text: t.text || step.did || '',
    source: t.source || 'rules',
    label: step.label,
    did: step.did,
    stop: !!step.stop,
    fault: !!(step.data && step.data.fault),
  };
}

export function studioReducer(s, a) {
  switch (a.type) {
    case 'select':
      return { ...initialStudio, eventId: a.eventId };
    case 'loaded': {
      // a finished run read back from the server: every visit with its saved trace, every edge travelled
      if (a.eventId !== s.eventId || s.phase === 'running') return s;
      const visits = (a.steps || []).map(fromStep);
      let edges = [];
      let prev = '__start__';
      visits.forEach((v) => {
        const k = `${prev}>${v.node}`;
        if (!edges.includes(k)) edges = [...edges, k];
        prev = v.node;
      });
      if (visits.length) edges = [...edges, `${prev}>__end__`];
      const done = visits.length > 0 && a.status === 'DONE';
      return { ...s, phase: done ? 'done' : 'idle', visits, edges, lastEdge: null, active: null, activeSeq: null,
        outcome: a.outcome, outcomeLabel: a.outcomeLabel, summary: visits.length ? visits[visits.length - 1].did : null };
    }
    case 'run_start':
      return { ...initialStudio, eventId: a.eventId, phase: 'running' };
    case 'step_start': {
      if (s.phase !== 'running') return s;
      const visit = { seq: a.seq, node: a.node, status: 'active', llm: !!a.llm, think: '', text: '', source: a.llm ? 'llm' : 'rules',
        label: null, did: null, stop: false, fault: false };
      return { ...s, active: a.node, activeSeq: a.seq, visits: [...s.visits, visit], ...addEdge(s, lastNode(s), a.node) };
    }
    case 'trace': {
      if (s.phase !== 'running') return s;
      const visits = s.visits.map((v) =>
        v.seq === a.seq ? (a.kind === 'think' ? { ...v, think: v.think + a.text } : { ...v, text: v.text + a.text }) : v);
      return { ...s, visits };
    }
    case 'step_end': {
      if (s.phase !== 'running') return s;
      const st = a.step;
      const visits = s.visits.map((v) => {
        if (v.seq !== st.seq) return v;
        const t = st.trace || {};
        return { ...v, status: 'done', label: st.label, did: st.did, stop: !!st.stop,
          fault: v.node === 'validate_output' ? /Problem/.test(st.label || '') : v.fault || /Problem/.test(st.label || ''),
          source: t.source || v.source, think: v.think || t.think || '', text: v.text || t.text || st.did || '' };
      });
      return { ...s, visits };
    }
    case 'run_end': {
      if (s.phase !== 'running') return s;
      return { ...s, phase: 'done', active: null, activeSeq: null, outcome: a.outcome, outcomeLabel: a.outcomeLabel,
        summary: a.summary, ...addEdge(s, lastNode(s), '__end__') };
    }
    default:
      return s;
  }
}

// What each node looks like right now: 'active' | 'done' | 'fault' | 'stop' | 'pending' (not reached yet) | 'idle'
export function nodeState(s, id) {
  if (s.active === id) return 'active';
  const vs = s.visits.filter((v) => v.node === id);
  if (id === '__start__') return s.visits.length ? 'done' : s.phase === 'idle' ? 'idle' : 'pending';
  if (id === '__end__') return s.phase === 'done' ? 'done' : s.phase === 'idle' ? 'idle' : 'pending';
  if (!vs.length) return s.phase === 'idle' ? 'idle' : 'pending';
  const last = vs[vs.length - 1];
  if (vs.some((v) => v.fault)) return 'fault';
  if (last.stop) return 'stop';
  return 'done';
}

export function edgeState(s, key) {
  if (s.phase === 'idle' && !s.edges.length) return 'idle';
  if (s.lastEdge === key && s.phase === 'running') return 'live';
  if (s.edges.includes(key)) return 'travelled';
  return 'dim';
}

export function visitsOf(s, node) {
  return s.visits.filter((v) => v.node === node);
}
