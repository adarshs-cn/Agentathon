import { useNavigate } from 'react-router-dom';
import { Typography } from '@mui/material';
import Section from '../Section';
import SimpleTable from '../SimpleTable';
import MonoId from '../MonoId';
import OutcomeChip from '../OutcomeChip';
import { useApi } from '../../hooks/useApi';
import { api } from '../../api/client';
import { tokens } from '../../theme/muiTheme';

const time = (v) => (v ? String(v).slice(11, 16) : '—');
const role = (r) => (r ? r.replace(/_agent$/, '').replace(/^\w/, (c) => c.toUpperCase()) : null);

// The customers the live monitor is watching, and where each one stands.
export default function WatchedCustomers() {
  const navigate = useNavigate();
  const { data } = useApi(() => api.monitorWatched(), [], { live: true });
  const rows = data?.items || [];
  const columns = [
    { key: 'customer', label: 'Customer', render: (r) => (
      <>
        <MonoId sx={{ fontSize: 12, fontWeight: 600, color: tokens.navbarBg }}>{r.customer_id}</MonoId>
        <Typography sx={{ fontSize: 10.5, color: tokens.statLabelGrey }}>{r.name_masked}</Typography>
      </>) },
    { key: 'account', label: 'Account · DPD', render: (r) => (
      <>
        <MonoId sx={{ fontSize: 12 }}>{r.account_id}</MonoId>
        <Typography sx={{ fontSize: 10.5, color: tokens.statLabelGrey }}>{r.dpd ?? 0} days past due</Typography>
      </>) },
    { key: 'owner', label: 'Owner', render: (r) => <Typography sx={{ fontSize: 12 }}>{role(r.owner) || <span style={{ color: tokens.statLabelGrey }}>Null</span>}</Typography> },
    { key: 'last', label: 'Last result', render: (r) => (r.last_outcome ? <OutcomeChip outcome={r.last_outcome} label={r.last_outcome_label} /> : <Typography sx={{ fontSize: 12, color: tokens.statLabelGrey }}>Not yet</Typography>) },
    { key: 'contact', label: 'Last contact', render: (r) => <span className="tabular-nums">{time(r.last_contact)}</span> },
    { key: 'next', label: 'Next event', render: (r) => <span className="tabular-nums">{time(r.next_due_at)}</span> },
  ];
  return (
    <Section title="Watched customers" subtitle={`${rows.length} customers the monitor looks after. Click a row to open the customer.`} noPad sx={{ height: '100%' }}>
      <SimpleTable columns={columns} rows={rows} maxHeight={380} rowKey={(r) => r.customer_id}
        onRowClick={(r) => navigate(`/trace?account=${r.account_id}`)} empty="The monitor has no customers yet." />
    </Section>
  );
}
