import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Alert, Box, Button, Chip, Collapse, Grid, Paper, Stack, Typography } from '@mui/material';
import { Timeline, TimelineConnector, TimelineContent, TimelineDot, TimelineItem, TimelineOppositeContent, TimelineSeparator } from '@mui/lab';
import PersonSearchIcon from '@mui/icons-material/PersonSearch';
import ShieldIcon from '@mui/icons-material/VerifiedUserOutlined';
import HistoryIcon from '@mui/icons-material/History';
import QuestionAnswerIcon from '@mui/icons-material/QuestionAnswerOutlined';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import LockIcon from '@mui/icons-material/LockOutlined';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import Section from '../components/Section';
import EmptyState from '../components/EmptyState';
import MonoId from '../components/MonoId';
import OutcomeChip, { OUTCOME_VARIANTS } from '../components/OutcomeChip';
import StatusChip from '../components/StatusChip';
import UsageBar from '../components/UsageBar';
import ChannelVerdict from '../components/ChannelVerdict';
import EventRow from '../components/EventRow';
import SimpleTable from '../components/SimpleTable';
import BorrowerSearch from '../components/BorrowerSearch';
import { RuleChips } from '../components/RuleChip';
import { fmtDateTime, fmtTime, inr, titleCase } from '../utils/format';
import { tokens } from '../theme/muiTheme';

function Fact({ label, children }) {
  return (
    <Box sx={{ minWidth: 110 }}>
      <Typography sx={{ fontSize: 10.5, color: tokens.statLabelGrey, fontWeight: 600 }}>{label}</Typography>
      <Box sx={{ fontSize: 13, fontWeight: 600, color: '#222933', mt: 0.2 }}>{children}</Box>
    </Box>
  );
}

function FlagChips({ f }) {
  const flags = [f.legal && 'legal', f.settlement && 'settlement', f.restructure && 'restructure', f.deceased && 'deceased', f.shared_phone && 'shared phone'].filter(Boolean);
  if (!flags.length) return <Typography sx={{ fontSize: 12, color: tokens.statLabelGrey }}>none</Typography>;
  return (
    <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
      {flags.map((x) => (
        <Chip key={x} size="small" label={x} sx={{ height: 18, fontSize: 10, fontWeight: 600, backgroundColor: '#eff0f0' }} />
      ))}
    </Stack>
  );
}

const GUARD_TONE = { OK: ['healthy', 'Allowed'], BLOCKED: ['fault', 'Blocked'], DEFERRED: ['degraded', 'Later'] };

function Standing({ s }) {
  const probe = s.probe;
  const plan = probe.plan;
  // The chip shows the FINAL answer: the guard can pass while no agent is allowed to act.
  const final = probe.guard.status !== 'OK' ? probe.guard.status : plan?.status || 'OK';
  const [tone, word] = final === 'SUPPRESSED' ? ['degraded', 'No agent can act'] : GUARD_TONE[final] || ['degraded', final];
  const first = plan?.considered?.[0];
  return (
    <Stack spacing={2}>
      <Section title="Standing right now" subtitle="Limits and holds that apply at the current simulated time" action={<ShieldIcon sx={{ fontSize: 18, color: tokens.navbarBg }} />}>
        <Stack spacing={1.4}>
          <UsageBar label="Contacts today (all channels, all accounts)" used={s.caps.today.used} cap={s.caps.today.cap} />
          <Box sx={{ mt: -0.5 }}><RuleChips ids={s.caps.today.rule_ids} /></Box>
          <UsageBar label="Contacts in 7 days" used={s.caps.week.used} cap={s.caps.week.cap} />
          <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1.5 }}>
            {Object.entries(s.caps.by_channel).map(([ch, v]) => (
              <Box key={ch}>
                {v.integrated ? (
                  <UsageBar label={`${titleCase(ch)} today`} used={v.used} cap={v.cap} height={4} />
                ) : (
                  <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey }}>{titleCase(ch)}: no agent integrated</Typography>
                )}
              </Box>
            ))}
          </Box>
          {s.holds.length > 0 && (
            <Stack spacing={0.8} sx={{ pt: 0.5 }}>
              {s.holds.map((h, i) => (
                <Alert key={i} severity="warning" icon={<LockIcon fontSize="small" />} sx={{ py: 0, fontSize: 12, borderRadius: 2 }}
                  action={<RuleChips ids={[h.rule]} />}>
                  {titleCase(h.kind)}: {h.detail}
                </Alert>
              ))}
            </Stack>
          )}
        </Stack>
      </Section>

      <Section title={`If the next event (${probe.event_type}) arrived right now`} subtitle="The policy engine's live answer, with the rules behind it" action={<QuestionAnswerIcon sx={{ fontSize: 18, color: tokens.navbarBg }} />}>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
          <StatusChip status={tone} label={word} />
          {plan?.role && (
            <Typography sx={{ fontSize: 12.5, color: '#222933' }}>
              <b>{plan.role}</b> would act ({plan.action}) via <b>{plan.channel_agents.join(', ') || 'no channel'}</b>
            </Typography>
          )}
          <RuleChips ids={probe.guard.rule_ids?.length ? probe.guard.rule_ids : plan?.rule_ids} />
        </Stack>
        {probe.guard.status !== 'OK' && <Typography sx={{ fontSize: 12, color: tokens.statLabelGrey }}>{probe.guard.reason}</Typography>}
        {plan?.handoff && (
          <Alert severity="info" sx={{ py: 0, fontSize: 12, borderRadius: 2, my: 1 }}>
            Handoff from {plan.handoff.from} to {plan.handoff.to}: {plan.handoff.why}
          </Alert>
        )}
        {first?.channels?.map((c) => <ChannelVerdict key={c.channel} {...c} />)}
        {first && !first.channels && <Typography sx={{ fontSize: 12, color: tokens.statLabelGrey }}>{first.reason}</Typography>}
        {plan?.status === 'SUPPRESSED' && <Typography sx={{ fontSize: 12, color: tokens.statLabelGrey }}>{plan.reason}</Typography>}
      </Section>
    </Stack>
  );
}

function EventCard({ e }) {
  const [open, setOpen] = useState(false);
  const last = e.outcome || e.status;
  const color = (OUTCOME_VARIANTS[last]?.bg) || tokens.dividerGrey;
  const ids = [...new Set((e.feed || []).flatMap((x) => x.rule_ids || []))];
  return (
    <TimelineItem sx={{ '&:before': { display: 'none' } }}>
      <TimelineOppositeContent sx={{ flex: 0.18, minWidth: 90, pt: 1.6 }}>
        <MonoId className="tabular-nums" sx={{ fontSize: 12, fontWeight: 700, color: tokens.navbarBg }}>{fmtTime(e.time)}</MonoId>
        <Typography sx={{ fontSize: 10.5, color: tokens.statLabelGrey }}>{e.time.slice(0, 10)}</Typography>
      </TimelineOppositeContent>
      <TimelineSeparator>
        <TimelineDot sx={{ backgroundColor: color, boxShadow: 'none', my: 1.4 }} />
        <TimelineConnector sx={{ backgroundColor: tokens.dividerGrey }} />
      </TimelineSeparator>
      <TimelineContent sx={{ pb: 2.5 }}>
        <Paper variant="outlined" sx={{ borderRadius: 2, boxShadow: 'none', borderColor: tokens.dividerGrey, overflow: 'hidden' }}>
          <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap" useFlexGap sx={{ px: 1.5, py: 1, backgroundColor: tokens.cardGroupedBg }}>
            <MonoId sx={{ fontSize: 11.5, fontWeight: 600 }}>{e.event_id}</MonoId>
            <Chip size="small" label={e.type} sx={{ height: 18, fontSize: 10, fontWeight: 600, backgroundColor: '#fff' }} />
            <OutcomeChip outcome={last} />
            <Box sx={{ flex: 1 }} />
            <RuleChips ids={ids} />
          </Stack>
          <Box sx={{ px: 1 }}>
            {(e.feed || []).map((x) => <EventRow key={x.event_id} event={x} showAccount={false} />)}
          </Box>
          <Box sx={{ px: 1.5, pb: 0.5 }}>
            <Button size="small" onClick={() => setOpen((o) => !o)} endIcon={open ? <ExpandLessIcon /> : <ExpandMoreIcon />}
              sx={{ fontSize: 11, color: tokens.navbarBg }}>
              {open ? 'Hide' : 'Show'} all {e.steps.length} graph steps with their data
            </Button>
          </Box>
          <Collapse in={open} unmountOnExit>
            <Box sx={{ px: 1.5, pb: 1.5 }}>
              {e.steps.map((s, i) => (
                <Box key={i} sx={{ py: 0.6, borderTop: `1px dashed ${tokens.dividerGrey}` }}>
                  <Stack direction="row" spacing={1} alignItems="baseline">
                    <MonoId sx={{ fontSize: 11, fontWeight: 700, color: tokens.navbarBg, minWidth: 110 }}>{s.node}</MonoId>
                    <Typography sx={{ fontSize: 11.5, color: '#222933' }}>{s.text}</Typography>
                  </Stack>
                  {s.data && (
                    <Box component="pre" sx={{ m: 0, mt: 0.4, ml: '118px', p: 1, borderRadius: 1.5, backgroundColor: tokens.containerBg,
                      fontFamily: tokens.fontMono, fontSize: 10.5, color: tokens.statValueGrey, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 220, overflow: 'auto' }}>
                      {JSON.stringify(s.data, null, 1)}
                    </Box>
                  )}
                </Box>
              ))}
            </Box>
          </Collapse>
        </Paper>
      </TimelineContent>
    </TimelineItem>
  );
}

function StartHere() {
  const navigate = useNavigate();
  const { data: faults } = useApi(() => api.faults(), []);
  const { data: blocked } = useApi(() => api.decisions({ outcome: 'BLOCKED', page_size: 4 }), []);
  const { data: deferred } = useApi(() => api.decisions({ outcome: 'DEFERRED', page_size: 3 }), []);
  const { data: own } = useApi(() => api.ownership(), []);
  const picks = [
    ...(faults?.incidents || []).slice(0, 4).map((i) => ({ id: i.account_id, why: `${titleCase(i.fault_type.toLowerCase())} on ${i.agent}: ${titleCase(i.action.toLowerCase())}`, tone: 'fault' })),
    ...(own?.handoffs || []).slice(0, 2).map((h) => ({ id: h.borrower_id, why: `handoff ${h.from} → ${h.to}`, tone: 'degraded' })),
    ...(blocked?.items || []).slice(0, 3).map((d) => ({ id: d.account_id, why: `blocked by ${(d.rule_ids || []).join(', ')}`, tone: 'degraded' })),
    ...(deferred?.items || []).slice(0, 2).map((d) => ({ id: d.account_id, why: 'deferred to the next contact window', tone: 'healthy' })),
  ].filter((p) => p.id && p.id !== '-');
  return (
    <Stack spacing={2}>
      <Section title="Find a borrower" subtitle="Any account or customer number. Press / on any page to jump here.">
        <BorrowerSearch width="100%" />
      </Section>
      <Section title="Interesting borrowers to look at" subtitle="Picked from what the supervisor has done so far in the simulated day">
        {picks.length === 0 ? (
          <EmptyState icon={PersonSearchIcon} title="Nothing to suggest yet" hint="Press play on the sim clock. Faults, handoffs and blocked contacts will be listed here so you can open their traces." />
        ) : (
          <Stack>
            {picks.map((p, i) => (
              <Stack key={i} direction="row" spacing={1.5} alignItems="center" onClick={() => navigate(`/trace?account=${p.id}`)}
                sx={{ py: 1, px: 1, cursor: 'pointer', borderBottom: `1px solid ${tokens.dividerGrey}`, '&:hover': { backgroundColor: tokens.cardGroupedBg }, '&:last-child': { borderBottom: 'none' } }}>
                <MonoId sx={{ fontSize: 12, fontWeight: 600, color: tokens.navbarBg, minWidth: 90 }}>{p.id}</MonoId>
                <Typography sx={{ fontSize: 12, color: tokens.statLabelGrey }}>{p.why}</Typography>
              </Stack>
            ))}
          </Stack>
        )}
      </Section>
    </Stack>
  );
}

export default function BorrowerTrace() {
  const [params] = useSearchParams();
  const account = params.get('account');
  const state = useApi(() => (account ? api.borrowerState(account) : Promise.resolve(null)), [account], { live: true });
  const trace = useApi(() => (account ? api.borrowerTrace(account) : Promise.resolve(null)), [account], { live: true });

  if (!account) return <StartHere />;

  if (state.error && !state.data) {
    return (
      <Stack spacing={2}>
        <BorrowerSearch width={320} />
        <Alert severity="warning" sx={{ borderRadius: 2 }}>No borrower found for “{account}”. Try an account number such as ACC000123 or a customer number such as BRW00123.</Alert>
      </Stack>
    );
  }
  const s = state.data;
  const t = trace.data;
  return (
    <Stack spacing={2}>
      {s && (
        <Section title={`Borrower ${s.borrower_id}`} subtitle={`Opened from ${s.requested_id}. Name and phone are masked in the database.`}>
          <Stack direction="row" spacing={3} flexWrap="wrap" useFlexGap>
            <Fact label="Customer">{s.name || '—'} <MonoId sx={{ fontSize: 11, color: tokens.statLabelGrey }}>{s.phone}</MonoId></Fact>
            <Fact label="Accounts">{s.accounts.length}</Fact>
            <Fact label="Worst DPD / bucket">{s.facts.dpd} <Chip size="small" label={s.facts.bucket} sx={{ height: 18, fontSize: 10.5, fontWeight: 700, ml: 0.5 }} /></Fact>
            <Fact label="Flags"><FlagChips f={s.facts} /></Fact>
            <Fact label="Owner (24 h lease)">
              {s.ownership.role ? <>{s.ownership.role} <Typography component="span" sx={{ fontSize: 11, color: tokens.statLabelGrey }}>until {fmtDateTime(s.ownership.until)}</Typography></> : <span style={{ color: '#999' }}>unassigned</span>}
            </Fact>
            <Fact label="Supervisor status"><StatusChip status={s.state.status === 'ACTIVE' ? 'healthy' : 'fault'} label={s.state.status || '—'} /></Fact>
          </Stack>
          <Box sx={{ mt: 1.5 }}>
            <SimpleTable
              columns={[
                { key: 'account_id', label: 'Account', render: (a) => <MonoId sx={{ fontSize: 12 }}>{a.account_id}</MonoId> },
                { key: 'product', label: 'Product' },
                { key: 'dpd', label: 'DPD', align: 'right', render: (a) => <span className="tabular-nums">{a.dpd}</span> },
                { key: 'delinquency_bucket', label: 'Bucket' },
                { key: 'account_status', label: 'Status', render: (a) => titleCase(a.account_status) },
                { key: 'loan_amount', label: 'Loan', align: 'right', render: (a) => inr(a.loan_amount) },
                { key: 'total_overdue', label: 'Overdue', align: 'right', render: (a) => inr(a.total_overdue) },
              ]}
              rows={s.accounts}
              rowKey={(a) => a.account_id}
            />
          </Box>
        </Section>
      )}

      <Grid container spacing={2}>
        <Grid item xs={12} md={5}>{s && <Standing s={s} />}</Grid>
        <Grid item xs={12} md={7}>
          <Section title="Everything that happened to this borrower" subtitle={t ? `${t.event_count} event${t.event_count === 1 ? '' : 's'} · trace ${t.complete ? 'complete' : 'has gaps'}` : ''}
            action={<HistoryIcon sx={{ fontSize: 18, color: tokens.navbarBg }} />}>
            {!t || t.events.length === 0 ? (
              <EmptyState icon={HistoryIcon} title="No events for this borrower yet" hint="Nothing has been routed to them in the simulated day so far. Press play, or open one of the suggested borrowers on this page's start screen." />
            ) : (
              <Timeline sx={{ p: 0, m: 0 }}>{t.events.map((e) => <EventCard key={e.event_id} e={e} />)}</Timeline>
            )}
          </Section>
        </Grid>
      </Grid>

      {s && (
        <Section title="Recent contacts (last 7 days)" subtitle="Contacts made before today come from the D4 history; today's come from the supervisor" noPad>
          <SimpleTable
            columns={[
              { key: 'at', label: 'When', render: (c) => <MonoId sx={{ fontSize: 11.5 }}>{fmtDateTime(c.at)}</MonoId> },
              { key: 'channel', label: 'Channel', render: (c) => titleCase(c.channel) },
              { key: 'role', label: 'By' },
              { key: 'source', label: 'Source', render: (c) => <Chip size="small" label={c.source === 'ours' ? 'supervisor' : 'history'} sx={{ height: 18, fontSize: 10, backgroundColor: c.source === 'ours' ? tokens.statusHealthy : '#eff0f0', fontWeight: 600 }} /> },
              { key: 'disposition', label: 'Disposition' },
            ]}
            rows={s.recent_contacts}
            rowKey={(c) => `${c.at}${c.channel}${c.role}`}
            empty="No contacts in the last 7 days"
          />
        </Section>
      )}
    </Stack>
  );
}
