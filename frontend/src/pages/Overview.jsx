import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Box, CircularProgress, Stack, Typography } from '@mui/material';
import GavelIcon from '@mui/icons-material/Gavel';
import BugReportIcon from '@mui/icons-material/BugReport';
import SpeedIcon from '@mui/icons-material/Speed';
import GroupsIcon from '@mui/icons-material/Groups';
import CallMadeIcon from '@mui/icons-material/CallMade';
import BlockIcon from '@mui/icons-material/Block';
import StatTile from '../components/StatTile';
import Section from '../components/Section';
import OutcomeChip from '../components/OutcomeChip';
import TileDrawer from '../components/TileDrawer';
import WorkflowGraph from '../components/workflow/WorkflowGraph';
import EventPicker from '../components/workflow/EventPicker';
import RunControls from '../components/workflow/RunControls';
import PhonePreview from '../components/workflow/PhonePreview';
import EventLog from '../components/workflow/EventLog';
import { useOverview } from '../hooks/useOverview';
import { useScenario } from '../hooks/useScenario';
import { useRun } from '../hooks/useRun';
import { api } from '../api/client';
import { PACES } from '../config/labels';
import { tokens } from '../theme/muiTheme';

const TILE_GRID = { display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', md: 'repeat(3, 1fr)', lg: 'repeat(6, 1fr)' } };
const LOWER_GRID = { display: 'grid', gap: 2, alignItems: 'start', gridTemplateColumns: { xs: '1fr', md: '340px 1fr' } };

export default function Overview() {
  const { data, error } = useOverview();
  const { items, refresh, done, total } = useScenario();
  const { run, select, start, replay } = useRun();
  const [tile, setTile] = useState(null);
  const [pace, setPace] = useState('normal');
  const [formError, setFormError] = useState(null);
  const [localItems, setLocalItems] = useState(null);
  const [resetting, setResetting] = useState(false);
  const picked = useRef(false);

  const list = localItems || items;
  const item = list.find((i) => i.event_id === run.eventId);
  const running = run.phase === 'running';
  const borrower = item ? { id: item.borrower_id, masked: item.borrower_masked } : null;

  // Open on the first event not yet run (or the first one).
  useEffect(() => {
    if (!picked.current && items.length) {
      picked.current = true;
      select((items.find((i) => i.status !== 'done') || items[0]).event_id);
    }
  }, [items, select]);

  // The list refreshes when the live data moves (a run finished); keep the local copy in step.
  useEffect(() => setLocalItems(null), [items]);

  const pick = (id) => {
    setFormError(null);
    select(id);
  };
  const onRun = async () => {
    setFormError(null);
    try {
      await start(run.eventId, PACES[pace]);
    } catch (e) {
      setFormError(e.message.replace(/^.*failed: \d+ /, '').replace(/^\{"detail":"|"\}$/g, ''));
    }
  };
  const onReset = async () => {
    setFormError(null);
    setResetting(true);
    try {
      const body = await api.scenarioReset();
      setLocalItems(body.items);
      await select(body.items[0].event_id);
    } catch (e) {
      setFormError(e.message);
    } finally {
      setResetting(false);
    }
  };
  const pickFromTile = (id) => {
    setTile(null);
    pick(id);
  };

  // After a run finishes, pull the fresh list (status and outcome words for the dropdown).
  useEffect(() => {
    if (run.phase === 'done') refresh().then((b) => setLocalItems(b.items)).catch(() => {});
  }, [run.phase, refresh]);

  const counters = data?.counters;
  const latency = data?.latency_ms;
  const lines = useMemo(() => {
    if (!item) return '';
    return `${item.event_label} at ${item.time} · ${item.borrower_masked} · ${item.dpd} days past due`;
  }, [item]);

  if (error && !data) {
    return <Alert severity="error" sx={{ borderRadius: 2 }}>Could not reach the backend at the configured API URL: {error}</Alert>;
  }
  if (!data || !counters) {
    return <Box sx={{ display: 'flex', justifyContent: 'center', p: 6 }}><CircularProgress /></Box>;
  }

  const conflictOk = counters.conflicting_contacts === 0;
  const faultsOk = counters.faults_recovered >= counters.faults_injected;
  const latencyOk = latency.p95 < latency.target_ms;

  return (
    <Stack spacing={2.5}>

      <Box sx={TILE_GRID}>
        <Box>
          <StatTile icon={GavelIcon} label="Conflicting contacts" value={counters.conflicting_contacts} sub={conflictOk ? 'Target 0: met' : 'Target 0: breached'}
            accent={conflictOk ? tokens.statusHealthy : tokens.statusFault} onClick={() => setTile('conflicts')} />
        </Box>
        <Box>
          <StatTile icon={BugReportIcon} label="Faults recovered" value={`${counters.faults_recovered} / ${counters.faults_injected}`}
            sub={counters.faults_injected === 0 ? `${counters.faults_scheduled ?? 0} faults waiting to happen` : faultsOk ? 'All recovered' : 'Recovery pending'}
            accent={faultsOk ? tokens.statusHealthy : tokens.statusDegraded} onClick={() => setTile('faults')} />
        </Box>
        <Box>
          <StatTile icon={SpeedIcon} label="Decision speed" value={latency.samples ? `${latency.median.toFixed(0)} ms` : '—'}
            sub={`Target under ${latency.target_ms} ms`} accent={latency.samples && !latencyOk ? tokens.statusFault : undefined} onClick={() => setTile('latency')} />
        </Box>
        <Box>
          <StatTile icon={GroupsIcon} label="Borrowers handled" value={counters.borrowers_handled} sub={`${done} of ${total} demo events run`} onClick={() => setTile('borrowers')} />
        </Box>
        <Box>
          <StatTile icon={CallMadeIcon} label="Messages sent" value={counters.contacts_made} onClick={() => setTile('contacts')} />
        </Box>
        <Box>
          <StatTile icon={BlockIcon} label="Stopped or waiting" value={counters.blocked_or_deferred} sub="Click to see why" accent={tokens.statusDegraded} onClick={() => setTile('blocked')} />
        </Box>
      </Box>

      <Section title="Workflow" subtitle={item ? item.note : 'Loading the demo events…'}>
        <Stack spacing={2}>
          <Stack direction="row" spacing={2} alignItems="center" justifyContent="space-between" flexWrap="wrap" useFlexGap>
            <EventPicker items={list} value={run.eventId} onChange={pick} disabled={running} />
            <RunControls item={item} running={running || resetting} resetting={resetting} onRun={onRun} onReplay={() => replay(run.eventId, PACES[pace])}
              onReset={onReset} pace={pace} onPace={setPace} />
          </Stack>
          {lines && <Typography sx={{ fontSize: 12, color: tokens.statLabelGrey }} data-testid="event-line">{lines}</Typography>}
          {formError && <Alert severity="warning" sx={{ borderRadius: 2, fontSize: 12 }}>{formError}</Alert>}
          {item && !item.available && !formError && <Alert severity="info" sx={{ borderRadius: 2, fontSize: 12 }}>{item.why_unavailable}</Alert>}

          <Box sx={{ borderTop: `1px solid ${tokens.dividerGrey}`, pt: 2 }}>
            <WorkflowGraph run={run} borrower={borrower} />
          </Box>

          <Box data-testid="outcome" sx={{ minHeight: 28 }}>
            {run.phase === 'done' && run.outcome ? (
              <Stack direction="row" spacing={1.2} alignItems="center">
                <OutcomeChip outcome={run.outcome} label={run.outcomeLabel} />
                <Typography sx={{ fontSize: 12.5, color: tokens.statValueGrey }}>{run.summary}</Typography>
              </Stack>
            ) : (
              <Typography sx={{ fontSize: 12, color: tokens.statLabelGrey }}>
                {running ? 'Running… each step lights up as the supervisor works on it.' : 'Press Run to execute this event through the supervisor.'}
              </Typography>
            )}
          </Box>
        </Stack>
      </Section>

      <Box sx={LOWER_GRID}>
        <Section title="Message sent">
          <PhonePreview message={run.message} waiting={running} />
        </Section>
        <EventLog steps={run.steps} />
      </Box>

      <TileDrawer tile={tile} onClose={() => setTile(null)} onPickEvent={pickFromTile} />
    </Stack>
  );
}
