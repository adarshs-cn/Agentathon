import { Box, Paper, Stack, Typography } from '@mui/material';
import { tokens } from '../../theme/muiTheme';

const DOT = { monitoring: tokens.statusHealthy, outside_window: tokens.statusDegraded, paused: tokens.statLabelGrey };
const mins = (hhmm) => { const [h, m] = (hhmm || '0:0').split(':').map(Number); return h * 60 + m; };

// One line that says what the supervisor is doing right now, with today's contact window drawn as a bar.
export default function StatusStrip({ monitor }) {
  if (!monitor) return null;
  const [open, close] = (monitor.window || '08:00–19:00').split(/[–-]/);
  const now = new Date(monitor.now);
  const nowMin = now.getHours() * 60 + now.getMinutes();
  const pct = (m) => `${Math.max(0, Math.min(100, (m / (24 * 60)) * 100))}%`;
  const facts = [
    ['Contact window', monitor.window],
    ['Customers watched', monitor.pool_size],
    ['Handled so far', monitor.pool_handled],
    ['Waiting', monitor.waiting],
    ['Next event', monitor.state === 'monitoring' && monitor.next_event_at ? monitor.next_event_at.slice(11, 16) : '—'],
  ];
  return (
    <Paper sx={{ p: 2, borderRadius: 2.5 }} data-testid="status-strip">
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={{ xs: 1.5, md: 3 }} alignItems={{ md: 'center' }}>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 230 }}>
          <Box sx={{ width: 10, height: 10, borderRadius: '50%', backgroundColor: DOT[monitor.state] }} />
          <Box>
            <Typography sx={{ fontSize: 14, fontWeight: 600, color: tokens.statTitleGrey }}>{monitor.label}</Typography>
            <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey }}>
              {monitor.state === 'monitoring' ? 'The supervisor is handling events as they arrive.'
                : monitor.state === 'paused' ? 'Paused from the header. Nothing is processed.'
                  : 'No contact outside the window (R007). Events wait for the window to open.'}
            </Typography>
          </Box>
        </Stack>
        <Stack direction="row" spacing={3} flexWrap="wrap" useFlexGap sx={{ flex: 1 }}>
          {facts.map(([k, v]) => (
            <Box key={k}>
              <Typography sx={{ fontSize: 10.5, color: tokens.statLabelGrey }}>{k}</Typography>
              <Typography sx={{ fontSize: 15, fontWeight: 600, color: tokens.statValueGrey }} className="tabular-nums">{v}</Typography>
            </Box>
          ))}
        </Stack>
        <Box sx={{ minWidth: 240 }} aria-label={`Contact window ${monitor.window}; now ${monitor.now.slice(11, 16)}`}>
          <Box sx={{ position: 'relative', height: 8, borderRadius: 4, backgroundColor: tokens.cardGroupedBg, border: `1px solid ${tokens.dividerGrey}` }}>
            <Box sx={{ position: 'absolute', top: 0, bottom: 0, left: pct(mins(open)), width: `calc(${pct(mins(close))} - ${pct(mins(open))})`,
              backgroundColor: tokens.statusHealthy, opacity: 0.55, borderRadius: 4 }} />
            <Box sx={{ position: 'absolute', top: -4, bottom: -4, left: pct(nowMin), width: 2, backgroundColor: tokens.navbarBg }} />
          </Box>
          <Stack direction="row" justifyContent="space-between" sx={{ mt: 0.5 }}>
            <Typography sx={{ fontSize: 10, color: tokens.statLabelGrey }}>00:00</Typography>
            <Typography sx={{ fontSize: 10, color: tokens.navbarBg, fontWeight: 600 }}>now {monitor.now.slice(11, 16)}</Typography>
            <Typography sx={{ fontSize: 10, color: tokens.statLabelGrey }}>24:00</Typography>
          </Stack>
        </Box>
      </Stack>
    </Paper>
  );
}
