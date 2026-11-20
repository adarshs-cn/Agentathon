import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Alert, Box, Button, Chip, Drawer, FormControl, IconButton, InputLabel, MenuItem, Paper, Select, Stack, TextField, Typography } from '@mui/material';
import { DataGrid } from '@mui/x-data-grid';
import CloseIcon from '@mui/icons-material/Close';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import ClearAllIcon from '@mui/icons-material/ClearAll';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { useRules } from '../hooks/useRules';
import MonoId from '../components/MonoId';
import OutcomeChip from '../components/OutcomeChip';
import RuleChip, { RuleChips } from '../components/RuleChip';
import { gridSx } from '../components/gridStyles';
import { fmtDateTime, fmtTime, titleCase } from '../utils/format';
import { tokens } from '../theme/muiTheme';

const OUTCOMES = ['CONTACTED', 'BLOCKED', 'SUPPRESSED', 'DEFERRED', 'ESCALATED', 'REJECTED'];
const TYPES = ['DUE_SOON', 'OVERDUE', 'PTP_DUE', 'PTP_BROKEN', 'PAYMENT_RECEIVED', 'CONTACT_REQUESTED', 'SERVICE_REQUEST'];
const AGENTS = ['email', 'voice'];

function Detail({ row, onClose }) {
  const navigate = useNavigate();
  const rules = useRules();
  if (!row) return null;
  return (
    <Box sx={{ width: 420, p: 0 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ px: 2, py: 1.2, backgroundColor: tokens.cardGroupedBg, borderBottom: `1px solid ${tokens.dividerGrey}` }}>
        <Box>
          <Typography sx={{ fontSize: 14, fontWeight: 600, color: tokens.statTitleGrey }}>Decision</Typography>
          <MonoId sx={{ fontSize: 11, color: tokens.statLabelGrey }}>{row.event_id}</MonoId>
        </Box>
        <IconButton size="small" onClick={onClose}><CloseIcon fontSize="small" /></IconButton>
      </Stack>
      <Stack spacing={2} sx={{ p: 2 }}>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <OutcomeChip outcome={row.outcome} />
          <Chip size="small" label={row.type} sx={{ height: 20, fontSize: 10.5, fontWeight: 600, backgroundColor: '#eff0f0' }} />
          <MonoId className="tabular-nums" sx={{ fontSize: 11.5, color: tokens.statLabelGrey }}>{fmtDateTime(row.ts)}</MonoId>
        </Stack>
        <Box>
          <Typography sx={{ fontSize: 10.5, fontWeight: 600, color: tokens.statLabelGrey }}>Borrower</Typography>
          <MonoId sx={{ fontSize: 13, fontWeight: 600, color: tokens.navbarBg }}>{row.account_id}</MonoId>
        </Box>
        {row.role && (
          <Box>
            <Typography sx={{ fontSize: 10.5, fontWeight: 600, color: tokens.statLabelGrey }}>Who acted</Typography>
            <Typography sx={{ fontSize: 13, fontWeight: 600 }}>{titleCase(row.role)} ({row.action}) via {row.agent}</Typography>
          </Box>
        )}
        <Box>
          <Typography sx={{ fontSize: 10.5, fontWeight: 600, color: tokens.statLabelGrey }}>Why</Typography>
          <Typography sx={{ fontSize: 12.5, color: '#222933', mt: 0.3 }}>{row.reason || 'Routed normally; no rule stopped it.'}</Typography>
        </Box>
        <Box>
          <Typography sx={{ fontSize: 10.5, fontWeight: 600, color: tokens.statLabelGrey, mb: 0.6 }}>Rules cited</Typography>
          {row.rule_ids?.length ? (
            <Stack spacing={1}>
              {row.rule_ids.map((id) => (
                <Stack key={id} direction="row" spacing={1} alignItems="flex-start">
                  <RuleChip id={id} />
                  <Typography sx={{ fontSize: 11.5, color: tokens.statLabelGrey }}>{rules[id]?.description || '—'}</Typography>
                </Stack>
              ))}
            </Stack>
          ) : (
            <Typography sx={{ fontSize: 12, color: tokens.statLabelGrey }}>None: nothing blocked this event.</Typography>
          )}
        </Box>
        <Button variant="contained" color="primary" startIcon={<OpenInNewIcon />} onClick={() => navigate(`/trace?account=${row.account_id}`)}>
          Open full trace
        </Button>
      </Stack>
    </Box>
  );
}

export default function Decisions() {
  const [params, setParams] = useSearchParams();
  const rules = useRules();
  const [pagination, setPagination] = useState({ page: 0, pageSize: 25 });
  const [selected, setSelected] = useState(null);
  const filters = { outcome: params.get('outcome') || '', type: params.get('type') || '', rule_id: params.get('rule_id') || '', agent: params.get('agent') || '', account_id: params.get('account_id') || '' };

  const set = (k, v) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v); else next.delete(k);
    setParams(next, { replace: true });
    setPagination((p) => ({ ...p, page: 0 }));
  };
  const query = useMemo(() => ({ page: pagination.page + 1, page_size: pagination.pageSize, ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [pagination, params]);
  const { data, error, loading } = useApi(() => api.decisions(query), [JSON.stringify(query)], { live: true });
  // The selected rule is always an option, even before the rule list has loaded (deep links from a rule chip).
  const ruleIds = Array.from(new Set([...(filters.rule_id ? [filters.rule_id] : []), ...Object.keys(rules)])).sort();
  const active = Object.values(filters).filter(Boolean).length;

  const columns = [
    { field: 'ts', headerName: 'Time', width: 90, sortable: false, renderCell: (p) => <MonoId className="tabular-nums" sx={{ fontSize: 12 }}>{fmtTime(p.value)}</MonoId> },
    { field: 'account_id', headerName: 'Borrower', width: 110, sortable: false, renderCell: (p) => <MonoId sx={{ fontSize: 12, fontWeight: 600, color: tokens.navbarBg }}>{p.value}</MonoId> },
    { field: 'type', headerName: 'Event', width: 175, sortable: false },
    { field: 'outcome', headerName: 'Outcome', width: 130, sortable: false, renderCell: (p) => <OutcomeChip outcome={p.value} /> },
    { field: 'role', headerName: 'Agent', width: 150, sortable: false, valueGetter: (p) => (p.row.role ? `${titleCase(p.row.role)} → ${p.row.agent}` : '—') },
    { field: 'rule_ids', headerName: 'Rules cited', width: 200, sortable: false, renderCell: (p) => <Stack direction="row" spacing={0.4} sx={{ overflow: 'hidden' }}><RuleChips ids={p.value} max={3} /></Stack> },
    { field: 'reason', headerName: 'Reason', flex: 1, minWidth: 280, sortable: false },
  ];

  if (error && !data) return <Alert severity="error" sx={{ borderRadius: 2 }}>Could not load the decision log: {error}</Alert>;

  return (
    <Stack spacing={2} sx={{ height: '100%' }}>
      <Paper sx={{ p: 2, borderRadius: 2.5 }}>
        <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap>
          <FormControl size="small" sx={{ minWidth: 140 }}>
            <InputLabel>Outcome</InputLabel>
            <Select label="Outcome" value={filters.outcome} onChange={(e) => set('outcome', e.target.value)}>
              <MenuItem value="">Any</MenuItem>
              {OUTCOMES.map((o) => <MenuItem key={o} value={o}>{titleCase(o.toLowerCase())}</MenuItem>)}
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel>Event type</InputLabel>
            <Select label="Event type" value={filters.type} onChange={(e) => set('type', e.target.value)}>
              <MenuItem value="">Any</MenuItem>
              {TYPES.map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel>Rule cited</InputLabel>
            <Select label="Rule cited" value={filters.rule_id} onChange={(e) => set('rule_id', e.target.value)} MenuProps={{ PaperProps: { sx: { maxHeight: 320 } } }}>
              <MenuItem value="">Any</MenuItem>
              {ruleIds.map((o) => <MenuItem key={o} value={o}><MonoId sx={{ fontSize: 12 }}>{o}</MonoId></MenuItem>)}
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 130 }}>
            <InputLabel>Channel agent</InputLabel>
            <Select label="Channel agent" value={filters.agent} onChange={(e) => set('agent', e.target.value)}>
              <MenuItem value="">Any</MenuItem>
              {AGENTS.map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
            </Select>
          </FormControl>
          <TextField size="small" label="Borrower" value={filters.account_id} onChange={(e) => set('account_id', e.target.value)} sx={{ minWidth: 140 }} />
          {active > 0 && (
            <Button size="small" startIcon={<ClearAllIcon />} onClick={() => { setParams({}, { replace: true }); setPagination((p) => ({ ...p, page: 0 })); }} sx={{ color: tokens.navbarBg }}>
              Clear filters
            </Button>
          )}
          {data && <Chip size="small" label={`${data.total.toLocaleString()} decisions`} sx={{ fontSize: 11, fontWeight: 600, backgroundColor: '#eff0f0', ml: 'auto' }} />}
        </Stack>
        <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey, mt: 1 }}>
          Every routing decision is logged with its reason and the D12 rule ids that caused it. Click a row for the explanation.
        </Typography>
      </Paper>

      <Paper sx={{ borderRadius: 2.5, flex: 1, minHeight: 520 }}>
        <DataGrid
          rows={data?.items || []}
          columns={columns}
          getRowId={(r) => r.event_id}
          loading={loading && !data}
          rowCount={data?.total || 0}
          paginationMode="server"
          paginationModel={pagination}
          onPaginationModelChange={setPagination}
          pageSizeOptions={[25, 50, 100]}
          onRowClick={(p) => setSelected(p.row)}
          density="compact"
          disableRowSelectionOnClick
          disableColumnMenu
          sx={gridSx}
        />
      </Paper>

      <Drawer anchor="right" open={!!selected} onClose={() => setSelected(null)}>
        <Detail row={selected} onClose={() => setSelected(null)} />
      </Drawer>
    </Stack>
  );
}
