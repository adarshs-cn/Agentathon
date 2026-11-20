import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Box, Stack, Typography, useMediaQuery } from '@mui/material';
import EventPicker from '../components/workflow/EventPicker';
import RunControls from '../components/workflow/RunControls';
import OutcomeChip from '../components/OutcomeChip';
import StudioGraph from '../components/studio/StudioGraph';
import TracePad from '../components/studio/TracePad';
import { C } from '../components/studio/studioTheme';
import { useScenario } from '../hooks/useScenario';
import { useStudio } from '../hooks/useStudio';
import { api } from '../api/client';
import { PACES } from '../config/labels';

// Workflow Studio: run one demo scenario through the real supervisor graph and watch it think, node by node.
// Demo only: it runs on the walkthrough's own database and never touches the live numbers.
export default function WorkflowStudio() {
  const { items, refresh } = useScenario();
  const { run, select, start, replay, reload } = useStudio();
  const [graph, setGraph] = useState(null);
  const [hover, setHover] = useState(null);
  const [pinned, setPinned] = useState(null);
  const [pace, setPace] = useState('normal');
  const [error, setError] = useState(null);
  const [localItems, setLocalItems] = useState(null);
  const [resetting, setResetting] = useState(false);
  const picked = useRef(false);
  const reduced = useMediaQuery('(prefers-reduced-motion: reduce)');

  useEffect(() => { api.graph().then(setGraph).catch((e) => setError(e.message)); }, []);
  const list = localItems || items;
  const item = list.find((i) => i.event_id === run.eventId);
  const running = run.phase === 'running';
  const metaById = useMemo(() => Object.fromEntries((graph?.nodes || []).map((n) => [n.id, n])), [graph]);

  useEffect(() => {
    if (!picked.current && items.length) {
      picked.current = true;
      select((items.find((i) => i.status !== 'done') || items[0]).event_id);
    }
  }, [items, select]);
  useEffect(() => setLocalItems(null), [items]);
  useEffect(() => {
    if (run.phase === 'done') refresh().then((b) => setLocalItems(b.items)).catch(() => {});
  }, [run.phase, refresh]);
  useEffect(() => { if (running) { setHover(null); setPinned(null); } }, [running]);

  const onRun = async () => {
    setError(null);
    try {
      await start(run.eventId, PACES[pace]);
    } catch (e) {
      setError(e.message.replace(/^.*failed: \d+ /, '').replace(/^\{"detail":"|"\}$/g, ''));
      reload(run.eventId);
    }
  };
  const onReset = async () => {
    setError(null);
    setResetting(true);
    try {
      const body = await api.scenarioReset();
      setLocalItems(body.items);
      await select(body.items[0].event_id);
    } catch (e) {
      setError(e.message);
    } finally {
      setResetting(false);
    }
  };

  const outcome = run.phase === 'done' && run.outcome ? (
    <Stack direction="row" spacing={1.2} alignItems="center" sx={{ py: 1.5, borderTop: `1px solid ${C.grid}`, mt: 1 }} data-testid="studio-outcome">
      <OutcomeChip outcome={run.outcome} label={run.outcomeLabel} />
      <Typography sx={{ fontSize: 12.5, color: C.text }}>{run.summary}</Typography>
    </Stack>
  ) : null;

  return (
    <Stack spacing={2} sx={{ height: '100%' }}>
      <Stack direction="row" spacing={2} alignItems="center" justifyContent="space-between" flexWrap="wrap" useFlexGap>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
          <EventPicker items={list} value={run.eventId} onChange={(id) => { setError(null); setHover(null); setPinned(null); select(id); }} disabled={running} />
          {item && (
            <Typography sx={{ fontSize: 12, color: 'text.secondary' }} data-testid="event-line">
              {item.event_label} at {item.time} · {item.borrower_masked} · {item.dpd} days past due
            </Typography>
          )}
        </Stack>
        <RunControls item={item} running={running || resetting} resetting={resetting} onRun={onRun}
          onReplay={() => replay(run.eventId, PACES[pace])} onReset={onReset} pace={pace} onPace={setPace} runLabel="Run demo" />
      </Stack>
      <Typography sx={{ fontSize: 11.5, color: 'text.secondary', mt: -1 }}>
        Demo only: runs here use a separate database and never change the live numbers.
        {graph && ` Graph: ${graph.nodes.length - 2} steps and ${graph.edges.length} connections, read from the compiled LangGraph.`}
        {graph && graph.narrator !== 'llm' && ' The LLM is not configured, so every step shows its rule check.'}
      </Typography>
      {error && <Alert severity="warning" sx={{ borderRadius: 2, fontSize: 12 }}>{error}</Alert>}
      {item && !item.available && !error && <Alert severity="info" sx={{ borderRadius: 2, fontSize: 12 }}>{item.why_unavailable}</Alert>}
      <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1fr) 420px' }, alignItems: 'stretch' }}>
        <Box>
          <StudioGraph graph={graph} run={run} hover={hover} pinned={pinned} onHover={setHover} onPin={setPinned} reduced={reduced} />
        </Box>
        <Box sx={{ minHeight: 360, position: 'relative' }}>
          <Box sx={{ position: { lg: 'absolute' }, inset: 0, height: { xs: 420, lg: 'auto' } }}>
          <TracePad run={run} hover={hover || pinned} pinned={!hover && !!pinned} onUnpin={() => setPinned(null)} metaById={metaById} outcome={outcome} />
          </Box>
        </Box>
      </Box>
    </Stack>
  );
}
