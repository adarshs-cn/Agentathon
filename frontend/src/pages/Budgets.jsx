import { Alert, Box, Chip, Grid, LinearProgress, Stack, Typography } from '@mui/material';
import PaidIcon from '@mui/icons-material/PaidOutlined';
import CallMadeIcon from '@mui/icons-material/CallMade';
import SmartToyIcon from '@mui/icons-material/SmartToyOutlined';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import Section from '../components/Section';
import StatTile from '../components/StatTile';
import UsageBar from '../components/UsageBar';
import SimpleTable from '../components/SimpleTable';
import { inr2, num, titleCase } from '../utils/format';
import { tokens } from '../theme/muiTheme';

const CH = { sms: 'SMS', whatsapp: 'WhatsApp', email: 'Email', call: 'Voice call', field_visit: 'Field visit' };

export default function Budgets() {
  const { data, error } = useApi(() => api.budgets(), [], { live: true });
  if (error && !data) return <Alert severity="error" sx={{ borderRadius: 2 }}>Could not load budgets: {error}</Alert>;
  if (!data) return null;
  const dist = data.per_borrower_today;
  const distTotal = Math.max(1, dist['1'] + dist['2'] + dist['3+']);
  const groups = data.resources.reduce((acc, r) => ({ ...acc, [r.agent]: [...(acc[r.agent] || []), r] }), {});
  const order = ['reminder_agent', 'negotiation_agent', 'servicing_agent', 'legal_agent', 'AGY001', 'AGY002', 'AGY003'];

  return (
    <Stack spacing={2}>
      <Grid container spacing={2}>
        <Grid item xs={12} sm={4}><StatTile icon={CallMadeIcon} label="Attempts today (all agents)" value={num(data.totals.attempts_today)} sub={`as of ${data.as_of}, history plus supervisor`} /></Grid>
        <Grid item xs={12} sm={4}><StatTile icon={SmartToyIcon} label="Sent by the supervisor" value={num(data.totals.by_supervisor)} sub="Counted against the same budgets" accent={tokens.statusHealthy} /></Grid>
        <Grid item xs={12} sm={4}><StatTile icon={PaidIcon} label="Spend today" value={inr2(data.totals.spend_today)} sub="Attempts × cost per attempt (D13)" /></Grid>
      </Grid>

      <Section title="Borrowers contacted today" subtitle="The per-borrower limit is 3 a day across all channels, lower in some buckets (R009–R032)">
        <Stack spacing={1.4}>
          {[['1', 'Once', tokens.statusHealthy], ['2', 'Twice', tokens.statusDegraded], ['3+', 'Three times or more (at the global cap)', tokens.statusFault]].map(([k, label, tone]) => (
            <Box key={k}>
              <Stack direction="row" justifyContent="space-between">
                <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey }}>{label}</Typography>
                <Typography className="tabular-nums" sx={{ fontSize: 11, fontWeight: 600, color: tokens.statValueGrey }}>
                  {num(dist[k])} borrowers · {((100 * dist[k]) / distTotal).toFixed(0)}%
                </Typography>
              </Stack>
              <LinearProgress variant="determinate" value={(100 * dist[k]) / distTotal}
                sx={{ height: 6, borderRadius: 3, mt: 0.4, backgroundColor: tokens.iconBadgeBg, '& .MuiLinearProgress-bar': { backgroundColor: tone } }} />
            </Box>
          ))}
        </Stack>
      </Section>

      {order.filter((a) => groups[a]).map((agent) => (
        <Section key={agent} title={agent.endsWith('_agent') ? `${titleCase(agent.replace('_agent', ''))} agent` : `External agency ${agent}`}
          subtitle={agent.endsWith('_agent') ? 'Daily attempt budget and spend cap per channel (D13)' : 'Not orchestrated here; shown because its contacts use the same borrowers'} noPad>
          <SimpleTable rows={groups[agent]} rowKey={(r) => r.resource_id}
            columns={[
              { key: 'channel', label: 'Channel', width: 120, render: (r) => <b>{CH[r.channel] || r.channel}</b> },
              { key: 'attempts', label: 'Attempts vs daily budget', width: 260, render: (r) => <UsageBar used={r.used_today} cap={r.daily_budget} height={5} /> },
              { key: 'spend', label: 'Spend vs cap (₹)', width: 240, render: (r) => <UsageBar used={r.spend_used} cap={r.spend_cap} digits={0} height={5} /> },
              { key: 'window', label: 'Hours', render: (r) => <span className="tabular-nums">{r.window}</span> },
              { key: 'buckets', label: 'Buckets', render: (r) => <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey }}>{r.buckets.join(' · ')}</Typography> },
              { key: 'note', label: '', render: (r) => (
                <Stack direction="row" spacing={0.5}>
                  {r.by_supervisor > 0 && <Chip size="small" label={`supervisor sent ${r.by_supervisor}`} sx={{ height: 18, fontSize: 10, fontWeight: 600, backgroundColor: tokens.statusHealthy }} />}
                  {r.agent.endsWith('_agent') && !r.integrated && <Chip size="small" label="no agent integrated" sx={{ height: 18, fontSize: 10, backgroundColor: '#eff0f0' }} />}
                </Stack>) },
            ]} />
        </Section>
      ))}
    </Stack>
  );
}
