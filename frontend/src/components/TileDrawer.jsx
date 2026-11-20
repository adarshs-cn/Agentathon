import { Alert, Box, Drawer, IconButton, LinearProgress, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { tokens } from '../theme/muiTheme';

// The list behind one hero tile, opened in place. A row that belongs to a demo event selects it in the graph.
export default function TileDrawer({ tile, onClose, onPickEvent }) {
  const { data, error, loading } = useApi(() => (tile ? api.drilldown(tile) : Promise.resolve(null)), [tile], { live: true });
  return (
    <Drawer anchor="right" open={Boolean(tile)} onClose={onClose} PaperProps={{ sx: { width: { xs: '100%', sm: 560 }, boxShadow: tokens.cardShadow } }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ px: 2, py: 1.4, borderBottom: `1px solid ${tokens.dividerGrey}`, backgroundColor: tokens.cardGroupedBg }}>
        <Typography sx={{ fontSize: 14, fontWeight: 600, color: tokens.statTitleGrey }}>{data?.title || 'Details'}</Typography>
        <IconButton size="small" onClick={onClose} aria-label="Close"><CloseIcon fontSize="small" /></IconButton>
      </Stack>
      {loading && <LinearProgress />}
      <Box sx={{ p: 2 }} data-drawer={tile}>
        {error && <Alert severity="error">{error}</Alert>}
        {data?.summary && <Typography sx={{ fontSize: 12, color: tokens.statLabelGrey, mb: 1.5 }}>{data.summary}</Typography>}
        {data && data.rows.length === 0 && <Typography sx={{ fontSize: 12.5, color: tokens.statValueGrey }}>{data.empty}</Typography>}
        {data && data.rows.length > 0 && (
          <Table size="small">
            <TableHead>
              <TableRow>{data.columns.map(([k, label]) => <TableCell key={k} sx={{ fontSize: 11, fontWeight: 600, color: tokens.statLabelGrey }}>{label}</TableCell>)}</TableRow>
            </TableHead>
            <TableBody>
              {data.rows.map((r, i) => (
                <TableRow key={`${r.event_id || i}`} hover={Boolean(r.event_id)} onClick={r.event_id ? () => onPickEvent(r.event_id) : undefined} sx={{ cursor: r.event_id ? 'pointer' : 'default' }}>
                  {data.columns.map(([k]) => <TableCell key={k} sx={{ fontSize: 12 }}>{r[k]}</TableCell>)}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        {data?.rows?.some((r) => r.event_id) && <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey, mt: 1.5 }}>Click a row to show that event in the workflow.</Typography>}
      </Box>
    </Drawer>
  );
}
