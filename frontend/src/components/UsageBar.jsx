import { Box, LinearProgress, Stack, Typography } from '@mui/material';
import { tokens } from '../theme/muiTheme';

// Usage against a limit. Colour follows the status tokens AND the label says it in words.
export default function UsageBar({ used, cap, label, unit = '', digits = 0, height = 6 }) {
  const ratio = cap ? used / cap : 0;
  const tone = ratio >= 1 ? tokens.statusFault : ratio >= 0.8 ? tokens.statusDegraded : tokens.statusHealthy;
  const word = ratio >= 1 ? 'at limit' : ratio >= 0.8 ? 'near limit' : '';
  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="baseline">
        {label && <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey }}>{label}</Typography>}
        <Typography className="tabular-nums" sx={{ fontSize: 11, color: tokens.statValueGrey, fontWeight: 600 }}>
          {Number(used).toLocaleString('en-IN', { maximumFractionDigits: digits })}
          {cap != null ? ` / ${Number(cap).toLocaleString('en-IN', { maximumFractionDigits: digits })}` : ''}
          {unit} {word && <span style={{ color: ratio >= 1 ? tokens.statusFault : '#8a6d00' }}>· {word}</span>}
        </Typography>
      </Stack>
      <LinearProgress
        variant="determinate"
        value={Math.min(100, 100 * ratio)}
        sx={{
          height,
          borderRadius: height / 2,
          mt: 0.4,
          backgroundColor: tokens.iconBadgeBg,
          '& .MuiLinearProgress-bar': { backgroundColor: tone },
        }}
      />
    </Box>
  );
}
