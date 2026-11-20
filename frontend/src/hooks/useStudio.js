import { useCallback, useEffect, useReducer, useRef } from 'react';
import { api } from '../api/client';
import { useSim } from '../context/simState';
import { initialStudio, studioReducer } from '../components/studio/studioLogic';

// Drives the Workflow Studio. Live: the server's stream (step start -> trace pieces -> step end) while an event really runs.
// Replay: the saved steps, re-typed from their saved traces (no new LLM call).
export function useStudio() {
  const { subscribeRun } = useSim();
  const [run, dispatch] = useReducer(studioReducer, initialStudio);
  const timers = useRef([]);
  const eventRef = useRef(null);
  const clearTimers = () => { timers.current.forEach(clearTimeout); timers.current = []; };
  const later = (ms, fn) => timers.current.push(setTimeout(fn, ms));

  useEffect(() => subscribeRun(({ type, payload }) => {
    if (type === 'run_start') {
      clearTimers();
      eventRef.current = payload.event_id;
      dispatch({ type: 'run_start', eventId: payload.event_id });
    } else if (type === 'step') {
      if (payload.phase === 'start') dispatch({ type: 'step_start', seq: payload.seq, node: payload.node, llm: payload.llm });
      else dispatch({ type: 'step_end', step: payload });
    } else if (type === 'trace') {
      dispatch({ type: 'trace', seq: payload.seq, kind: payload.kind, text: payload.text });
    } else if (type === 'run_end') {
      dispatch({ type: 'run_end', outcome: payload.outcome, outcomeLabel: payload.outcome_label, summary: payload.summary });
    }
  }), [subscribeRun]);
  useEffect(() => clearTimers, []);

  const load = useCallback(async (eventId) => {
    const s = await api.scenarioSteps(eventId).catch(() => null);
    if (s && eventRef.current === eventId) {
      dispatch({ type: 'loaded', eventId, steps: s.steps, status: s.status, outcome: s.outcome, outcomeLabel: s.outcome_label });
    }
  }, []);

  const select = useCallback(async (eventId) => {
    clearTimers();
    eventRef.current = eventId;
    dispatch({ type: 'select', eventId });
    if (eventId) await load(eventId);
  }, [load]);

  const replay = useCallback(async (eventId, paceMs) => {
    clearTimers();
    const s = await api.scenarioSteps(eventId);
    dispatch({ type: 'run_start', eventId });
    let t = 0;
    s.steps.forEach((step) => {
      const tr = step.trace || { source: 'rules', think: '', text: step.did || '' };
      const llm = tr.source === 'llm';
      later(t, () => dispatch({ type: 'step_start', seq: step.seq, node: step.node, llm }));
      t += paceMs;
      const pieces = (tr.text || '').match(/\S+\s*|\s+/g) || [];
      const word = paceMs * 0.08;
      if (tr.think) later(t, () => dispatch({ type: 'trace', seq: step.seq, kind: 'think', text: tr.think }));
      pieces.forEach((p) => { later(t, () => dispatch({ type: 'trace', seq: step.seq, kind: 'say', text: p })); t += word; });
      t += paceMs * 0.9;
      later(t, () => dispatch({ type: 'step_end', step }));
      t += 60;
    });
    later(t + 200, () => dispatch({ type: 'run_end', outcome: s.outcome, outcomeLabel: s.outcome_label,
      summary: s.steps[s.steps.length - 1]?.did }));
  }, []);

  const start = useCallback(async (eventId, paceMs) => {
    const r = await api.scenarioRun(eventId, paceMs);
    if (r.replay) return replay(eventId, paceMs);
    return r;
  }, [replay]);

  return { run, select, start, replay, reload: load };
}
