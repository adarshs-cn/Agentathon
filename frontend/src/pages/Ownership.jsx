import { useNavigate } from 'react-router-dom';
import { Alert, Chip, Grid, Stack, Typography } from '@mui/material';
import HandshakeIcon from '@mui/icons-material/HandshakeOutlined';
import LockIcon from '@mui/icons-material/LockOutlined';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import GppBadIcon from '@mui/icons-material/GppBadOutlined';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import Section from '../components/Section';
import StatTile from '../components/StatTile';
import SimpleTable from '../components/SimpleTable';
import OutcomeChip from '../components/OutcomeChip';
import MonoId from '../components/MonoId';
import { RuleChips } from '../components/RuleChip';
import { fmtDateTime, fmtTime, titleCase } from '../utils/format';
import { tokens } from '../theme/muiTheme';

const ROLE_COLOR = { legal: tokens.statusFault, negotiation: tokens.navbarBg, servicing: tokens.linkBlue, reminder: tokens.statusHealthy };

function RoleChip({ role }) {
  return <Chip size="small" label={titleCase(role || '—')} sx={{ height: 20, fontSize: 10.5, fontWeight: 700, color: '#fff', backgroundColor: ROLE_COLOR[role] || tokens.statLabelGrey }} />;
}

export default function Ownership() {
  const navigate = useNavigate();
  const { data, error } = useApi(() => api.ownership(), [], { live: true });
  if (error && !data) return <Alert severity="error" sx={{ borderRadius: 2 }}>Could not load ownership: {error}</Alert>;
  if (!data) return null;
  const { summary } = data;
  const open = (r) => navigate(`/trace?account=${r.borrower_id}`);
  return (
    <Stack spacing={2}>
      <Grid container spacing={2}>
        <Grid item xs={12} sm={6} md={3}><StatTile icon={HandshakeIcon} label="Active ownership leases" value={summary.active_leases} sub="24 hours from the last contact (R038)" /></Grid>
        <Grid item xs={12} sm={6} md={3}><StatTile icon={SwapHorizIcon} label="Handoffs" value={summary.handoffs} sub="Higher priority took over, logged (A12)" /></Grid>
        <Grid item xs={12} sm={6} md={3}><StatTile icon={GppBadIcon} label="Simultaneous requests handled" value={summary.simultaneous} sub={`${summary.simultaneous_single_contact} ended with a single contact`} accent={tokens.statusHealthy} /></Grid>
        <Grid item xs={12} sm={6} md={3}><StatTile icon={LockIcon} label="Locks held right now" value={summary.locks_held} sub="Should be 0 between events" accent={summary.locks_held === 0 ? tokens.statusHealthy : tokens.statusDegraded} /></Grid>
      </Grid>

      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Section title="Who owns whom" subtitle="One owner per borrower at a time. Click a row to open the borrower." noPad>
            <SimpleTable maxHeight={360} rows={data.leases} onRowClick={open} empty="No leases yet: they start when the first contact is made."
              rowKey={(r) => r.borrower_id}
              columns={[
                { key: 'borrower_id', label: 'Borrower', render: (r) => <MonoId sx={{ fontSize: 12, fontWeight: 600, color: tokens.navbarBg }}>{r.borrower_id}</MonoId> },
                { key: 'role', label: 'Owner', render: (r) => <RoleChip role={r.role} /> },
                { key: 'until', label: 'Lease until', render: (r) => <MonoId sx={{ fontSize: 11.5 }}>{fmtDateTime(r.until)}</MonoId> },
                { key: 'in_flight', label: 'Lock', render: (r) => (r.in_flight ? <Chip size="small" label={`held by ${r.in_flight}`} sx={{ height: 18, fontSize: 10 }} /> : <Typography sx={{ fontSize: 11, color: '#bbb' }}>free</Typography>) },
              ]} />
          </Section>
        </Grid>
        <Grid item xs={12} md={6}>
          <Section title="Handoffs between agents" subtitle="Every ownership change is logged with its reason" noPad>
            <SimpleTable maxHeight={360} rows={data.handoffs} onRowClick={open} empty="No handoffs yet."
              columns={[
                { key: 'ts', label: 'Time', render: (r) => <MonoId className="tabular-nums" sx={{ fontSize: 11.5 }}>{fmtTime(r.ts)}</MonoId> },
                { key: 'borrower_id', label: 'Borrower', render: (r) => <MonoId sx={{ fontSize: 12, fontWeight: 600, color: tokens.navbarBg }}>{r.borrower_id}</MonoId> },
                { key: 'move', label: 'Change', render: (r) => <Stack direction="row" spacing={0.5} alignItems="center"><RoleChip role={r.from} /><span>→</span><RoleChip role={r.to} /></Stack> },
                { key: 'rule_ids', label: 'Rules', render: (r) => <Stack direction="row" spacing={0.5}><RuleChips ids={r.rule_ids} /></Stack> },
              ]} />
          </Section>
        </Grid>
      </Grid>

      <Section title="Two requests for one borrower at once" subtitle="Two events landed within 5 minutes of each other. The first acts; the second is checked against what just happened." noPad>
        <SimpleTable maxHeight={320} rows={data.simultaneous} onRowClick={open} empty="No simultaneous requests so far."
          rowKey={(r) => `${r.first.event_id}-${r.second.event_id}`}
          columns={[
            { key: 'borrower_id', label: 'Borrower', render: (r) => <MonoId sx={{ fontSize: 12, fontWeight: 600, color: tokens.navbarBg }}>{r.borrower_id}</MonoId> },
            { key: 'first', label: 'First request', render: (r) => <Stack direction="row" spacing={0.8} alignItems="center"><MonoId className="tabular-nums" sx={{ fontSize: 11 }}>{fmtTime(r.first.time)}</MonoId><span>{r.first.type}</span><OutcomeChip outcome={r.first.outcome} /></Stack> },
            { key: 'second', label: 'Second request', render: (r) => <Stack direction="row" spacing={0.8} alignItems="center"><MonoId className="tabular-nums" sx={{ fontSize: 11 }}>{fmtTime(r.second.time)}</MonoId><span>{r.second.type}</span><OutcomeChip outcome={r.second.outcome} /></Stack> },
            { key: 'rules', label: 'Rules', render: (r) => <Stack direction="row" spacing={0.5}><RuleChips ids={r.second.rule_ids} /></Stack> },
            { key: 'why', label: 'Why', render: (r) => <Typography sx={{ fontSize: 11.5, color: tokens.statLabelGrey }}>{r.second.reason}</Typography> },
          ]} />
      </Section>

      <Section title="Non-owner contacts stopped" subtitle="An agent tried to contact a borrower that another agent owns, and was blocked with the owner named (R036)" noPad>
        <SimpleTable maxHeight={320} rows={data.conflicts} onRowClick={open} empty="No conflicts so far."
          columns={[
            { key: 'ts', label: 'Time', render: (r) => <MonoId className="tabular-nums" sx={{ fontSize: 11.5 }}>{fmtTime(r.ts)}</MonoId> },
            { key: 'borrower_id', label: 'Borrower', render: (r) => <MonoId sx={{ fontSize: 12, fontWeight: 600, color: tokens.navbarBg }}>{r.borrower_id}</MonoId> },
            { key: 'blocked_role', label: 'Blocked agent', render: (r) => <RoleChip role={r.blocked_role} /> },
            { key: 'rule_ids', label: 'Rules', render: (r) => <Stack direction="row" spacing={0.5}><RuleChips ids={r.rule_ids} /></Stack> },
            { key: 'reason', label: 'Why', render: (r) => <Typography sx={{ fontSize: 11.5, color: tokens.statLabelGrey }}>{r.reason}</Typography> },
          ]} />
      </Section>
    </Stack>
  );
}
