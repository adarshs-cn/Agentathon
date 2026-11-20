import { Box, Paper, Stack, Typography } from '@mui/material';
import { tokens } from '../theme/muiTheme';

// The card used everywhere: white Paper, grouped-grey header strip with a divider, 14px / 600 title.
// Identical to the "Live decision feed" card on the Overview.
export default function Section({ title, subtitle, action, children, sx, bodySx, noPad }) {
  return (
    <Paper sx={{ borderRadius: 2.5, overflow: 'hidden', ...sx }}>
      <Stack
        direction="row"
        alignItems="center"
        justifyContent="space-between"
        sx={{
          px: 2,
          py: 1.2,
          borderBottom: `1px solid ${tokens.dividerGrey}`,
          backgroundColor: tokens.cardGroupedBg,
        }}
      >
        <Box sx={{ minWidth: 0 }}>
          <Typography sx={{ fontSize: 14, fontWeight: 600, color: tokens.statTitleGrey }}>{title}</Typography>
          {subtitle && (
            <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey, mt: 0.1 }}>{subtitle}</Typography>
          )}
        </Box>
        {action}
      </Stack>
      <Box sx={{ p: noPad ? 0 : 2, ...bodySx }}>{children}</Box>
    </Paper>
  );
}
