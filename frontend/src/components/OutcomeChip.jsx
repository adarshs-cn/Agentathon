import { Chip } from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import BlockIcon from '@mui/icons-material/Block';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import ScheduleIcon from '@mui/icons-material/Schedule';
import ErrorIcon from '@mui/icons-material/Error';
import RemoveCircleOutlineIcon from '@mui/icons-material/RemoveCircleOutline';
import { tokens } from '../theme/muiTheme';

// Same rule as StatusChip: never colour alone, always icon + text.
const VARIANTS = {
  CONTACTED: { bg: tokens.statusHealthy, fg: '#0c3d14', icon: CheckCircleIcon, text: 'Contacted' },
  BLOCKED: { bg: tokens.statusFault, fg: '#ffffff', icon: BlockIcon, text: 'Blocked' },
  SUPPRESSED: { bg: tokens.statusDegraded, fg: '#4d3b00', icon: WarningAmberIcon, text: 'Suppressed' },
  DEFERRED: { bg: tokens.linkBlue, fg: '#06304a', icon: ScheduleIcon, text: 'Deferred' },
  ESCALATED: { bg: tokens.statusFault, fg: '#ffffff', icon: ErrorIcon, text: 'Escalated' },
  REJECTED: { bg: '#eff0f0', fg: tokens.statTitleGrey, icon: RemoveCircleOutlineIcon, text: 'Rejected' },
  FAILED: { bg: tokens.statusFault, fg: '#ffffff', icon: ErrorIcon, text: 'Failed' },
};

export default function OutcomeChip({ outcome, label, sx }) {
  const v = VARIANTS[outcome] || { bg: '#eff0f0', fg: tokens.statTitleGrey, icon: RemoveCircleOutlineIcon, text: outcome || 'Pending' };
  const Icon = v.icon;
  return (
    <Chip
      size="small"
      icon={<Icon sx={{ fontSize: 14, color: `${v.fg} !important` }} />}
      label={label || v.text}
      sx={{ backgroundColor: v.bg, color: v.fg, fontSize: 11, height: 22, fontWeight: 600, ...sx }}
    />
  );
}

export { VARIANTS as OUTCOME_VARIANTS };
