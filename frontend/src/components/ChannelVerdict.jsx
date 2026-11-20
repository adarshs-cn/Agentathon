import { Box, Stack, Typography } from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import BlockIcon from '@mui/icons-material/Block';
import ScheduleIcon from '@mui/icons-material/Schedule';
import { RuleChips } from './RuleChip';
import { tokens } from '../theme/muiTheme';

const CHANNEL_LABEL = { whatsapp: 'WhatsApp', email: 'Email', call: 'Voice call', sms: 'SMS', field_visit: 'Field visit' };
const TONE = {
  OK: { icon: CheckCircleIcon, color: tokens.statusHealthy, word: 'allowed' },
  BLOCKED: { icon: BlockIcon, color: tokens.statusFault, word: 'blocked' },
  DEFERRED: { icon: ScheduleIcon, color: tokens.linkBlue, word: 'later' },
};

// One line per channel: what the policy engine decided for it, and which rules decided.
export default function ChannelVerdict({ channel, status, rule_ids, reason, defer_until }) {
  const t = TONE[status] || TONE.BLOCKED;
  const Icon = t.icon;
  return (
    <Stack direction="row" spacing={1} alignItems="flex-start" sx={{ py: 0.6 }}>
      <Icon sx={{ fontSize: 16, color: t.color, mt: 0.15 }} />
      <Box sx={{ minWidth: 0, flex: 1 }}>
        <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
          <Typography sx={{ fontSize: 12, fontWeight: 600, color: '#222933' }}>{CHANNEL_LABEL[channel] || channel}</Typography>
          <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey }}>{t.word}</Typography>
          <RuleChips ids={rule_ids} />
        </Stack>
        <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey }}>
          {reason}
          {defer_until ? ` (${defer_until.slice(0, 16).replace('T', ' ')})` : ''}
        </Typography>
      </Box>
    </Stack>
  );
}
