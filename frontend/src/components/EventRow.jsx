import { Box, Stack, Typography, Chip } from '@mui/material';
import MonoId from './MonoId';
import { RuleChips } from './RuleChip';
import { metaFor } from './eventTypes';
import { tokens } from '../theme/muiTheme';

function fmtTime(ts) {
  try {
    return new Date(ts).toISOString().slice(11, 19);
  } catch {
    return ts;
  }
}

export default function EventRow({ event, showAccount = true, onClick }) {
  const meta = metaFor(event.type);
  const Icon = meta.icon;
  return (
    <Stack
      direction="row"
      spacing={1.25}
      sx={{
        py: 1,
        px: 1,
        borderBottom: `1px solid ${tokens.dividerGrey}`,
        '&:last-child': { borderBottom: 'none' },
        ...(onClick && { cursor: 'pointer', '&:hover': { backgroundColor: tokens.cardGroupedBg } }),
      }}
      onClick={onClick}
    >
      <Box
        sx={{
          width: 24,
          height: 24,
          borderRadius: '50%',
          backgroundColor: `${meta.color}22`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          mt: 0.2,
        }}
      >
        <Icon sx={{ fontSize: 14, color: meta.color }} />
      </Box>
      <Box sx={{ minWidth: 0, flex: 1 }}>
        <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap">
          <MonoId className="tabular-nums" sx={{ fontSize: 11, color: tokens.statLabelGrey }}>
            {fmtTime(event.ts)}
          </MonoId>
          {showAccount && (
            <MonoId sx={{ fontSize: 11, color: tokens.navbarBg, fontWeight: 600 }}>
              {event.account_id}
            </MonoId>
          )}
          <Chip
            size="small"
            label={event.agent}
            sx={{
              height: 18,
              fontSize: 10,
              fontWeight: 600,
              backgroundColor: '#eff0f0',
              color: tokens.statTitleGrey,
            }}
          />
        </Stack>
        <Typography sx={{ fontSize: 12.5, fontWeight: 500, color: '#222933', mt: 0.25 }}>
          {meta.label}
          {event.decision ? `: ${event.decision}` : ''}
        </Typography>
        {event.reason && (
          <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey, mt: 0.1 }}>
            {event.reason}
          </Typography>
        )}
        {event.rule_ids?.length > 0 && (
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mt: 0.5 }}>
            <RuleChips ids={event.rule_ids} />
          </Stack>
        )}
      </Box>
    </Stack>
  );
}
