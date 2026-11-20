import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Paper, Stack, Typography, TextField, Chip, Alert, FormControlLabel, Checkbox, Tooltip } from '@mui/material';
import { DataGrid } from '@mui/x-data-grid';
import { api } from '../api/client';
import { useSim } from '../context/simState';
import MonoId from '../components/MonoId';
import OutcomeChip from '../components/OutcomeChip';
import { alpha } from '@mui/material/styles';
import { tokens } from '../theme/muiTheme';

const when = (v) => (v ? String(v).replace('T', ' ').slice(0, 19) : '—');
const words = (v) => (v ? v.replace(/_agent$/, '').replace(/_/g, ' ') : '—');

export default function JourneyRuns() {
  const navigate = useNavigate();
  const [sp, setSp] = useSearchParams();
  const highlight = useMemo(() => (sp.get('highlight') || '').split(',').filter(Boolean), [sp]);
  const { subscribeRun, tick } = useSim();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState({});
  const [pm, setPm] = useState({ page: 0, pageSize: 25 });
  const [sort, setSort] = useState([{ field: 'finished', sort: 'desc' }]);
  const [bump, setBump] = useState(0);

  useEffect(() => subscribeRun(({ type }) => type === 'run_end' && setBump((b) => b + 1)), [subscribeRun]);

  const params = useMemo(() => {
    const p = { page: pm.page + 1, page_size: pm.pageSize, sort_by: sort[0]?.field || 'finished', sort_dir: sort[0]?.sort || 'desc' };
    Object.entries(filters).forEach(([k, v]) => v && (p[k] = v));
    if (highlight.length) p.pin = highlight.join(',');
    return p;
  }, [filters, pm, sort, highlight]);

  useEffect(() => {
    setLoading(true);
    api.journeys(params)
      .then((d) => { setData(d); setError(null); })
      .catch((e) => setError(e.message || 'Request failed'))
      .finally(() => setLoading(false));
  }, [params, tick, bump]);

  const set = (k) => (e) => { setFilters((f) => ({ ...f, [k]: e.target.value })); setPm((m) => ({ ...m, page: 0 })); };

  const columns = [
    { field: 'finished', headerName: 'Ran at', width: 160, renderCell: (p) => when(p.row.finished_at) },
    { field: 'customer_id', headerName: 'Customer', width: 110, renderCell: (p) => <MonoId>{p.value}</MonoId> },
    { field: 'account_id', headerName: 'Account', width: 110, sortable: false, renderCell: (p) => <MonoId>{p.value || '—'}</MonoId> },
    { field: 'name_masked', headerName: 'Name', width: 110, sortable: false, renderCell: (p) => p.value || '—' },
    { field: 'event_type', headerName: 'Event', width: 150, renderCell: (p) => words(p.value) },
    { field: 'channel', headerName: 'Channel', width: 100, sortable: false, renderCell: (p) => p.value || '—' },
    { field: 'role', headerName: 'Owner after', width: 150, sortable: false,
      renderCell: (p) => (p.row.owner_after ? <Chip size="small" label={words(p.row.owner_after)} sx={{ textTransform: 'capitalize', fontSize: 11 }} /> : <Typography sx={{ fontSize: 12, color: tokens.statLabelGrey }}>Null</Typography>) },
    { field: 'outcome', headerName: 'Outcome', width: 150, renderCell: (p) => <OutcomeChip outcome={p.value} label={p.row.outcome_label} /> },
    { field: 'fault', headerName: 'Fault and recovery', width: 230, sortable: false,
      renderCell: (p) => (p.row.had_fault
        ? <Tooltip title={p.row.recovery_reason || ''}><Chip size="small" color="warning" label={`${p.row.fault_label} → ${p.row.recovery_label}`} sx={{ fontSize: 11, textTransform: 'capitalize' }} /></Tooltip>
        : <Typography sx={{ fontSize: 12, color: tokens.statLabelGrey }}>None</Typography>) },
    { field: 'summary', headerName: 'What the supervisor did', flex: 1, minWidth: 260, sortable: false },
    { field: 'duration_ms', headerName: 'Took', width: 80, type: 'number', renderCell: (p) => (p.value == null ? '—' : `${Math.round(p.value)} ms`) },
  ];

  return (
    <Stack spacing={1.5} sx={{ height: '100%' }}>
      <Paper sx={{ p: 1.5, borderRadius: 2.5 }}>
        <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap>
          <TextField size="small" label="Customer ID" value={filters.customer_id || ''} onChange={set('customer_id')} sx={{ width: 150 }} />
          <FormControlLabel
            control={<Checkbox size="small" checked={!!filters.faults_only} onChange={(e) => { setFilters((f) => ({ ...f, faults_only: e.target.checked || undefined })); setPm((m) => ({ ...m, page: 0 })); }} />}
            label="Only runs with a fault"
          />
          <Typography sx={{ fontSize: 12, color: tokens.statLabelGrey }}>
            {data?.total ?? 0} runs. Every finished run is saved and is still here after a restart.
          </Typography>
        </Stack>
      </Paper>
      {highlight.length > 0 && (
        <Alert severity="warning" onClose={() => setSp({})}>
          {highlight.length === 1 ? 'This run had a fault that the supervisor recovered.' : `${highlight.length} runs had a fault that the supervisor recovered.`} Highlighted below.
        </Alert>
      )}
      {error && <Alert severity="error">Could not load journey runs ({error}). Restart the backend if you just updated the code.</Alert>}
      <Paper sx={{ borderRadius: 2.5, flex: 1, minHeight: 500 }}>
        <DataGrid
          rows={data?.items || []} columns={columns} getRowId={(r) => r.id} loading={loading}
          rowCount={data?.total || 0} paginationMode="server" sortingMode="server"
          paginationModel={pm} onPaginationModelChange={setPm} sortModel={sort} onSortModelChange={setSort}
          pageSizeOptions={[25, 50, 100]} onRowClick={(r) => navigate(`/trace?account=${r.row.account_id || r.row.customer_id}`)}
          density="compact" disableRowSelectionOnClick
          getRowClassName={(p) => (highlight.includes(p.row.event_id) ? 'hl' : '')}
          sx={{ border: 'none', fontSize: 12.5, '& .MuiDataGrid-columnHeaders': { backgroundColor: tokens.cardGroupedBg, fontSize: 10.5, fontWeight: 700, color: tokens.statTitleGrey }, '& .MuiDataGrid-row': { cursor: 'pointer' }, '& .hl': { backgroundColor: alpha(tokens.statusDegraded, 0.35), boxShadow: `inset 3px 0 0 ${tokens.statusFault}` } }}
        />
      </Paper>
    </Stack>
  );
}
