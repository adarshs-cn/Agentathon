import { useNavigate } from 'react-router-dom';
import { Button, Chip } from '@mui/material';
import HealingIcon from '@mui/icons-material/Healing';
import Section from '../Section';
import SimpleTable from '../SimpleTable';
import MonoId from '../MonoId';
import OutcomeChip from '../OutcomeChip';
import EmptyState from '../EmptyState';
import { useApi } from '../../hooks/useApi';
import { api } from '../../api/client';

// The latest faults the supervisor recovered from, with what it did about each.
export default function RecentRecoveries() {
  const navigate = useNavigate();
  const { data } = useApi(() => api.journeys({ faults_only: 1, page_size: 5 }), [], { live: true });
  const rows = data?.items || [];
  const columns = [
    { key: 'when', label: 'When', render: (r) => <span className="tabular-nums">{(r.finished_at || '').slice(11, 16)}</span> },
    { key: 'who', label: 'Customer · Account', render: (r) => <MonoId sx={{ fontSize: 12 }}>{r.customer_id} · {r.account_id || '—'}</MonoId> },
    { key: 'fault', label: 'What went wrong → what the supervisor did', render: (r) => (
      <Chip size="small" color="warning" label={`${r.fault_label} → ${r.recovery_label}`} sx={{ fontSize: 11, textTransform: 'capitalize' }} />) },
    { key: 'out', label: 'Result', render: (r) => <OutcomeChip outcome={r.outcome} label={r.outcome_label} /> },
  ];
  return (
    <Section title="Recent faults, already handled" subtitle={`${data?.total ?? 0} in total. Each one also raised an alert on the bell.`}
      action={<Button size="small" onClick={() => navigate('/runs?faults_only=1')}>All runs</Button>} noPad>
      {rows.length ? (
        <SimpleTable columns={columns} rows={rows} rowKey={(r) => r.event_id} onRowClick={(r) => navigate(`/runs?highlight=${encodeURIComponent(r.event_id)}`)} />
      ) : <EmptyState icon={HealingIcon} title="No faults so far" hint="If a channel crashes, stalls or replies with garbage, it shows up here once the supervisor has dealt with it." />}
    </Section>
  );
}
