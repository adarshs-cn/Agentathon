import { Chip } from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import ErrorIcon from '@mui/icons-material/Error';
import { tokens } from '../theme/muiTheme';

// Status is never color-only: every chip pairs an icon + a text label.
const VARIANTS = {
  healthy: { color: tokens.statusHealthy, icon: CheckCircleIcon, text: '#0c3d14' },
  degraded: { color: tokens.statusDegraded, icon: WarningAmberIcon, text: '#4d3b00' },
  fault: { color: tokens.statusFault, icon: ErrorIcon, text: '#ffffff' },
};

export default function StatusChip({ status, label }) {
  const v = VARIANTS[status] || VARIANTS.degraded;
  const Icon = v.icon;
  return (
    <Chip
      size="small"
      icon={<Icon sx={{ fontSize: 15, color: `${v.text} !important` }} />}
      label={label || status}
      sx={{
        backgroundColor: v.color,
        color: v.text,
        fontSize: 11,
        height: 22,
        fontWeight: 600,
      }}
    />
  );
}
