import { useNavigate } from 'react-router-dom';
import { Alert, Chip, Grid, Stack, Typography, Box } from '@mui/material';
import BugReportIcon from '@mui/icons-material/BugReport';
import HealingIcon from '@mui/icons-material/Healing';
import ContentCopyIcon from '@mui/icons-material/ContentCopyOutlined';
import SupportAgentIcon from '@mui/icons-material/SupportAgent';
import ScienceIcon from '@mui/icons-material/ScienceOutlined';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import Section from '../components/Section';
import StatTile from '../components/StatTile';
import StatusChip from '../components/StatusChip';
import OutcomeChip from '../components/OutcomeChip';
import SimpleTable from '../components/SimpleTable';
import EmptyState from '../components/EmptyState';
import MonoId from '../components/MonoId';
import { fmtTime, titleCase } from '../utils/format';
import { tokens } from '../theme/muiTheme';

const PROVIDER = {
  SENT: { tone: 'healthy', text: 'Provider: sent' },
  NOT_SENT: { tone: 'degraded', text: 'Provider: not sent' },
  UNKNOWN: { tone: 'fault', text: 'Provider: unknown' },
};
const ACTION_LABEL = {
  RESTART_SKIP_CURRENT: 'Skip: already sent',
  RESUME: 'Retry same agent',
  REROUTE_CHANNEL: 'Switch channel',
  ESCALATE: 'Escalate to human',
  QUARANTINE: 'Hold for review',
};
const OUTCOME_TEXT = {
  RESTART_SKIP_CURRENT: 'Message had already gone out: recorded, never resent',
  RESUME: 'Nothing was sent: the same agent was called again',
  REROUTE_CHANNEL: 'Nothing was sent: switched to the next channel',
  ESCALATE: 'No channel left: held for human review, state kept',
  QUARANTINE: 'Could not verify what happened: held for human review, state kept',
};

export default function Faults() {
  const navigate = useNavigate();
  const { data, error } = useApi(() => api.faults(), [], { live: true });
  if (error && !data) return <Alert severity="error" sx={{ borderRadius: 2 }}>Could not load faults: {error}</Alert>;
  if (!data) return null;
  const { summary, incidents, script } = data;

  return (
    <Stack spacing={2}>
      <Grid container spacing={2}>
        <Grid item xs={12} sm={6} md={3}>
          <StatTile icon={BugReportIcon} label="Faults fired so far" value={`${summary.injected} / ${summary.scheduled}`} sub="Scheduled for today's simulated day" />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatTile icon={HealingIcon} label="Recovered without losing state" value={`${summary.recovered} / ${summary.injected}`}
            sub={summary.recovered === summary.injected ? (summary.injected ? 'All recovered' : 'Waiting for the first fault') : 'Recovery pending'}
            accent={summary.recovered === summary.injected ? tokens.statusHealthy : tokens.statusDegraded} />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatTile icon={ContentCopyIcon} label="Double contacts prevented" value={summary.resends_prevented} sub="Crashed after sending: not resent" accent={tokens.statusHealthy} />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatTile icon={SupportAgentIcon} label="Escalated to a human" value={summary.escalated} sub="State preserved, nothing lost" accent={summary.escalated ? tokens.statusDegraded : tokens.statValueGrey} />
        </Grid>
      </Grid>

      <Section title="Incidents" subtitle="Every time the monitor stepped in. Click a row for the borrower's full trace." noPad>
        <SimpleTable
          maxHeight={420}
          empty="No faults yet. They appear here as the simulated day reaches them."
          rows={incidents}
          onRowClick={(r) => navigate(`/trace?account=${r.account_id}`)}
          columns={[
            { key: 'ts', label: 'Time', render: (r) => <MonoId className="tabular-nums" sx={{ fontSize: 11.5 }}>{fmtTime(r.ts)}</MonoId> },
            { key: 'account_id', label: 'Borrower', render: (r) => <MonoId sx={{ fontSize: 12, fontWeight: 600, color: tokens.navbarBg }}>{r.account_id}</MonoId> },
            { key: 'agent', label: 'Agent', render: (r) => <Chip size="small" label={r.agent} sx={{ height: 18, fontSize: 10, fontWeight: 600, backgroundColor: '#eff0f0' }} /> },
            { key: 'fault_type', label: 'Fault', render: (r) => <StatusChip status="fault" label={titleCase(r.fault_type.toLowerCase())} /> },
            { key: 'provider_state', label: 'What the provider said', render: (r) => { const p = PROVIDER[r.provider_state] || { tone: 'degraded', text: '—' }; return <StatusChip status={p.tone} label={p.text} />; } },
            { key: 'action', label: 'Recovery', render: (r) => <Chip size="small" label={ACTION_LABEL[r.action] || titleCase(r.action.toLowerCase())} sx={{ height: 20, fontSize: 10.5, fontWeight: 700, backgroundColor: tokens.actionPrimaryBg, color: '#000' }} /> },
            { key: 'result', label: 'What it means', render: (r) => <Typography sx={{ fontSize: 11.5, color: tokens.statLabelGrey }}>{OUTCOME_TEXT[r.action] || r.reason}</Typography> },
            { key: 'outcome', label: 'Final outcome', render: (r) => <OutcomeChip outcome={r.outcome} /> },
          ]}
        />
      </Section>

      <Grid container spacing={2}>
        <Grid item xs={12} md={7}>
          <Section title="The fault script" subtitle="What the simulator is injecting today. A fault is 'fired' once the agent actually misbehaves." action={<ScienceIcon sx={{ fontSize: 18, color: tokens.navbarBg }} />}>
            {script.length === 0 ? (
              <EmptyState icon={ScienceIcon} title="No faults scripted for this run" />
            ) : (
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                {Object.values(script.reduce((acc, s) => ({ ...acc, [`${s.account_id}${s.fault}`]: { ...s, calls: [...(acc[`${s.account_id}${s.fault}`]?.calls || []), s.call], fired: s.fired || acc[`${s.account_id}${s.fault}`]?.fired } }), {})).map((s) => (
                  <Chip key={s.account_id + s.fault} onClick={() => navigate(`/trace?account=${s.account_id}`)} clickable
                    label={`${s.account_id} · ${titleCase(s.fault.toLowerCase())}${s.calls.length > 1 ? ` ×${s.calls.length}` : ''}`}
                    icon={<Box component="span" sx={{ width: 8, height: 8, borderRadius: '50%', ml: '8px !important', backgroundColor: s.fired ? tokens.statusFault : tokens.dividerGrey }} />}
                    sx={{ height: 24, fontSize: 11, fontFamily: tokens.fontMono, backgroundColor: '#fff', border: `1px solid ${tokens.dividerGrey}` }} />
                ))}
              </Stack>
            )}
            <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey, mt: 1.5 }}>Red dot: fired. Grey dot: still to come. The supervisor never sees this script; it only sees an agent crash, hang, loop or return junk.</Typography>
          </Section>
        </Grid>
        <Grid item xs={12} md={5}>
          <Section title="How recovery decides" subtitle="It asks the provider, never the agent">
            <Stack spacing={1}>
              {[
                ['Provider says SENT', 'The message went out. Record it, never call the agent again.', 'healthy'],
                ['Provider says NOT SENT', 'Nothing went out. Retry, then switch channel, then escalate.', 'degraded'],
                ['Provider says UNKNOWN', 'Cannot tell. Refuse to risk a second message: hold for a human.', 'fault'],
              ].map(([t, d, tone]) => (
                <Stack key={t} direction="row" spacing={1.2} alignItems="flex-start">
                  <StatusChip status={tone} label={t} />
                  <Typography sx={{ fontSize: 11.5, color: tokens.statLabelGrey, pt: 0.3 }}>{d}</Typography>
                </Stack>
              ))}
            </Stack>
          </Section>
        </Grid>
      </Grid>
    </Stack>
  );
}
