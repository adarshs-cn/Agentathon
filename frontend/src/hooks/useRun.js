import { useCallback, useEffect, useReducer, useRef } from 'react';
import { api } from '../api/client';
import { useSim } from '../context/simState';
import { initialRun, runReducer } from '../components/workflow/logic';

// Drives the workflow graph. Live: fed by the server's stream while an event really runs.
// Replay: the same actions, scheduled from the stored steps, at the same pace.
export function useRun() {
  const { subscribeRun } = useSim();
  const [run, dispatch] = useReducer(runReducer, initialRun);
  const timers = useRef([]);
  const eventRef = useRef(null);

  const clearTimers = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };
  const later = (ms, fn) => timers.current.push(setTimeout(fn, ms));

  useEffect(
    () =>
      subscribeRun(({ type, payload }) => {
        if (type === 'run_start') {
          clearTimers();
          eventRef.current = payload.event_id;
          dispatch({ type: 'run_start', eventId: payload.event_id });
        } else if (type === 'step') {
          dispatch(payload.phase === 'start' ? { type: 'step_start', node: payload.node, station: payload.station } : { type: 'step_end', step: payload });
        } else if (type === 'run_end') {
          dispatch({ type: 'run_end', outcome: payload.outcome, outcomeLabel: payload.outcome_label, message: payload.message, summary: payload.summary });
        }
      }),
    [subscribeRun]
  );
  useEffect(() => clearTimers, []);

  const select = useCallback(async (eventId) => {
    clearTimers();
    eventRef.current = eventId;
    dispatch({ type: 'select', eventId });
    if (!eventId) return;
    const s = await api.scenarioSteps(eventId).catch(() => null);
    if (s && eventRef.current === eventId) {
      dispatch({ type: 'loaded', eventId, steps: s.steps, outcome: s.outcome, outcomeLabel: s.outcome_label, message: s.message });
    }
  }, []);

  const replay = useCallback(async (eventId, paceMs) => {
    clearTimers();
    const s = await api.scenarioSteps(eventId);
    dispatch({ type: 'run_start', eventId });
    s.steps.forEach((step, i) => {
      later(i * paceMs, () => dispatch({ type: 'step_start', node: step.node, station: step.station }));
      later((i + 1) * paceMs - 20, () => dispatch({ type: 'step_end', step }));
    });
    later(s.steps.length * paceMs, () =>
      dispatch({ type: 'run_end', outcome: s.outcome, outcomeLabel: s.outcome_label, message: s.message, summary: s.steps[s.steps.length - 1]?.did })
    );
  }, []);

  // Start a real run. If the stream never announces it, fall back to showing the stored result.
  const start = useCallback(
    async (eventId, paceMs) => {
      const r = await api.scenarioRun(eventId, paceMs);
      if (r.replay) return replay(eventId, paceMs);
      later(5000, async () => {
        if (eventRef.current === eventId) {
          const s = await api.scenarioSteps(eventId).catch(() => null);
          if (s && s.status === 'DONE') dispatch({ type: 'loaded', eventId, steps: s.steps, outcome: s.outcome, outcomeLabel: s.outcome_label, message: s.message });
        }
      });
      return r;
    },
    [replay]
  );

  return { run, select, start, replay };
}
