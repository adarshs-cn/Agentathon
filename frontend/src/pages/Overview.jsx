import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Alert, Box, CircularProgress, Stack } from '@mui/material';
import GavelIcon from '@mui/icons-material/Gavel';
import BugReportIcon from '@mui/icons-material/BugReport';
import SpeedIcon from '@mui/icons-material/Speed';
import GroupsIcon from '@mui/icons-material/Groups';
import CallMadeIcon from '@mui/icons-material/CallMade';
import BlockIcon from '@mui/icons-material/Block';
import StatTile from '../components/StatTile';
import TileDrawer from '../components/TileDrawer';
import { useOverview } from '../hooks/useOverview';
import { tokens } from '../theme/muiTheme';

const TILE_GRID = { display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', md: 'repeat(3, 1fr)', lg: 'repeat(6, 1fr)' } };

// Overview: the live (real, monitored) numbers. The demo walkthrough lives in the Workflow Studio.
export default function Overview() {
  const { data, error } = useOverview();
  const navigate = useNavigate();
  const [tile, setTile] = useState(null);
  const counters = data?.counters;
  const latency = data?.latency_ms;

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
          <StatTile icon={GroupsIcon} label="Customers handled" value={counters.borrowers_handled} sub={data.monitor ? `${data.monitor.pool_handled} of ${data.monitor.pool_size} watched customers` : undefined} onClick={() => setTile('borrowers')} />
        </Box>
        <Box>
          <StatTile icon={CallMadeIcon} label="Messages sent" value={counters.contacts_made} sub={data.monitor ? 'Real customers only' : undefined} onClick={() => setTile('contacts')} />
        </Box>
        <Box>
          <StatTile icon={BlockIcon} label="Stopped or waiting" value={counters.blocked_or_deferred} sub="Click to see why" accent={tokens.statusDegraded} onClick={() => setTile('blocked')} />
        </Box>
      </Box>

      <TileDrawer tile={tile} onClose={() => setTile(null)} onPickEvent={(id) => { setTile(null); navigate(`/runs?highlight=${encodeURIComponent(id)}`); }} />
    </Stack>
  );
}
