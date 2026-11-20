import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Paper,
  Stack,
  Typography,
  TextField,
  Button,
  Collapse,
  Select,
  MenuItem,
  InputLabel,
  FormControl,
  Checkbox,
  FormControlLabel,
  Chip,
} from '@mui/material';
import { DataGrid } from '@mui/x-data-grid';
import TuneIcon from '@mui/icons-material/Tune';
import { api } from '../api/client';
import { useSim } from '../context/simState';
import MonoId from '../components/MonoId';
import { tokens } from '../theme/muiTheme';

const STATUS_COLORS = {
  current: tokens.statusHealthy,
  overdue: tokens.statusDegraded,
  restructured: tokens.linkBlue,
  settled: tokens.statLabelGrey,
  legal: tokens.statusFault,
};

const QUICK_FIELDS = [
  { key: 'account_id', label: 'Account No' },
  { key: 'customer_id', label: 'Customer No' },
  { key: 'borrower_name', label: 'Customer Name' },
  { key: 'contact_number', label: 'Contact Number' },
];

const money = (v) =>
  v == null ? '—' : `₹${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;

const columns = [
  {
    field: 'account_id',
    headerName: 'Account Number',
    width: 130,
    renderCell: (p) => <MonoId sx={{ fontSize: 12 }}>{p.value}</MonoId>,
  },
  {
    field: 'customer_id',
    headerName: 'Customer No',
    width: 110,
    renderCell: (p) => <MonoId sx={{ fontSize: 12 }}>{p.value}</MonoId>,
  },
  { field: 'borrower_name', headerName: 'Customer Name', width: 150 },
  { field: 'product', headerName: 'Product Segment', width: 140 },
  {
    field: 'loan_amount',
    headerName: 'Loan Amount',
    width: 120,
    type: 'number',
    valueFormatter: (p) => money(p.value),
  },
  {
    field: 'total_outstanding',
    headerName: 'Total O/S',
    width: 120,
    type: 'number',
    valueFormatter: (p) => money(p.value),
  },
  {
    field: 'principal_outstanding',
    headerName: 'POS',
    width: 110,
    type: 'number',
    valueFormatter: (p) => money(p.value),
  },
  {
    field: 'total_overdue',
    headerName: 'Total Overdue',
    width: 120,
    type: 'number',
    valueFormatter: (p) => money(p.value),
  },
  {
    field: 'installment_amount',
    headerName: 'Installment Amt',
    width: 120,
    type: 'number',
    valueFormatter: (p) => money(p.value),
  },
  {
    field: 'installment_overdue',
    headerName: 'Installment Overdue',
    width: 140,
    type: 'number',
    valueFormatter: (p) => money(p.value),
  },
  {
    field: 'dpd',
    headerName: 'DPD',
    width: 80,
    type: 'number',
    cellClassName: 'tabular-nums',
  },
  { field: 'delinquency_bucket', headerName: 'Bucket', width: 90 },
  {
    field: 'account_status',
    headerName: 'Status',
    width: 120,
    renderCell: (p) => (
      <Chip
        size="small"
        label={p.value}
        sx={{
          height: 20,
          fontSize: 10.5,
          fontWeight: 700,
          color: '#fff',
          backgroundColor: STATUS_COLORS[p.value] || tokens.statLabelGrey,
        }}
      />
    ),
  },
  {
    field: 'flags',
    headerName: 'Flags',
    width: 150,
    sortable: false,
    renderCell: (p) => (
      <Stack direction="row" spacing={0.5}>
        {p.row.restructure_flag && <Chip size="small" label="restr" sx={{ height: 18, fontSize: 9.5 }} />}
        {p.row.settlement_flag && <Chip size="small" label="settl" sx={{ height: 18, fontSize: 9.5 }} />}
        {p.row.legal_flag && <Chip size="small" label="legal" sx={{ height: 18, fontSize: 9.5 }} />}
      </Stack>
    ),
  },
  {
    field: 'case_owner_user_id',
    headerName: 'Current Owner',
    width: 130,
    renderCell: (p) => p.value || <span style={{ color: '#bbb' }}>unassigned</span>,
  },
  {
    field: 'last_disposition_date',
    headerName: 'Last Contact',
    width: 120,
    renderCell: (p) => p.value || <span style={{ color: '#bbb' }}>—</span>,
  },
  {
    field: 'contact_no',
    headerName: 'Contact No',
    width: 120,
    renderCell: (p) => <MonoId sx={{ fontSize: 11.5 }}>{p.value || '—'}</MonoId>,
  },
  { field: 'city', headerName: 'City', width: 110 },
];

// The columns a supervisor cares about come first; the two the data does not contain start hidden.
const ORDER = ['account_id', 'customer_id', 'borrower_name', 'dpd', 'delinquency_bucket', 'account_status', 'flags',
  'case_owner_user_id', 'last_disposition_date', 'product', 'loan_amount', 'total_overdue', 'principal_outstanding',
  'installment_amount', 'contact_no', 'city', 'total_outstanding', 'installment_overdue'];
const orderedColumns = [...columns].sort((a, b) => ORDER.indexOf(a.field) - ORDER.indexOf(b.field));

export default function Accounts() {
  const navigate = useNavigate();
  const [quick, setQuick] = useState({});
  const [advanceOpen, setAdvanceOpen] = useState(false);
  const [advance, setAdvance] = useState({});
  const [filterOptions, setFilterOptions] = useState(null);
  const [paginationModel, setPaginationModel] = useState({ page: 0, pageSize: 25 });
  const [sortModel, setSortModel] = useState([{ field: 'dpd', sort: 'desc' }]);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const { tick } = useSim();

  useEffect(() => {
    api.accountsFilterOptions().then(setFilterOptions).catch(() => {});
  }, []);

  const queryParams = useMemo(() => {
    const p = {
      page: paginationModel.page + 1,
      page_size: paginationModel.pageSize,
      sort_by: sortModel[0]?.field || 'dpd',
      sort_dir: sortModel[0]?.sort || 'desc',
    };
    Object.entries(quick).forEach(([k, v]) => v && (p[k] = v));
    Object.entries(advance).forEach(([k, v]) => {
      if (v === '' || v === undefined || v === null) return;
      p[k] = v;
    });
    return p;
  }, [quick, advance, paginationModel, sortModel]);

  useEffect(() => {
    setLoading(true);
    api
      .accountsList(queryParams)
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [queryParams]);

  // While the simulated day plays, owners and last-contact dates change: refresh the page quietly (no spinner).
  useEffect(() => {
    if (!tick) return;
    api.accountsList(queryParams).then(setData).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);

  if (error) {
    return (
      <Paper sx={{ p: 3, borderRadius: 2.5 }}>
        <Typography color="error">Could not reach the backend: {error}</Typography>
      </Paper>
    );
  }

  return (
    <Stack spacing={2} sx={{ height: '100%' }}>
      <Paper sx={{ p: 2, borderRadius: 2.5 }}>
        <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap">
          {QUICK_FIELDS.map((f) => (
            <TextField
              key={f.key}
              size="small"
              label={f.label}
              value={quick[f.key] || ''}
              onChange={(e) => {
                setQuick((q) => ({ ...q, [f.key]: e.target.value }));
                setPaginationModel((m) => ({ ...m, page: 0 }));
              }}
              sx={{ minWidth: 150 }}
            />
          ))}
          <FormControl size="small" sx={{ minWidth: 130 }}>
            <InputLabel>Account Status</InputLabel>
            <Select
              label="Account Status"
              value={quick.account_status || ''}
              onChange={(e) => {
                setQuick((q) => ({ ...q, account_status: e.target.value }));
                setPaginationModel((m) => ({ ...m, page: 0 }));
              }}
            >
              <MenuItem value="">Any</MenuItem>
              {['current', 'overdue', 'restructured', 'settled', 'legal'].map((s) => (
                <MenuItem key={s} value={s}>
                  {s}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Button
            variant={advanceOpen ? 'contained' : 'outlined'}
            size="small"
            startIcon={<TuneIcon sx={{ fontSize: 16 }} />}
            onClick={() => setAdvanceOpen((o) => !o)}
            sx={{
              backgroundColor: advanceOpen ? tokens.primaryButtonBg : '#fff',
              borderColor: tokens.secondaryButtonBorder,
              color: advanceOpen ? '#fff' : tokens.navbarBg,
            }}
          >
            Advance Filter
          </Button>
          {data && (
            <Chip
              size="small"
              label={`${data.total.toLocaleString()} accounts`}
              sx={{ fontSize: 11, fontWeight: 600, backgroundColor: '#eff0f0', ml: 'auto' }}
            />
          )}
        </Stack>
        <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey, mt: 1 }}>
          Click a row to open that customer&apos;s trace. Owner and last-contact columns update live while the simulated day plays.
          Total O/S and Installment Overdue are not in the source data (D1) and are hidden.
        </Typography>
      </Paper>

      <Collapse in={advanceOpen}>
        <Paper sx={{ p: 2, borderRadius: 2.5 }}>
          <Typography sx={{ fontSize: 13, fontWeight: 600, color: tokens.statTitleGrey, mb: 1.5 }}>
            Advance Filter
          </Typography>
          <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
            <FormControl size="small" sx={{ minWidth: 150 }}>
              <InputLabel>Product</InputLabel>
              <Select
                label="Product"
                value={advance.product || ''}
                onChange={(e) => setAdvance((a) => ({ ...a, product: e.target.value }))}
              >
                <MenuItem value="">Any</MenuItem>
                {(filterOptions?.products || []).map((p) => (
                  <MenuItem key={p} value={p}>
                    {p}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 130 }}>
              <InputLabel>Bucket</InputLabel>
              <Select
                label="Bucket"
                value={advance.bucket || ''}
                onChange={(e) => setAdvance((a) => ({ ...a, bucket: e.target.value }))}
              >
                <MenuItem value="">Any</MenuItem>
                {(filterOptions?.buckets || []).map((b) => (
                  <MenuItem key={b} value={b}>
                    {b}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 150 }}>
              <InputLabel>City</InputLabel>
              <Select
                label="City"
                value={advance.city || ''}
                onChange={(e) => setAdvance((a) => ({ ...a, city: e.target.value }))}
              >
                <MenuItem value="">Any</MenuItem>
                {(filterOptions?.cities || []).map((c) => (
                  <MenuItem key={c} value={c}>
                    {c}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              size="small"
              label="DPD min"
              type="number"
              value={advance.dpd_min || ''}
              onChange={(e) => setAdvance((a) => ({ ...a, dpd_min: e.target.value }))}
              sx={{ width: 100 }}
            />
            <TextField
              size="small"
              label="DPD max"
              type="number"
              value={advance.dpd_max || ''}
              onChange={(e) => setAdvance((a) => ({ ...a, dpd_max: e.target.value }))}
              sx={{ width: 100 }}
            />
            <TextField
              size="small"
              label="Loan min"
              type="number"
              value={advance.loan_min || ''}
              onChange={(e) => setAdvance((a) => ({ ...a, loan_min: e.target.value }))}
              sx={{ width: 110 }}
            />
            <TextField
              size="small"
              label="Loan max"
              type="number"
              value={advance.loan_max || ''}
              onChange={(e) => setAdvance((a) => ({ ...a, loan_max: e.target.value }))}
              sx={{ width: 110 }}
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={!!advance.restructure}
                  onChange={(e) => setAdvance((a) => ({ ...a, restructure: e.target.checked || undefined }))}
                />
              }
              label="Restructured"
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={!!advance.settlement}
                  onChange={(e) => setAdvance((a) => ({ ...a, settlement: e.target.checked || undefined }))}
                />
              }
              label="Settlement"
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={!!advance.legal}
                  onChange={(e) => setAdvance((a) => ({ ...a, legal: e.target.checked || undefined }))}
                />
              }
              label="Legal"
            />
            <Button
              size="small"
              onClick={() => {
                setAdvance({});
                setQuick({});
              }}
            >
              Clear all
            </Button>
          </Stack>
        </Paper>
      </Collapse>

      <Paper sx={{ borderRadius: 2.5, flex: 1, minHeight: 500 }}>
        <DataGrid
          rows={data?.items || []}
          columns={orderedColumns}
          initialState={{ columns: { columnVisibilityModel: { total_outstanding: false, installment_overdue: false } } }}
          getRowId={(r) => r.account_id}
          loading={loading}
          rowCount={data?.total || 0}
          paginationMode="server"
          sortingMode="server"
          paginationModel={paginationModel}
          onPaginationModelChange={setPaginationModel}
          sortModel={sortModel}
          onSortModelChange={setSortModel}
          pageSizeOptions={[25, 50, 100]}
          onRowClick={(params) => navigate(`/trace?account=${params.row.account_id}`)}
          density="compact"
          disableRowSelectionOnClick
          sx={{
            border: 'none',
            fontSize: 12.5,
            '& .MuiDataGrid-columnHeaders': {
              backgroundColor: tokens.cardGroupedBg,
              fontSize: 10.5,
              fontWeight: 700,
              color: tokens.statTitleGrey,
            },
            '& .MuiDataGrid-row': { cursor: 'pointer' },
          }}
        />
      </Paper>
    </Stack>
  );
}
