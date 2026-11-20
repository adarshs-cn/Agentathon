import { Alert, Box, Chip, Grid, Paper, Stack, Typography } from '@mui/material';
import WhatsAppIcon from '@mui/icons-material/WhatsApp';
import EmailIcon from '@mui/icons-material/EmailOutlined';
import PhoneIcon from '@mui/icons-material/PhoneInTalkOutlined';
import CheckIcon from '@mui/icons-material/Check';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import Section from '../components/Section';
import StatusChip from '../components/StatusChip';
import MonoId from '../components/MonoId';
import SimpleTable from '../components/SimpleTable';
import { fmtDateTime, num, titleCase } from '../utils/format';
import { tokens } from '../theme/muiTheme';

const ICON = { whatsapp: WhatsAppIcon, email: EmailIcon, voice: PhoneIcon };
const LABEL = { whatsapp: 'WhatsApp agent', email: 'Email agent', voice: 'Voice / IVR agent' };
const STATUS_TEXT = { healthy: 'Healthy', degraded: 'Degraded', fault: 'Fault' };
const BUCKETS = ['0', '1-30', '31-60', '61-90', '90+'];

function Metric({ label, value, unit }) {
  return (
    <Box sx={{ minWidth: 70 }}>
      <Typography sx={{ fontSize: 10.5, color: tokens.statLabelGrey, fontWeight: 600 }}>{label}</Typography>
      <Typography className="tabular-nums" sx={{ fontSize: 18, fontWeight: 700, color: tokens.statValueGrey, lineHeight: 1.2 }}>
        {value}<Typography component="span" sx={{ fontSize: 11, color: tokens.statLabelGrey }}> {unit}</Typography>
      </Typography>
    </Box>
  );
}

function ChannelAgentCard({ a }) {
  const Icon = ICON[a.name] || EmailIcon;
  return (
    <Paper sx={{ borderRadius: 2.5, p: 2 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between">
        <Stack direction="row" alignItems="center" spacing={1.2}>
          <Box sx={{ width: 32, height: 32, borderRadius: 2, backgroundColor: tokens.iconBadgeBg, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Icon sx={{ fontSize: 19, color: tokens.navbarBg }} />
          </Box>
          <Box>
            <Typography sx={{ fontSize: 14, fontWeight: 600, color: '#222933' }}>{LABEL[a.name] || a.name}</Typography>
            <Typography sx={{ fontSize: 10.5, color: tokens.statLabelGrey }}>serves D12 channel “{a.d12_channel}”</Typography>
          </Box>
        </Stack>
        <StatusChip status={a.status} label={STATUS_TEXT[a.status]} />
      </Stack>
      <Stack direction="row" spacing={2.5} sx={{ mt: 2 }} flexWrap="wrap" useFlexGap>
        <Metric label="Calls" value={num(a.calls)} />
        <Metric label="Contacts sent" value={num(a.contacts_sent)} />
        <Metric label="Faults" value={num(a.faults)} />
        <Metric label="Avg time" value={a.avg_ms.toFixed(2)} unit="ms" />
        <Metric label="p95" value={a.p95_ms.toFixed(2)} unit="ms" />
      </Stack>
      <Box sx={{ mt: 1.5, p: 1.2, borderRadius: 2, backgroundColor: a.last_fault ? '#fdf3f3' : tokens.cardGroupedBg }}>
        {a.last_fault ? (
          <>
            <Typography sx={{ fontSize: 11, fontWeight: 700, color: tokens.statusFault }}>Last fault</Typography>
            <Typography sx={{ fontSize: 11.5, color: '#222933' }}>{a.last_fault.what}</Typography>
            <Typography sx={{ fontSize: 10.5, color: tokens.statLabelGrey }}>
              <MonoId>{a.last_fault.account_id}</MonoId> · {fmtDateTime(a.last_fault.ts)}
            </Typography>
          </>
        ) : (
          <Typography sx={{ fontSize: 11.5, color: tokens.statLabelGrey }}>No faults from this agent so far.</Typography>
        )}
      </Box>
    </Paper>
  );
}

export default function Agents() {
  const { data, error } = useApi(() => api.agents(), [], { live: true });
  if (error && !data) return <Alert severity="error" sx={{ borderRadius: 2 }}>Could not load agents: {error}</Alert>;
  if (!data) return null;
  return (
    <Stack spacing={2}>
      <Section title="Channel agents" subtitle="The agents your teammates built. Health is judged from the last 10 calls: any failure is 'degraded', half or more is 'fault'." noPad bodySx={{ p: 2 }}>
        <Grid container spacing={2}>
          {data.channel_agents.map((a) => (
            <Grid item xs={12} md={4} key={a.name}><ChannelAgentCard a={a} /></Grid>
          ))}
        </Grid>
      </Section>

      <Section title="Role agents: who may act, in which bucket" subtitle="From the D12 agent × bucket matrix. The number is the owner priority rank (1 = first choice)." noPad>
        <SimpleTable
          rows={data.role_agents}
          rowKey={(r) => r.name}
          columns={[
            { key: 'name', label: 'Agent', render: (r) => <b>{titleCase(r.name)}</b> },
            ...BUCKETS.map((b) => ({
              key: b, label: `Bucket ${b}`, render: (r) => {
                const c = r.buckets[b];
                return c?.allowed ? (
                  <Stack direction="row" spacing={0.5} alignItems="center">
                    <CheckIcon sx={{ fontSize: 14, color: tokens.statusHealthy }} />
                    <Chip size="small" label={`#${c.rank}`} sx={{ height: 18, fontSize: 10, fontWeight: 700, backgroundColor: '#eff0f0' }} />
                    <Typography sx={{ fontSize: 10, color: tokens.statLabelGrey }}>{c.channels.filter((x) => ['whatsapp', 'email', 'call'].includes(x)).join(' ')}</Typography>
                  </Stack>
                ) : (
                  <Typography sx={{ fontSize: 11, color: '#bbb' }}>not allowed</Typography>
                );
              },
            })),
            { key: 'contacts_sent', label: 'Sent', align: 'right', render: (r) => <span className="tabular-nums">{r.contacts_sent}</span> },
            { key: 'decisions', label: 'Routed', align: 'right', render: (r) => <span className="tabular-nums">{r.decisions}</span> },
            { key: 'handoffs', label: 'Handoffs in / out', align: 'right', render: (r) => <span className="tabular-nums">{r.handoffs_in} / {r.handoffs_out}</span> },
          ]}
        />
      </Section>
      <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey }}>
        External agencies (AGY001–003) are not orchestrated here, but their contacts still count toward the caps and ownership.
      </Typography>
    </Stack>
  );
}
