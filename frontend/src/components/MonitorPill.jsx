import { Chip, IconButton, Stack, Tooltip, Typography } from '@mui/material';
import PauseIcon from '@mui/icons-material/Pause';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import { api } from '../api/client';
import { useSim } from '../context/simState';
import { tokens } from '../theme/muiTheme';

const DOT = { monitoring: tokens.statusHealthy, outside_window: tokens.statusDegraded, paused: tokens.statLabelGrey };

// The live monitor's status, in the header so it is visible from every screen.
export default function MonitorPill() {
  const { data, tick } = useSim();
  const m = data?.monitor;
  if (!m) return null;
  const paused = m.state === 'paused';
  const toggle = () => api.monitorControl(paused ? 'resume' : 'pause').catch(() => {});
  const tip = (
    <Stack spacing={0.3} sx={{ fontSize: 12 }}>
      <span>Contact window {m.window}. {m.pool_size} borrowers watched, {m.pool_handled} handled so far.</span>
      {m.waiting > 0 && <span>{m.waiting} event{m.waiting === 1 ? '' : 's'} waiting for the window to open.</span>}
      {m.next_event_at && m.state === 'monitoring' && <span>Next scheduled event {m.next_event_at.slice(11, 16)}.</span>}
      {m.error && <span>Last problem: {m.error}</span>}
    </Stack>
  );
  return (
    <Stack direction="row" alignItems="center" spacing={0.25} data-testid="monitor-pill" data-state={m.state} data-tick={tick}>
      <Tooltip title={tip}>
        <Chip
          size="small"
          variant="outlined"
          icon={<span style={{ width: 8, height: 8, borderRadius: '50%', background: DOT[m.state], marginLeft: 8 }} />}
          label={<Typography sx={{ fontSize: 11.5 }}>{m.label}</Typography>}
          sx={{ height: 26 }}
        />
      </Tooltip>
      <Tooltip title={paused ? 'Resume monitoring' : 'Pause monitoring'}>
        <IconButton size="small" onClick={toggle} aria-label={paused ? 'Resume monitoring' : 'Pause monitoring'}>
          {paused ? <PlayArrowIcon sx={{ fontSize: 18 }} /> : <PauseIcon sx={{ fontSize: 18 }} />}
        </IconButton>
      </Tooltip>
    </Stack>
  );
}
