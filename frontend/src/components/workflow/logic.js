// The run state machine and the view derived from it. Pure, so the same code drives a live run and a Replay.
import { EDGES, edgeKey } from './layout.js';

export const initialRun = {
  eventId: null,
  phase: 'idle', // idle | running | done
  steps: [], // finished steps, in order
  active: null, // { node, station } while a node runs
  activeEdge: null, // edgeKey lit while the next station starts
  outcome: null,
  outcomeLabel: null,
  message: null,
  summary: '',
};

export const isStop = (s) => s.node !== 'close_event' && (s.stop ?? Boolean(s.data && s.data.outcome));

export function runReducer(state, action) {
  switch (action.type) {
    case 'select':
      return { ...initialRun, eventId: action.eventId };
    case 'loaded': {
      const steps = action.steps || [];
      return {
        ...initialRun,
        eventId: action.eventId,
        phase: steps.length ? 'done' : 'idle',
        steps,
        outcome: action.outcome || null,
        outcomeLabel: action.outcomeLabel || null,
        message: action.message || null,
        summary: steps.length ? steps[steps.length - 1].did : '',
      };
    }
    case 'run_start':
      return { ...initialRun, eventId: action.eventId, phase: 'running' };
    case 'step_start': {
      const stopped = state.steps.some(isStop);
      const station = action.node === 'close_event' ? (stopped ? 'stopped' : 'done') : action.station;
      const prev = state.steps.length ? state.steps[state.steps.length - 1].station : null;
      const key = prev && prev !== station ? edgeKey(prev, station) : null;
      return { ...state, active: { node: action.node, station }, activeEdge: key && EDGES.some(([a, b]) => edgeKey(a, b) === key) ? key : null };
    }
    case 'step_end':
      return { ...state, steps: [...state.steps, action.step], active: null, activeEdge: null };
    case 'run_end':
      return {
        ...state,
        phase: 'done',
        active: null,
        activeEdge: null,
        outcome: action.outcome,
        outcomeLabel: action.outcomeLabel,
        message: action.message || null,
        summary: action.summary || state.summary,
      };
    default:
      return state;
  }
}

// What each station should look like right now.
export function deriveView(run) {
  const stations = {};
  const touch = (id) => (stations[id] ||= { state: 'idle', label: '', did: '', ownerBefore: undefined, ownerAfter: undefined, steps: 0 });
  const stopStep = run.steps.find(isStop);
  for (const s of run.steps) {
    const v = touch(s.station);
    v.steps += 1;
    v.state = s.station === 'recover' ? 'recovered' : 'done';
    v.label = s.label;
    v.did = v.did ? `${v.did} ${s.did}` : s.did;
    if (v.ownerBefore === undefined) v.ownerBefore = s.owner_before ?? null;
    v.ownerAfter = s.owner_after ?? null;
  }
  if (stopStep) touch(stopStep.station).state = 'blocked';
  const last = run.steps.find((s) => s.station === 'stopped');
  if (last) touch('stopped').state = 'stopped';
  if (run.active) {
    const v = touch(run.active.station);
    v.state = run.active.station === 'recover' ? 'recovering' : 'active';
  }
  const used = new Set();
  let prev = null;
  for (const s of run.steps) {
    if (prev && prev !== s.station) used.add(edgeKey(prev, s.station));
    prev = s.station;
  }
  return { stations, usedEdges: used };
}

// Option label in the dropdown: "4 · Higher-priority agent takes over · Message sent".
export function optionLabel(item) {
  const tail = item.status === 'done' ? ` · ${item.outcome_label}` : item.available ? '' : ' · locked';
  return `${item.seq} · ${item.label}${tail}`;
}
