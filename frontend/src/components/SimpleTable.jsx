import { Box, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@mui/material';
import { tokens } from '../theme/muiTheme';

// A compact table for short lists, styled like the DataGrid header used on Accounts.
export default function SimpleTable({ columns, rows, onRowClick, maxHeight, empty = 'Nothing here yet', rowKey }) {
  return (
    <TableContainer sx={{ maxHeight }}>
      <Table size="small" stickyHeader>
        <TableHead>
          <TableRow>
            {columns.map((c) => (
              <TableCell
                key={c.key}
                align={c.align}
                sx={{
                  backgroundColor: tokens.cardGroupedBg,
                  fontSize: 10.5,
                  fontWeight: 700,
                  color: tokens.statTitleGrey,
                  borderBottom: `1px solid ${tokens.dividerGrey}`,
                  width: c.width,
                  whiteSpace: 'nowrap',
                }}
              >
                {c.label}
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={columns.length}>
                <Typography sx={{ fontSize: 12, color: tokens.statLabelGrey, py: 2, textAlign: 'center' }}>{empty}</Typography>
              </TableCell>
            </TableRow>
          )}
          {rows.map((r, i) => (
            <TableRow
              key={rowKey ? rowKey(r) : r.id ?? i}
              hover={!!onRowClick}
              onClick={onRowClick ? () => onRowClick(r) : undefined}
              sx={{ cursor: onRowClick ? 'pointer' : 'default', '&:last-child td': { borderBottom: 'none' } }}
            >
              {columns.map((c) => (
                <TableCell key={c.key} align={c.align} sx={{ fontSize: 12, borderBottom: `1px solid ${tokens.dividerGrey}`, py: 0.8 }}>
                  {c.render ? c.render(r) : <Box component="span">{r[c.key]}</Box>}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
